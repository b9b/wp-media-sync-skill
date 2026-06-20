# WordPress 媒体同步规则

## `.env` 配置

脚本只读取目标项目根目录的 `.env`。目标项目根目录由 `scripts/wp-media-sync.py --project-root <path>` 指定；不要把 Skill 安装目录当成项目目录，也不要把凭据放进命令行参数或系统环境变量。

必填：

- `SSH_HOST`：服务器地址。
- `SSH_PORT`：SSH 端口。
- `SSH_USER`：SSH 用户。
- `WP_PATH`：远端 WordPress 根目录，必须能在该目录运行 `wp`。

可选：

- `SSH_KEY_PATH`：私钥路径。不填写时使用本机 SSH 配置中的免密登录。
- `SSH_EXTRA_OPTS`：额外 SSH 参数，例如 `-o ProxyJump=jump-host`。
- `WP_CLI_BIN`：远端 WP-CLI 命令，默认 `wp`。
- `WP_ALLOW_ROOT`：设为 `1` 时追加 `--allow-root`。
- `WP_REMOTE_TMP_DIR`：远端临时目录，默认 `/tmp/wp-media-sync`。

## 本地媒体仓库

- `<project-root>/media/log.json` 是去重账本，记录源 URL、本地缓存路径、SHA-256、附件 ID、远端 URL、上传时间和站点信息。
- `<project-root>/media/files/` 是唯一允许保存下载文件的位置。
- 命中 `source_url` 的成功记录时，不重新下载、不重新上传。
- 下载后命中相同 SHA-256 的成功记录时，复用已有附件并把新的 `source_url` 也写入日志。

## 上传方式

上传只能走以下链路：

1. 本地下载远程媒体到 `media/files/`。
2. 使用 `scp` 把缓存文件复制到远端临时目录。
3. 使用 SSH 在 `WP_PATH` 下执行 `wp media import <remote-file> --porcelain`。
4. 使用 `wp eval 'echo wp_get_attachment_url(<id>);'` 读取最终远端 URL。

如果 WP-CLI 不存在、不可执行，或任何 WP-CLI 命令失败，直接终止并报告错误。不要下载后继续尝试其他上传路径，也不要降级到 REST API、后台表单、XML-RPC 或浏览器自动化。

## 跳过规则

- `<iframe>` 标签中的 URL 保持原样。
- YouTube、Vimeo、Bilibili、Dailymotion、Twitch 等外链视频保持原样。
- 视频扩展名包括 `mp4`、`mov`、`webm`、`avi`、`mkv`、`m4v`、`wmv`、`flv`。超过 20 MB 时跳过并提示。
- 非媒体链接不处理。脚本优先通过扩展名判断；没有扩展名时使用响应 `Content-Type` 判断。

## SVG 规则

SVG 必须先通过本地安全校验。脚本会拒绝包含以下内容的 SVG：

- `script`、`iframe`、`object`、`embed`、`foreignObject`。
- `onload`、`onclick` 等事件属性。
- `javascript:`、外部 HTTP(S) 引用或危险 `data:` 引用。
- `DOCTYPE` 或实体定义。

上传 SVG 前，脚本会通过 WP-CLI 获取当前主题目录，并且只在该主题的 `functions.php` 中追加带 `wp-media-sync svg upload support` 标记的 MIME 允许代码。不要把 SVG 上传开关写入插件、mu-plugin 或其他主题文件。
