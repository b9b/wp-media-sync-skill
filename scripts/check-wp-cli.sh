#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(pwd)"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-root)
      PROJECT_ROOT="$2"
      shift 2
      ;;
    -h|--help)
      cat <<'HELP'
Usage:
  bash scripts/check-wp-cli.sh [--project-root /path/to/project]

Checks SSH connectivity and remote WP-CLI availability using only /path/to/project/.env.
HELP
      exit 0
      ;;
    *)
      echo "未知参数: $1" >&2
      exit 2
      ;;
  esac
done

ENV_FILE="$PROJECT_ROOT/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "未找到 .env: $ENV_FILE" >&2
  exit 1
fi

trim() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

while IFS= read -r raw_line || [[ -n "$raw_line" ]]; do
  line="$(trim "$raw_line")"
  [[ -z "$line" || "$line" == \#* ]] && continue
  [[ "$line" == export\ * ]] && line="$(trim "${line#export }")"
  [[ "$line" != *=* ]] && continue
  key="$(trim "${line%%=*}")"
  value="$(trim "${line#*=}")"
  if [[ "$value" == \"*\" && "$value" == *\" ]]; then
    value="${value:1:${#value}-2}"
  elif [[ "$value" == \'*\' && "$value" == *\' ]]; then
    value="${value:1:${#value}-2}"
  fi
  case "$key" in
    SSH_HOST|SSH_PORT|SSH_USER|WP_PATH|SSH_KEY_PATH|SSH_EXTRA_OPTS|WP_CLI_BIN|WP_ALLOW_ROOT)
      printf -v "$key" '%s' "$value"
      ;;
  esac
done < "$ENV_FILE"

: "${SSH_HOST:?缺少 SSH_HOST}"
: "${SSH_PORT:?缺少 SSH_PORT}"
: "${SSH_USER:?缺少 SSH_USER}"
: "${WP_PATH:?缺少 WP_PATH}"

WP_CLI_BIN="${WP_CLI_BIN:-wp}"
WP_ALLOW_ROOT="${WP_ALLOW_ROOT:-0}"

ssh_args=(-p "$SSH_PORT" -o BatchMode=yes -o StrictHostKeyChecking=accept-new)
if [[ -n "${SSH_KEY_PATH:-}" ]]; then
  ssh_args+=(-i "$SSH_KEY_PATH")
fi
if [[ -n "${SSH_EXTRA_OPTS:-}" ]]; then
  # shellcheck disable=SC2206
  extra_opts=($SSH_EXTRA_OPTS)
  ssh_args+=("${extra_opts[@]}")
fi

wp_path_q="$(printf '%q' "$WP_PATH")"
wp_bin_q="$(printf '%q' "$WP_CLI_BIN")"
allow_root=""
if [[ "$WP_ALLOW_ROOT" == "1" || "$WP_ALLOW_ROOT" == "true" ]]; then
  allow_root=" --allow-root"
fi

remote_cmd="cd $wp_path_q && $wp_bin_q --info$allow_root && $wp_bin_q option get siteurl$allow_root"

echo "检查 SSH: $SSH_USER@$SSH_HOST:$SSH_PORT"
if ! ssh "${ssh_args[@]}" "$SSH_USER@$SSH_HOST" "$remote_cmd"; then
  echo "远端 WP-CLI 不存在或无法执行，已终止。请安装 WP-CLI，或在 .env 中把 WP_CLI_BIN 配置为可执行路径。本 Skill 不会尝试 REST API 或其他上传方式。" >&2
  exit 1
fi
echo "WP-CLI 可用。"
