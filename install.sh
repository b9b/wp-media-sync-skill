#!/bin/sh
set -eu

REPO="b9b/wp-media-sync-skill"
SKILL_NAME="wp-media-sync"
ARCHIVE_NAME="wp-media-sync.zip"
VERSION="latest"
TOOL="codex"
SCOPE="user"
PROJECT_ROOT=""
INSTALL_DIR=""
ARCHIVE_PATH=""
ARCHIVE_URL=""
BACKUP_EXISTING="1"
DRY_RUN="0"

usage() {
  cat <<'HELP'
wp-media-sync Skill installer

Usage:
  sh install.sh [options]

Common examples:
  sh install.sh --tool codex --scope user
  sh install.sh --tool claude-code --scope user
  sh install.sh --tool opencode --scope user
  sh install.sh --tool codex --scope project --project /path/to/project
  sh install.sh --tool all --scope project --project /path/to/project

Options:
  --tool TOOL       codex | claude-code | opencode | all (default: codex)
  --scope SCOPE     user | project (default: user)
  --project PATH    Target project root for --scope project. Defaults to cwd.
  --version TAG     GitHub release tag, for example v0.1.0. Default: latest.
  --url URL         Download a custom wp-media-sync.zip URL.
  --archive PATH    Install from a local wp-media-sync.zip.
  --install-dir DIR Install into this exact parent skills directory.
  --no-backup       Replace an existing skill directory without creating backup.
  --dry-run         Print actions without changing files.
  -h, --help        Show this help.
HELP
}

fail() {
  echo "错误: $*" >&2
  exit 1
}

log() {
  echo "wp-media-sync: $*"
}

need_command() {
  command -v "$1" >/dev/null 2>&1 || fail "缺少命令: $1"
}

absolute_path() {
  case "$1" in
    /*) printf '%s\n' "$1" ;;
    *) printf '%s/%s\n' "$(pwd)" "$1" ;;
  esac
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --tool)
      [ "$#" -ge 2 ] || fail "--tool 需要参数"
      TOOL="$2"
      shift 2
      ;;
    --scope)
      [ "$#" -ge 2 ] || fail "--scope 需要参数"
      SCOPE="$2"
      shift 2
      ;;
    --project)
      [ "$#" -ge 2 ] || fail "--project 需要参数"
      PROJECT_ROOT="$2"
      shift 2
      ;;
    --version)
      [ "$#" -ge 2 ] || fail "--version 需要参数"
      VERSION="$2"
      shift 2
      ;;
    --url)
      [ "$#" -ge 2 ] || fail "--url 需要参数"
      ARCHIVE_URL="$2"
      shift 2
      ;;
    --archive)
      [ "$#" -ge 2 ] || fail "--archive 需要参数"
      ARCHIVE_PATH="$2"
      shift 2
      ;;
    --install-dir)
      [ "$#" -ge 2 ] || fail "--install-dir 需要参数"
      INSTALL_DIR="$2"
      shift 2
      ;;
    --no-backup)
      BACKUP_EXISTING="0"
      shift
      ;;
    --dry-run)
      DRY_RUN="1"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "未知参数: $1"
      ;;
  esac
done

case "$TOOL" in
  codex|claude-code|claude|opencode|all) ;;
  *) fail "--tool 只能是 codex、claude-code、opencode 或 all" ;;
esac

case "$SCOPE" in
  user|project) ;;
  *) fail "--scope 只能是 user 或 project" ;;
esac

if [ -n "$INSTALL_DIR" ] && [ "$TOOL" = "all" ]; then
  fail "--install-dir 只能和单个 --tool 搭配使用"
fi

need_command unzip

if [ -z "$ARCHIVE_PATH" ]; then
  if [ -n "$ARCHIVE_URL" ]; then
    download_url="$ARCHIVE_URL"
  elif [ "$VERSION" = "latest" ]; then
    download_url="https://github.com/$REPO/releases/latest/download/$ARCHIVE_NAME"
  else
    download_url="https://github.com/$REPO/releases/download/$VERSION/$ARCHIVE_NAME"
  fi
  if command -v curl >/dev/null 2>&1; then
    downloader="curl"
  elif command -v wget >/dev/null 2>&1; then
    downloader="wget"
  else
    fail "缺少 curl 或 wget，无法下载发布包"
  fi
fi

if [ "$SCOPE" = "project" ]; then
  if [ -z "$PROJECT_ROOT" ]; then
    PROJECT_ROOT="$(pwd)"
  fi
  [ -d "$PROJECT_ROOT" ] || fail "项目目录不存在: $PROJECT_ROOT"
  PROJECT_ROOT="$(cd "$PROJECT_ROOT" && pwd)"
fi

TMP_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT INT TERM

archive_file="$TMP_DIR/$ARCHIVE_NAME"
if [ -n "$ARCHIVE_PATH" ]; then
  [ -f "$ARCHIVE_PATH" ] || fail "本地发布包不存在: $ARCHIVE_PATH"
  cp "$ARCHIVE_PATH" "$archive_file"
else
  log "下载 $download_url"
  if [ "$DRY_RUN" = "1" ]; then
    log "[dry-run] 跳过下载"
  else
    if [ "$downloader" = "curl" ]; then
      curl -fsSL "$download_url" -o "$archive_file"
    else
      wget -qO "$archive_file" "$download_url"
    fi
  fi
fi

unpack_dir="$TMP_DIR/unpack"
if [ "$DRY_RUN" = "1" ]; then
  mkdir -p "$unpack_dir/$SKILL_NAME"
else
  unzip -q "$archive_file" -d "$unpack_dir"
fi

if [ "$DRY_RUN" != "1" ] && [ ! -f "$unpack_dir/$SKILL_NAME/SKILL.md" ]; then
  fail "发布包结构不正确：未找到 $SKILL_NAME/SKILL.md"
fi

skills_parent_for() {
  tool_name="$1"
  if [ -n "$INSTALL_DIR" ]; then
    absolute_path "$INSTALL_DIR"
    return
  fi

  if [ "$SCOPE" = "user" ]; then
    case "$tool_name" in
      codex) printf '%s\n' "$HOME/.agents/skills" ;;
      claude-code|claude) printf '%s\n' "$HOME/.claude/skills" ;;
      opencode) printf '%s\n' "${XDG_CONFIG_HOME:-$HOME/.config}/opencode/skills" ;;
      *) fail "未知工具: $tool_name" ;;
    esac
  else
    case "$tool_name" in
      codex) printf '%s\n' "$PROJECT_ROOT/.agents/skills" ;;
      claude-code|claude) printf '%s\n' "$PROJECT_ROOT/.claude/skills" ;;
      opencode) printf '%s\n' "$PROJECT_ROOT/.opencode/skills" ;;
      *) fail "未知工具: $tool_name" ;;
    esac
  fi
}

install_one() {
  tool_name="$1"
  skills_parent="$(skills_parent_for "$tool_name")"
  target_dir="$skills_parent/$SKILL_NAME"

  log "安装目标: tool=$tool_name scope=$SCOPE path=$target_dir"
  if [ "$DRY_RUN" = "1" ]; then
    log "[dry-run] 如目录不存在则创建: $skills_parent"
    log "[dry-run] 安装 $SKILL_NAME 到 $target_dir"
    return
  fi

  if [ ! -d "$skills_parent" ]; then
    mkdir -p "$skills_parent"
  fi

  if [ -d "$target_dir" ]; then
    if [ "$BACKUP_EXISTING" = "1" ]; then
      backup_dir="$target_dir.backup.$(date +%Y%m%d%H%M%S)"
      mv "$target_dir" "$backup_dir"
      log "已备份旧版本到 $backup_dir"
    else
      rm -rf "$target_dir"
      log "已删除旧版本 $target_dir"
    fi
  fi

  cp -R "$unpack_dir/$SKILL_NAME" "$target_dir"
  log "安装完成: $target_dir"
}

case "$TOOL" in
  all)
    install_one codex
    install_one claude-code
    install_one opencode
    ;;
  claude)
    install_one claude-code
    ;;
  *)
    install_one "$TOOL"
    ;;
esac

log "完成。若正在运行的 AI 工具没有立即发现该 Skill，请重启对应工具。"
