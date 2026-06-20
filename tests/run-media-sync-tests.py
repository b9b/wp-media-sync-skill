#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import functools
import http.server
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures"
RUNTIME_DIR = PROJECT_ROOT / "tests" / "runtime"
SOURCE_DIR = RUNTIME_DIR / "source"
OUTPUT_DIR = RUNTIME_DIR / "output"
OFFLINE_PROJECT_DIR = RUNTIME_DIR / "offline-project"
FAKE_BIN_DIR = RUNTIME_DIR / "fake-bin"
DOCKER_LIVE_DIR = PROJECT_ROOT / "tests" / "docker-live"
DOCKER_RUNTIME_DIR = RUNTIME_DIR / "docker"
DOCKER_PROJECT_DIR = RUNTIME_DIR / "docker-project"
DOCKER_COMPOSE_PROJECT = "wp-media-sync-docker-live"
TEST_IMAGE_NAME = "wp-media-sync-test.png"
FAKE_ATTACHMENT_ID = 987654
FAKE_REMOTE_URL = "https://example.test/wp-content/uploads/wp-media-sync-test.png"


class TestFailure(RuntimeError):
    pass


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        return


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行 wp-media-sync 可复用测试流程。")
    parser.add_argument("--live", action="store_true", help="执行真实 SSH/WP-CLI 上传链路测试。")
    parser.add_argument("--docker-live", action="store_true", help="启动隔离 Docker WordPress 环境，执行真实 SSH/WP-CLI 上传测试。")
    parser.add_argument("--keep-docker", action="store_true", help="保留 docker-live 容器和卷，方便失败后排查。")
    parser.add_argument("--port", type=int, default=8765, help="本地测试 HTTP 服务端口；默认 8765。")
    parser.add_argument("--keep-runtime", action="store_true", help="保留 tests/runtime 中已有文件。")
    return parser.parse_args()


def reset_runtime(keep_runtime: bool) -> None:
    if RUNTIME_DIR.exists() and not keep_runtime:
        shutil.rmtree(RUNTIME_DIR)
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def write_test_image() -> None:
    raw = (FIXTURES_DIR / f"{TEST_IMAGE_NAME}.base64").read_text(encoding="utf-8").strip()
    (SOURCE_DIR / TEST_IMAGE_NAME).write_bytes(base64.b64decode(raw))


def render_templates(base_url: str) -> tuple[Path, Path]:
    json_input = RUNTIME_DIR / "sample-input.json"
    html_input = RUNTIME_DIR / "sample-input.html"
    for target, template_name in (
        (json_input, "sample-input.json.tpl"),
        (html_input, "sample-input.html.tpl"),
    ):
        template = (FIXTURES_DIR / template_name).read_text(encoding="utf-8")
        target.write_text(template.replace("__MEDIA_BASE_URL__", base_url), encoding="utf-8")
    return json_input, html_input


def start_http_server(port: int):
    handler = functools.partial(QuietHandler, directory=str(SOURCE_DIR))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    actual_port = server.server_address[1]
    return server, f"http://127.0.0.1:{actual_port}"


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def run_command(
    name: str,
    args: list[str],
    *,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=PROJECT_ROOT, text=True, capture_output=True, env=env)
    (OUTPUT_DIR / f"{name}.stdout").write_text(result.stdout, encoding="utf-8")
    (OUTPUT_DIR / f"{name}.stderr").write_text(result.stderr, encoding="utf-8")
    if check and result.returncode != 0:
        raise TestFailure(
            f"{name} 失败，退出码 {result.returncode}\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return result


def docker_compose_args(extra_args: list[str]) -> list[str]:
    return [
        "docker",
        "compose",
        "-f",
        str(DOCKER_LIVE_DIR / "docker-compose.yml"),
        "-p",
        DOCKER_COMPOSE_PROJECT,
        *extra_args,
    ]


def docker_env(ssh_port: int, http_port: int) -> dict[str, str]:
    env = dict(os.environ)
    env["WP_MEDIA_SYNC_DOCKER_SSH_PORT"] = str(ssh_port)
    env["WP_MEDIA_SYNC_DOCKER_HTTP_PORT"] = str(http_port)
    return env


def prepare_offline_project(base_url: str) -> None:
    if OFFLINE_PROJECT_DIR.exists():
        shutil.rmtree(OFFLINE_PROJECT_DIR)
    (OFFLINE_PROJECT_DIR / "media" / "files").mkdir(parents=True, exist_ok=True)
    (OFFLINE_PROJECT_DIR / ".env").write_text(
        "SSH_HOST=127.0.0.1\n"
        "SSH_PORT=22\n"
        "SSH_USER=offline-test\n"
        "WP_PATH=/var/www/html\n",
        encoding="utf-8",
    )
    source_url = f"{base_url}/{TEST_IMAGE_NAME}"
    log_data = {
        "version": 1,
        "uploads": {
            source_url: {
                "source_url": source_url,
                "local_path": f"media/files/{TEST_IMAGE_NAME}",
                "sha256": "offline-fixture",
                "bytes": (SOURCE_DIR / TEST_IMAGE_NAME).stat().st_size,
                "attachment_id": FAKE_ATTACHMENT_ID,
                "remote_url": FAKE_REMOTE_URL,
                "uploaded_at": "2026-06-20T00:00:00+00:00",
            }
        },
    }
    (OFFLINE_PROJECT_DIR / "media" / "log.json").write_text(
        json.dumps(log_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def prepare_fake_cli_tools() -> dict[str, str]:
    FAKE_BIN_DIR.mkdir(parents=True, exist_ok=True)
    fake_ssh = FAKE_BIN_DIR / "ssh"
    fake_scp = FAKE_BIN_DIR / "scp"
    fake_ssh.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
remote_cmd="${@: -1}"
if [[ "$remote_cmd" == *"--info"* ]]; then
  printf 'OS:\\tFake\\nShell:\\tFake\\nPHP binary:\\t/usr/bin/php\\nWP-CLI root dir:\\tfake\\n'
  exit 0
fi
echo "offline fake ssh received unexpected command: $remote_cmd" >&2
exit 77
""",
        encoding="utf-8",
    )
    fake_scp.write_text(
        """#!/usr/bin/env bash
echo "offline fake scp should not be called" >&2
exit 77
""",
        encoding="utf-8",
    )
    fake_ssh.chmod(0o755)
    fake_scp.chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = f"{FAKE_BIN_DIR}:{env.get('PATH', '')}"
    return env


def generate_docker_ssh_key() -> Path:
    DOCKER_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    key_path = DOCKER_RUNTIME_DIR / "id_ed25519"
    if key_path.exists() and key_path.with_suffix(".pub").exists():
        return key_path
    run_command(
        "docker-ssh-keygen",
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key_path)],
    )
    return key_path


def prepare_docker_project(ssh_port: int, key_path: Path) -> None:
    if DOCKER_PROJECT_DIR.exists():
        shutil.rmtree(DOCKER_PROJECT_DIR)
    (DOCKER_PROJECT_DIR / "media" / "files").mkdir(parents=True, exist_ok=True)
    known_hosts = DOCKER_RUNTIME_DIR / "known_hosts"
    (DOCKER_PROJECT_DIR / ".env").write_text(
        "\n".join(
            [
                "SSH_HOST=127.0.0.1",
                f"SSH_PORT={ssh_port}",
                "SSH_USER=root",
                f"SSH_KEY_PATH={key_path}",
                f"SSH_EXTRA_OPTS=-o UserKnownHostsFile={known_hosts} -o IdentitiesOnly=yes",
                "WP_PATH=/var/www/html",
                "WP_CLI_BIN=wp",
                "WP_ALLOW_ROOT=1",
                "WP_REMOTE_TMP_DIR=/tmp/wp-media-sync",
                "",
            ]
        ),
        encoding="utf-8",
    )


def ensure_docker_available() -> None:
    if not shutil.which("docker"):
        raise TestFailure("未找到 docker 命令，无法运行 --docker-live 测试")
    run_command("docker-version", ["docker", "--version"])
    run_command("docker-compose-version", ["docker", "compose", "version"])


def install_docker_wordpress(compose_env: dict[str, str], http_port: int) -> None:
    site_url = f"http://127.0.0.1:{http_port}"
    install_script = f"""
set -euo pipefail
cd /var/www/html
for i in $(seq 1 90); do
  if wp core version --allow-root >/dev/null 2>&1 && wp db check --allow-root >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
wp core version --allow-root >/dev/null
wp config set DB_NAME wordpress --allow-root >/dev/null
wp config set DB_USER wordpress --allow-root >/dev/null
wp config set DB_PASSWORD wordpress --allow-root >/dev/null
wp config set DB_HOST db:3306 --allow-root >/dev/null
wp db check --allow-root >/dev/null
if ! wp core is-installed --allow-root >/dev/null 2>&1; then
  wp core install --allow-root \\
    --url={sh_quote(site_url)} \\
    --title='wp-media-sync docker test' \\
    --admin_user=admin \\
    --admin_password='admin-password-123' \\
    --admin_email=admin@example.test \\
    --skip-email
fi
wp option update siteurl {sh_quote(site_url)} --allow-root >/dev/null
wp option update home {sh_quote(site_url)} --allow-root >/dev/null
wp option get siteurl --allow-root
"""
    run_command(
        "docker-wordpress-install",
        docker_compose_args(["exec", "-T", "wordpress", "bash", "-lc", install_script]),
        env=compose_env,
    )


def sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def assert_offline_json(output_path: Path) -> None:
    data = json.loads(output_path.read_text(encoding="utf-8"))
    if data["cover"]["url"] != FAKE_REMOTE_URL:
        raise TestFailure("JSON cover.url 没有被回写为远端媒体 URL")
    if data["cover"]["id"] != FAKE_ATTACHMENT_ID:
        raise TestFailure("JSON cover.id 没有被回写为附件 ID")
    if data["gallery"][0]["src"] != FAKE_REMOTE_URL:
        raise TestFailure("JSON gallery.src 没有被回写为远端媒体 URL")
    if data["gallery"][0]["attachment_id"] != FAKE_ATTACHMENT_ID:
        raise TestFailure("JSON gallery.attachment_id 没有被回写为附件 ID")
    if "youtube.com" not in data["external_video"]:
        raise TestFailure("外链视频不应被改写")


def assert_offline_html(output_path: Path, base_url: str) -> None:
    html = output_path.read_text(encoding="utf-8")
    if f'<img src="{FAKE_REMOTE_URL}"' not in html:
        raise TestFailure("HTML img src 没有被回写")
    if f'<iframe src="{base_url}/{TEST_IMAGE_NAME}"></iframe>' not in html:
        raise TestFailure("HTML iframe 内 URL 不应被改写")
    if "youtube.com" not in html:
        raise TestFailure("HTML 外链视频不应被改写")


def run_offline_tests(base_url: str, json_input: Path, html_input: Path) -> None:
    prepare_offline_project(base_url)
    fake_env = prepare_fake_cli_tools()
    json_output = OUTPUT_DIR / "offline-output.json"
    html_output = OUTPUT_DIR / "offline-output.html"

    run_command(
        "offline-json",
        [
            sys.executable,
            "scripts/wp-media-sync.py",
            "--project-root",
            str(OFFLINE_PROJECT_DIR),
            "--input",
            str(json_input),
            "--output",
            str(json_output),
            "--report",
            str(OUTPUT_DIR / "offline-json-report.json"),
        ],
        env=fake_env,
    )
    run_command(
        "offline-html",
        [
            sys.executable,
            "scripts/wp-media-sync.py",
            "--project-root",
            str(OFFLINE_PROJECT_DIR),
            "--input",
            str(html_input),
            "--output",
            str(html_output),
        ],
        env=fake_env,
    )
    assert_offline_json(json_output)
    assert_offline_html(html_output, base_url)


def assert_live_json(output_path: Path, base_url: str) -> None:
    data = json.loads(output_path.read_text(encoding="utf-8"))
    source_url = f"{base_url}/{TEST_IMAGE_NAME}"
    if data["cover"]["url"] == source_url:
        raise TestFailure("live JSON cover.url 仍是源 URL，说明未成功回写")
    if not isinstance(data["cover"]["id"], int) or data["cover"]["id"] <= 0:
        raise TestFailure("live JSON cover.id 不是有效附件 ID")
    if data["gallery"][0]["src"] != data["cover"]["url"]:
        raise TestFailure("live JSON 相同源 URL 没有复用同一个远端 URL")
    if data["gallery"][0]["attachment_id"] != data["cover"]["id"]:
        raise TestFailure("live JSON 相同源 URL 没有复用同一个附件 ID")


def run_live_tests(base_url: str, json_input: Path) -> None:
    check = run_command(
        "live-check-wp-cli",
        ["bash", "scripts/check-wp-cli.sh", "--project-root", str(PROJECT_ROOT)],
        check=False,
    )
    if check.returncode != 0:
        raise TestFailure(
            "live 前置检查失败，通常是远端 WP-CLI 不可用或 .env 配置不完整。\n"
            f"STDOUT:\n{check.stdout}\nSTDERR:\n{check.stderr}"
        )

    live_output = OUTPUT_DIR / "live-output.json"
    run_command(
        "live-json",
        [
            sys.executable,
            "scripts/wp-media-sync.py",
            "--project-root",
            str(PROJECT_ROOT),
            "--input",
            str(json_input),
            "--output",
            str(live_output),
            "--report",
            str(OUTPUT_DIR / "live-json-report.json"),
        ],
    )
    assert_live_json(live_output, base_url)


def run_docker_live_tests(base_url: str, json_input: Path, *, keep_docker: bool) -> None:
    ensure_docker_available()
    ssh_port = find_free_port()
    http_port = find_free_port()
    key_path = generate_docker_ssh_key()
    prepare_docker_project(ssh_port, key_path)
    compose_env = docker_env(ssh_port, http_port)

    run_command(
        "docker-compose-down-before",
        docker_compose_args(["down", "-v", "--remove-orphans"]),
        check=False,
        env=compose_env,
    )
    try:
        run_command(
            "docker-compose-up",
            docker_compose_args(["up", "-d", "--build"]),
            env=compose_env,
        )
        install_docker_wordpress(compose_env, http_port)
        run_command(
            "docker-check-wp-cli",
            ["bash", "scripts/check-wp-cli.sh", "--project-root", str(DOCKER_PROJECT_DIR)],
        )

        docker_output = OUTPUT_DIR / "docker-live-output.json"
        run_command(
            "docker-live-json",
            [
                sys.executable,
                "scripts/wp-media-sync.py",
                "--project-root",
                str(DOCKER_PROJECT_DIR),
                "--input",
                str(json_input),
                "--output",
                str(docker_output),
                "--report",
                str(OUTPUT_DIR / "docker-live-report.json"),
            ],
        )
        assert_live_json(docker_output, base_url)

        log_path = DOCKER_PROJECT_DIR / "media" / "log.json"
        log_data = json.loads(log_path.read_text(encoding="utf-8"))
        if not log_data.get("uploads"):
            raise TestFailure("docker-live 没有写入 media/log.json 上传记录")
    finally:
        if not keep_docker:
            run_command(
                "docker-compose-down-after",
                docker_compose_args(["down", "-v", "--remove-orphans"]),
                check=False,
                env=compose_env,
            )


def main() -> int:
    args = parse_args()
    reset_runtime(args.keep_runtime)
    write_test_image()

    server = None
    try:
        server, base_url = start_http_server(args.port)
        json_input, html_input = render_templates(base_url)
        run_offline_tests(base_url, json_input, html_input)
        print("离线夹具测试通过：JSON/HTML 回写、iframe 跳过、外链视频跳过、log 去重均正常。")

        if args.live:
            run_live_tests(base_url, json_input)
            print("live 上传测试通过：SSH/WP-CLI 上传和回写正常。")
        if args.docker_live:
            run_docker_live_tests(base_url, json_input, keep_docker=args.keep_docker)
            print("docker-live 上传测试通过：隔离 WordPress 容器中的 SSH/WP-CLI 上传和回写正常。")
        if not args.live and not args.docker_live:
            print("未运行 live 上传测试；需要真实站点上传时执行：python3 tests/run-media-sync-tests.py --live")
            print("需要隔离 Docker 真实上传时执行：python3 tests/run-media-sync-tests.py --docker-live")
        else:
            print("测试输出位于 tests/runtime/output/。")
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TestFailure as exc:
        print(f"测试失败: {exc}", file=sys.stderr)
        raise SystemExit(1)
