---
name: wp-media-sync
description: WordPress media synchronization through SSH and WP-CLI only. Use when Codex, Claude Code, OpenCode, or another AI tool must process HTML, JSON, Gutenberg data, Elementor JSON, or mixed text, download remote media into media/files, upload those files to a target WordPress site with wp media import, maintain media/log.json to prevent duplicate uploads, and rewrite the original data with returned attachment IDs and URLs. Never use the WordPress REST API for media upload.
---

# WordPress Media Sync

## 核心原则

把输入数据里的远程媒体同步到指定 WordPress 站点，并返回已回写的新数据。必须遵守这些边界：

- 只允许通过 SSH 调用远端 `WP-CLI` 上传媒体；不要使用 WordPress REST API、后台表单、XML-RPC 或浏览器自动化上传。
- 只从目标项目根目录的 `.env` 读取连接配置；目标项目根目录由 `--project-root` 指定，不等同于 Skill 安装目录。
- 下载和手动补充的文件只能放在目标项目的 `media/files/`，上传记录只能写入目标项目的 `media/log.json`。
- 上传前先查 `media/log.json`，命中已成功上传的 URL 或文件哈希时直接复用附件 ID 和远端 URL。
- `WP-CLI` 上传失败时立即报错终止，不要静默降级到其他上传方式。
- 输出和说明优先使用中文，保留 WordPress、WP-CLI、Elementor、Gutenberg 等专用名词。

## 推荐流程

1. 确认目标项目根目录存在 `.env`，至少包含 `SSH_HOST`、`SSH_PORT`、`SSH_USER`、`WP_PATH`。
2. 如果是第一次连接该站点，先运行：

```bash
bash scripts/check-wp-cli.sh --project-root /path/to/project
```

3. 把待处理 HTML、JSON 或文本保存为文件，然后运行。无论 Skill 安装在哪里，都要把 `--project-root` 指向被处理的目标项目：

```bash
python3 scripts/wp-media-sync.py --project-root /path/to/project --input input.json --output output.json
```

4. 将 `output.*` 交给后续发布 Skill，或把标准输出返回给用户。

## 项目账本约定

不要把 Skill 安装目录当成媒体账本目录。`scripts/wp-media-sync.py` 会以 `--project-root` 为唯一项目边界：

- 读取 `<project-root>/.env`。
- 创建或读取 `<project-root>/media/log.json`。
- 下载媒体到 `<project-root>/media/files/`。
- 在报告中输出实际使用的 `log_path`，用于核对是否写到了目标项目。

## 脚本资源

- `scripts/wp-media-sync.py`：主流程脚本。负责抽取 URL、跳过不应处理的媒体、下载到 `media/files/`、WP-CLI 上传、更新 `media/log.json`、回写 HTML/JSON/文本。
- `scripts/check-wp-cli.sh`：连接检查脚本。只验证 SSH 和远端 WP-CLI 是否可用，不上传媒体。
需要配置、跳过规则、SVG 规则或输出约定时，读取 `references/media-sync-rules.md`。

## 输入处理规则

- HTML：替换非 `<iframe>` 区域中的媒体 URL；`<iframe>` 中的 URL 保持原样。
- JSON：递归替换字符串里的媒体 URL；当同一对象中存在 `id`、`media_id`、`attachment_id`、`image_id` 等字段时，用新附件 ID 回写。
- 常见外链视频平台如 YouTube、Vimeo、Bilibili、Dailymotion 保持原样。
- 直接视频文件超过 20 MB 时保持原样并给出提示；无法确认大小的大型视频倾向于跳过。
- SVG 文件必须通过本地安全校验；需要打开 SVG 上传时，只允许通过 SSH 在当前主题 `functions.php` 追加带标记的允许上传代码。

## 协作方式

- 在 Codex 中：让 Codex 使用 `$wp-media-sync`，并提供输入文件或待处理数据文件路径。
- 在 Claude Code 中：让 Claude 读取本目录的 `SKILL.md` 和 `AGENT.md`，然后调用 `scripts/wp-media-sync.py`。
- 在 OpenCode 中：把本目录作为自定义 skill/workflow 上下文，按 `README.md` 的命令调用脚本。
