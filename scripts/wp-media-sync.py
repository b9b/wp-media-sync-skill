#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import mimetypes
import os
import posixpath
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


URL_RE = re.compile(r"https?://[^\s\"'<>()\]\[]+", re.IGNORECASE)
IFRAME_RE = re.compile(r"<iframe\b.*?</iframe\s*>", re.IGNORECASE | re.DOTALL)
TRAILING_URL_CHARS = ".,;:!?\"'"

MEDIA_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".svg", ".bmp", ".ico",
    ".mp3", ".wav", ".ogg", ".m4a", ".flac",
    ".mp4", ".mov", ".webm", ".avi", ".mkv", ".m4v", ".wmv", ".flv",
    ".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".zip",
}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".avi", ".mkv", ".m4v", ".wmv", ".flv"}
MEDIA_CONTENT_PREFIXES = ("image/", "audio/", "video/")
MEDIA_CONTENT_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/zip",
}
EXTERNAL_VIDEO_HOST_KEYWORDS = (
    "youtube.com", "youtu.be", "vimeo.com", "bilibili.com", "dailymotion.com",
    "twitch.tv", "tiktok.com", "youku.com", "iqiyi.com", "v.qq.com",
)
URL_FIELD_KEYS = {"url", "src", "href", "source_url", "media_url", "image_url"}
ID_FIELD_KEYS = {"id", "media_id", "attachment_id", "image_id", "thumbnail_id"}
USER_AGENT = "wp-media-sync/1.0"
SVG_MARKER = "wp-media-sync svg upload support"
class FatalSyncError(RuntimeError):
    pass


class SkipMedia(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="把 HTML/JSON/文本中的远程媒体通过 SSH + WP-CLI 同步到 WordPress，并回写 URL/附件 ID。"
    )
    parser.add_argument("--project-root", default=".", help="项目根目录，默认当前目录。")
    parser.add_argument("--input", required=True, help="输入文件路径；使用 - 从 stdin 读取。")
    parser.add_argument("--output", help="输出文件路径；不填写则写入 stdout。")
    parser.add_argument("--format", choices=("auto", "json", "html", "text"), default="auto", help="输入格式。")
    parser.add_argument("--report", help="可选：写入同步报告 JSON。")
    parser.add_argument("--max-video-mb", type=int, default=20, help="视频文件最大上传 MB，默认 20。")
    parser.add_argument("--no-svg-enable", action="store_true", help="不自动在当前主题 functions.php 打开 SVG 上传。")
    return parser.parse_args()


def read_env_file(project_root: Path) -> dict[str, str]:
    env_path = project_root / ".env"
    if not env_path.exists():
        raise FatalSyncError(f"未找到 .env: {env_path}")

    env: dict[str, str] = {}
    for line_no, raw_line in enumerate(env_path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            raise FatalSyncError(f".env 第 {line_no} 行不是 KEY=VALUE 格式")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            env[key] = value

    for key in ("SSH_HOST", "SSH_PORT", "SSH_USER", "WP_PATH"):
        if not env.get(key):
            raise FatalSyncError(f".env 缺少必填项: {key}")
    return env


def ensure_media_store(project_root: Path) -> tuple[Path, Path]:
    media_dir = project_root / "media"
    files_dir = media_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    log_path = media_dir / "log.json"
    if not log_path.exists():
        write_json_atomic(log_path, {"version": 1, "uploads": {}})
    return files_dir, log_path


def write_json_atomic(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def load_log(log_path: Path) -> dict:
    try:
        data = json.loads(log_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FatalSyncError(f"media/log.json 不是合法 JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise FatalSyncError("media/log.json 根节点必须是对象")
    data.setdefault("version", 1)
    uploads = data.setdefault("uploads", {})
    if not isinstance(uploads, dict):
        raise FatalSyncError("media/log.json 的 uploads 必须是对象")
    return data


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def source_key(url: str) -> str:
    return html.unescape(url).strip()


def trim_url(raw_url: str) -> tuple[str, str]:
    url = raw_url
    suffix = ""
    while url and url[-1] in TRAILING_URL_CHARS:
        suffix = url[-1] + suffix
        url = url[:-1]
    return url, suffix


def url_extension(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    return Path(urllib.parse.unquote(parsed.path)).suffix.lower()


def host_matches_external_video(url: str) -> bool:
    host = urllib.parse.urlparse(url).netloc.lower()
    return any(keyword in host for keyword in EXTERNAL_VIDEO_HOST_KEYWORDS)


def is_http_url(url: str) -> bool:
    return urllib.parse.urlparse(url).scheme.lower() in {"http", "https"}


def request_headers(url: str) -> dict[str, str]:
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return {key.lower(): value for key, value in response.headers.items()}
    except Exception:
        return {}


def media_type_from_headers(headers: dict[str, str]) -> str:
    return headers.get("content-type", "").split(";", 1)[0].strip().lower()


def content_length(headers: dict[str, str]) -> int | None:
    raw = headers.get("content-length")
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def is_media_candidate(url: str, headers: dict[str, str]) -> bool:
    ext = url_extension(url)
    if ext in MEDIA_EXTENSIONS:
        return True
    content_type = media_type_from_headers(headers)
    return content_type.startswith(MEDIA_CONTENT_PREFIXES) or content_type in MEDIA_CONTENT_TYPES


def is_video_candidate(url: str, headers: dict[str, str]) -> bool:
    ext = url_extension(url)
    content_type = media_type_from_headers(headers)
    return ext in VIDEO_EXTENSIONS or content_type.startswith("video/")


def safe_filename_from_url(url: str, headers: dict[str, str]) -> str:
    parsed = urllib.parse.urlparse(url)
    base = Path(urllib.parse.unquote(parsed.path)).name
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip(".-")
    if not base:
        content_type = media_type_from_headers(headers)
        ext = mimetypes.guess_extension(content_type) or ".bin"
        base = "media" + ext
    if "." not in base:
        ext = mimetypes.guess_extension(media_type_from_headers(headers)) or ""
        base += ext
    prefix = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{base[:120]}"


def find_upload_by_sha(log_data: dict, file_sha: str) -> dict | None:
    for item in log_data.get("uploads", {}).values():
        if item.get("sha256") == file_sha and item.get("attachment_id") and item.get("remote_url"):
            return item
    return None


def download_to_cache(url: str, headers: dict[str, str], files_dir: Path, max_video_bytes: int) -> tuple[Path, int, str]:
    is_video = is_video_candidate(url, headers)
    known_length = content_length(headers)
    if is_video and known_length is None:
        raise SkipMedia(f"视频无法确认大小，保持原样: {url}")
    if is_video and known_length is not None and known_length > max_video_bytes:
        raise SkipMedia(f"视频超过 {max_video_bytes // 1024 // 1024} MB，保持原样: {url}")

    filename = safe_filename_from_url(url, headers)
    target = files_dir / filename
    if target.exists():
        return target, target.stat().st_size, sha256_file(target)

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    tmp_fd, tmp_name = tempfile.mkstemp(prefix=filename + ".", suffix=".part", dir=str(files_dir))
    os.close(tmp_fd)
    tmp_path = Path(tmp_name)

    total = 0
    try:
        with urllib.request.urlopen(request, timeout=60) as response, tmp_path.open("wb") as out:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if is_video and total > max_video_bytes:
                    raise SkipMedia(f"视频下载中超过 {max_video_bytes // 1024 // 1024} MB，保持原样: {url}")
                out.write(chunk)
        tmp_path.replace(target)
    except SkipMedia:
        tmp_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        raise FatalSyncError(f"下载失败: {url}\n{exc}") from exc

    return target, total, sha256_file(target)


def validate_svg(path: Path) -> None:
    raw = path.read_bytes()
    lowered = raw[:4096].lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise FatalSyncError(f"SVG 安全校验失败，包含 DOCTYPE 或 ENTITY: {path}")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise FatalSyncError(f"SVG 不是合法 XML: {path}: {exc}") from exc

    forbidden_tags = {"script", "iframe", "object", "embed", "foreignobject"}
    for elem in root.iter():
        tag = elem.tag.rsplit("}", 1)[-1].lower()
        if tag in forbidden_tags:
            raise FatalSyncError(f"SVG 安全校验失败，包含禁止标签 <{tag}>: {path}")
        for attr_name, attr_value in elem.attrib.items():
            name = attr_name.rsplit("}", 1)[-1].lower()
            value = html.unescape(attr_value).strip().lower()
            if name.startswith("on"):
                raise FatalSyncError(f"SVG 安全校验失败，包含事件属性 {name}: {path}")
            if name in {"href", "src"}:
                if value.startswith(("javascript:", "http://", "https://", "data:text/html")):
                    raise FatalSyncError(f"SVG 安全校验失败，包含危险引用 {attr_value!r}: {path}")


def ssh_base_args(env: dict[str, str]) -> list[str]:
    args = [
        "ssh",
        "-p", env["SSH_PORT"],
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
    ]
    if env.get("SSH_KEY_PATH"):
        args.extend(["-i", env["SSH_KEY_PATH"]])
    if env.get("SSH_EXTRA_OPTS"):
        args.extend(shlex.split(env["SSH_EXTRA_OPTS"]))
    return args


def scp_base_args(env: dict[str, str]) -> list[str]:
    args = [
        "scp",
        "-P", env["SSH_PORT"],
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
    ]
    if env.get("SSH_KEY_PATH"):
        args.extend(["-i", env["SSH_KEY_PATH"]])
    if env.get("SSH_EXTRA_OPTS"):
        args.extend(shlex.split(env["SSH_EXTRA_OPTS"]))
    return args


def ssh_target(env: dict[str, str]) -> str:
    return f"{env['SSH_USER']}@{env['SSH_HOST']}"


def run_command(args: list[str], *, description: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, text=True, capture_output=True)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        detail = "\n".join(part for part in (stdout, stderr) if part)
        raise FatalSyncError(f"{description}失败: {detail or '无输出'}")
    return result


def run_ssh(env: dict[str, str], command: str, description: str) -> str:
    args = ssh_base_args(env) + [ssh_target(env), command]
    return run_command(args, description=description).stdout.strip()


def wp_command(env: dict[str, str], wp_args: list[str], description: str) -> str:
    wp_bin = env.get("WP_CLI_BIN", "wp")
    allow_root = ["--allow-root"] if env.get("WP_ALLOW_ROOT", "").lower() in {"1", "true", "yes"} else []
    quoted_args = " ".join(shlex.quote(arg) for arg in wp_args + allow_root)
    command = f"cd {shlex.quote(env['WP_PATH'])} && {shlex.quote(wp_bin)} {quoted_args}"
    return run_ssh(env, command, description)


def check_remote_wp_cli(env: dict[str, str]) -> None:
    try:
        wp_command(env, ["--info"], "检查远端 WP-CLI")
    except FatalSyncError as exc:
        wp_bin = env.get("WP_CLI_BIN", "wp")
        raise FatalSyncError(
            "远端 WP-CLI 不存在或无法执行，已终止。"
            f"请在远端安装 WP-CLI，或在 .env 中把 WP_CLI_BIN 配置为可执行的 WP-CLI 路径。当前 WP_CLI_BIN={wp_bin!r}。"
            "本 Skill 不会尝试 REST API、后台表单、XML-RPC 或其他上传方式。\n"
            f"{exc}"
        ) from exc


def ensure_svg_upload_support(env: dict[str, str]) -> None:
    wp_bin = shlex.quote(env.get("WP_CLI_BIN", "wp"))
    allow_root = " --allow-root" if env.get("WP_ALLOW_ROOT", "").lower() in {"1", "true", "yes"} else ""
    snippet = f"""

// {SVG_MARKER}
add_filter('upload_mimes', function ($mimes) {{
    $mimes['svg'] = 'image/svg+xml';
    $mimes['svgz'] = 'image/svg+xml';
    return $mimes;
}});
add_filter('wp_check_filetype_and_ext', function ($data, $file, $filename, $mimes) {{
    $ext = strtolower(pathinfo($filename, PATHINFO_EXTENSION));
    if ($ext === 'svg' || $ext === 'svgz') {{
        $data['ext'] = $ext;
        $data['type'] = 'image/svg+xml';
    }}
    return $data;
}}, 10, 4);
"""
    command = f"""set -eu
cd {shlex.quote(env['WP_PATH'])}
theme_dir=$({wp_bin} eval 'echo get_stylesheet_directory();'{allow_root})
if [ -z "$theme_dir" ]; then
  echo "无法获取当前主题目录" >&2
  exit 1
fi
functions_file="$theme_dir/functions.php"
touch "$functions_file"
if ! grep -q {shlex.quote(SVG_MARKER)} "$functions_file"; then
  cat >> "$functions_file" <<'PHP'
{snippet}
PHP
fi
"""
    run_ssh(env, command, "打开 SVG 上传支持")


def upload_with_wp_cli(env: dict[str, str], local_path: Path, is_svg: bool, enable_svg: bool) -> tuple[int, str]:
    if is_svg and enable_svg:
        ensure_svg_upload_support(env)

    remote_tmp_dir = env.get("WP_REMOTE_TMP_DIR", "/tmp/wp-media-sync").rstrip("/") or "/tmp/wp-media-sync"
    run_ssh(env, f"mkdir -p {shlex.quote(remote_tmp_dir)}", "创建远端临时目录")

    remote_name = re.sub(r"[^A-Za-z0-9._-]+", "-", local_path.name)
    remote_path = posixpath.join(remote_tmp_dir, remote_name)
    scp_target = f"{ssh_target(env)}:{remote_path}"
    run_command(scp_base_args(env) + [str(local_path), scp_target], description="复制媒体到远端")

    upload_error: Exception | None = None
    try:
        attachment_id_raw = wp_command(
            env,
            ["media", "import", remote_path, "--porcelain", f"--title={local_path.stem}"],
            "WP-CLI 媒体上传",
        )
        lines = [line.strip() for line in attachment_id_raw.splitlines() if line.strip()]
        if not lines:
            raise FatalSyncError("WP-CLI 媒体上传成功返回为空，无法取得附件 ID")
        try:
            attachment_id = int(lines[-1])
        except ValueError as exc:
            raise FatalSyncError(f"WP-CLI 返回的附件 ID 无法解析: {attachment_id_raw!r}") from exc
        remote_url = wp_command(env, ["eval", f"echo wp_get_attachment_url({attachment_id});"], "读取附件 URL")
    except Exception as exc:
        upload_error = exc
        raise
    finally:
        try:
            run_ssh(env, f"rm -f {shlex.quote(remote_path)}", "清理远端临时文件")
        except FatalSyncError as cleanup_exc:
            if upload_error is None:
                print(f"提示: 远端临时文件清理失败: {cleanup_exc}", file=sys.stderr)

    if not remote_url:
        raise FatalSyncError(f"附件 {attachment_id} 上传成功但未能读取远端 URL")
    return attachment_id, remote_url


class SyncContext:
    def __init__(self, project_root: Path, env: dict[str, str], max_video_bytes: int, enable_svg: bool):
        self.project_root = project_root
        self.env = env
        self.files_dir, self.log_path = ensure_media_store(project_root)
        self.log_data = load_log(self.log_path)
        self.max_video_bytes = max_video_bytes
        self.enable_svg = enable_svg
        self.url_cache: dict[str, dict] = {}
        self.warnings: list[str] = []
        self.processed: list[dict] = []

    def save_log(self) -> None:
        write_json_atomic(self.log_path, self.log_data)

    def warn(self, message: str) -> None:
        self.warnings.append(message)
        print(f"提示: {message}", file=sys.stderr)


def sync_url(ctx: SyncContext, raw_url: str) -> dict | None:
    clean_url = source_key(raw_url)
    if clean_url in ctx.url_cache:
        return ctx.url_cache[clean_url]
    if not is_http_url(clean_url):
        return None
    if host_matches_external_video(clean_url):
        ctx.warn(f"外链视频保持原样: {clean_url}")
        return None

    existing = ctx.log_data["uploads"].get(clean_url)
    if existing and existing.get("attachment_id") and existing.get("remote_url"):
        result = {
            "source_url": clean_url,
            "attachment_id": int(existing["attachment_id"]),
            "remote_url": existing["remote_url"],
            "reused": True,
        }
        ctx.url_cache[clean_url] = result
        return result

    headers = request_headers(clean_url)
    if not is_media_candidate(clean_url, headers):
        return None

    try:
        local_path, size, file_sha = download_to_cache(clean_url, headers, ctx.files_dir, ctx.max_video_bytes)
    except SkipMedia as exc:
        ctx.warn(exc.reason)
        return None

    sha_existing = find_upload_by_sha(ctx.log_data, file_sha)
    if sha_existing:
        entry = dict(sha_existing)
        entry.update({
            "source_url": clean_url,
            "local_path": str(local_path.relative_to(ctx.project_root)),
            "sha256": file_sha,
            "bytes": size,
            "reused_from_sha256": True,
            "updated_at": now_iso(),
        })
        ctx.log_data["uploads"][clean_url] = entry
        ctx.save_log()
        result = {
            "source_url": clean_url,
            "attachment_id": int(entry["attachment_id"]),
            "remote_url": entry["remote_url"],
            "reused": True,
        }
        ctx.url_cache[clean_url] = result
        return result

    is_svg = local_path.suffix.lower() == ".svg" or media_type_from_headers(headers) == "image/svg+xml"
    if is_svg:
        validate_svg(local_path)

    attachment_id, remote_url = upload_with_wp_cli(ctx.env, local_path, is_svg=is_svg, enable_svg=ctx.enable_svg)
    entry = {
        "source_url": clean_url,
        "local_path": str(local_path.relative_to(ctx.project_root)),
        "sha256": file_sha,
        "bytes": size,
        "attachment_id": attachment_id,
        "remote_url": remote_url,
        "uploaded_at": now_iso(),
        "site": {
            "ssh_host": ctx.env["SSH_HOST"],
            "wp_path": ctx.env["WP_PATH"],
        },
    }
    ctx.log_data["uploads"][clean_url] = entry
    ctx.save_log()

    result = {
        "source_url": clean_url,
        "attachment_id": attachment_id,
        "remote_url": remote_url,
        "reused": False,
    }
    ctx.url_cache[clean_url] = result
    ctx.processed.append(result)
    return result


def iframe_spans(text: str) -> list[tuple[int, int]]:
    return [(match.start(), match.end()) for match in IFRAME_RE.finditer(text)]


def position_in_spans(position: int, spans: list[tuple[int, int]]) -> bool:
    return any(start <= position < end for start, end in spans)


def rewrite_string(ctx: SyncContext, text: str, *, skip_iframes: bool = False) -> tuple[str, list[dict]]:
    spans = iframe_spans(text) if skip_iframes else []
    replacements: list[dict] = []

    def replace_match(match: re.Match[str]) -> str:
        if spans and position_in_spans(match.start(), spans):
            return match.group(0)
        raw_trimmed, suffix = trim_url(match.group(0))
        try:
            result = sync_url(ctx, raw_trimmed)
        except urllib.error.URLError as exc:
            raise FatalSyncError(f"处理 URL 失败: {raw_trimmed}\n{exc}") from exc
        if not result:
            return match.group(0)
        replacements.append(result)
        return result["remote_url"] + suffix

    return URL_RE.sub(replace_match, text), replacements


def rewrite_json_value(ctx: SyncContext, value):
    if isinstance(value, str):
        return rewrite_string(ctx, value, skip_iframes=False)
    if isinstance(value, list):
        output = []
        replacements: list[dict] = []
        for item in value:
            new_item, item_replacements = rewrite_json_value(ctx, item)
            output.append(new_item)
            replacements.extend(item_replacements)
        return output, replacements
    if isinstance(value, dict):
        output = {}
        replacements: list[dict] = []
        direct_url_replacements: list[dict] = []
        for key, item in value.items():
            new_item, item_replacements = rewrite_json_value(ctx, item)
            output[key] = new_item
            replacements.extend(item_replacements)
            if key in URL_FIELD_KEYS and item_replacements:
                direct_url_replacements.extend(item_replacements)
        if direct_url_replacements:
            latest = direct_url_replacements[-1]
            for id_key in ID_FIELD_KEYS:
                if id_key in output:
                    output[id_key] = latest["attachment_id"]
        return output, replacements
    return value, []


def detect_format(raw: str, input_path: str, explicit: str) -> str:
    if explicit != "auto":
        return explicit
    if input_path != "-":
        suffix = Path(input_path).suffix.lower()
        if suffix == ".json":
            return "json"
        if suffix in {".html", ".htm"}:
            return "html"
    try:
        json.loads(raw)
        return "json"
    except Exception:
        pass
    if re.search(r"<[A-Za-z][^>]*>", raw):
        return "html"
    return "text"


def read_input(input_arg: str) -> str:
    if input_arg == "-":
        return sys.stdin.read()
    return Path(input_arg).read_text(encoding="utf-8")


def write_output(output_arg: str | None, text: str) -> None:
    if output_arg:
        Path(output_arg).parent.mkdir(parents=True, exist_ok=True)
        Path(output_arg).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


def main() -> int:
    args = parse_args()
    project_root = Path(args.project_root).resolve()
    if not shutil.which("ssh"):
        raise FatalSyncError("本机未找到 ssh 命令")
    if not shutil.which("scp"):
        raise FatalSyncError("本机未找到 scp 命令")

    env = read_env_file(project_root)
    check_remote_wp_cli(env)
    ctx = SyncContext(
        project_root=project_root,
        env=env,
        max_video_bytes=args.max_video_mb * 1024 * 1024,
        enable_svg=not args.no_svg_enable,
    )

    raw = read_input(args.input)
    input_format = detect_format(raw, args.input, args.format)

    if input_format == "json":
        data = json.loads(raw)
        rewritten, _ = rewrite_json_value(ctx, data)
        output = json.dumps(rewritten, ensure_ascii=False, indent=2) + "\n"
    else:
        output, _ = rewrite_string(ctx, raw, skip_iframes=(input_format == "html"))

    write_output(args.output, output)

    if args.report:
        report = {
            "format": input_format,
            "processed": ctx.processed,
            "warnings": ctx.warnings,
            "log_path": str(ctx.log_path),
        }
        write_json_atomic(Path(args.report), report)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except FatalSyncError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        raise SystemExit(1)
