# wp-media-sync

`wp-media-sync` 是一个用于 WordPress 媒体同步的 AI Skill。它可以处理 HTML、JSON、Gutenberg 数据、Elementor JSON 或普通文本中的远程媒体链接，通过 SSH 调用远端 `WP-CLI` 上传到 WordPress 媒体库，并把原数据中的 URL 和常见附件 ID 字段回写为上传后的结果。

这个 Skill 只使用 `WP-CLI` 上传媒体，不使用 WordPress REST API、后台表单、XML-RPC 或浏览器自动化。

## 下载

推荐从 GitHub Releases 下载干净发布包。请下载 Release assets 里的 `wp-media-sync.zip` 或 `wp-media-sync.tar.gz`，不要使用 GitHub 自动生成的 `Source code` 包。

发布包解压后应得到这个结构：

```text
wp-media-sync/
├── SKILL.md
├── .env.example
├── agents/openai.yaml
├── references/media-sync-rules.md
└── scripts/
    ├── check-wp-cli.sh
    └── wp-media-sync.py
```

## 一键安装

推荐使用 Release 里的 `install.sh` 一键安装。安装脚本会先判断目标目录是否存在，不存在再创建；如果已安装旧版本，默认会先备份旧目录再安装新版本。

```bash
curl -fsSL https://github.com/b9b/wp-media-sync-skill/releases/latest/download/install.sh | sh -s -- --tool codex --scope user
```

参数说明：

- `--tool codex|claude-code|opencode|all`：选择安装到哪个 AI 工具，默认 `codex`。
- `--scope user|project`：选择用户级还是项目级安装，默认 `user`。
- `--project /path/to/project`：项目级安装目标；未填写时使用当前目录。
- `--version v0.1.0`：安装指定 Release 版本；默认安装 latest。
- `--url URL`：从自定义 `wp-media-sync.zip` 地址安装。
- `--archive /path/to/wp-media-sync.zip`：从本地 zip 安装。
- `--install-dir /path/to/skills`：安装到自定义 skills 父目录，仅适合单个 `--tool`。
- `--no-backup`：不备份旧版本，直接替换。
- `--dry-run`：只打印将执行的安装动作，不写入文件。

如果你不喜欢 `curl | sh`，可以先下载再执行：

```bash
curl -fsSLO https://github.com/b9b/wp-media-sync-skill/releases/latest/download/install.sh
sh install.sh --tool codex --scope user
```

## Codex 安装

Codex 当前支持用户级 Skill 和项目级 Skill。用户级 Skill 对所有项目可用；项目级 Skill 只对当前仓库或工作目录可用。

### Codex 用户级安装

```bash
curl -fsSL https://github.com/b9b/wp-media-sync-skill/releases/latest/download/install.sh | sh -s -- --tool codex --scope user
```

安装后，在 Codex CLI、IDE extension 或 Codex app 中可以显式提到 `$wp-media-sync`，也可以让 Codex 根据任务自动选择它。

### Codex 项目级安装

先进入目标项目根目录，再执行项目级安装：

```bash
cd /path/to/target-project
curl -fsSL https://github.com/b9b/wp-media-sync-skill/releases/latest/download/install.sh | sh -s -- --tool codex --scope project
```

项目级安装适合团队共享。把 `.agents/skills/wp-media-sync/` 提交到目标项目后，团队成员在该项目中启动 Codex 即可使用。

## Claude Code 安装

Claude Code 支持个人 Skill 和项目 Skill。个人 Skill 位于 `~/.claude/skills/<skill-name>/SKILL.md`，项目 Skill 位于 `.claude/skills/<skill-name>/SKILL.md`。

### Claude Code 用户级安装

```bash
curl -fsSL https://github.com/b9b/wp-media-sync-skill/releases/latest/download/install.sh | sh -s -- --tool claude-code --scope user
```

使用时可以让 Claude Code 自动触发，也可以显式输入：

```text
/wp-media-sync
```

如果 Claude Code 会话已经启动，新增顶层 skills 目录后可能需要重启 Claude Code；已存在目录下的 `SKILL.md` 变更通常会被自动检测。

### Claude Code 项目级安装

```bash
cd /path/to/target-project
curl -fsSL https://github.com/b9b/wp-media-sync-skill/releases/latest/download/install.sh | sh -s -- --tool claude-code --scope project
```

项目级安装适合把这个 Skill 固定到某个 WordPress 内容项目中。

## OpenCode 安装

OpenCode 原生 Skill 位置是 `.opencode/skills/<name>/SKILL.md` 和 `~/.config/opencode/skills/<name>/SKILL.md`。它也会读取 `.claude/skills` 和 `.agents/skills` 兼容目录。

### OpenCode 用户级安装

```bash
curl -fsSL https://github.com/b9b/wp-media-sync-skill/releases/latest/download/install.sh | sh -s -- --tool opencode --scope user
```

### OpenCode 项目级安装

```bash
cd /path/to/target-project
curl -fsSL https://github.com/b9b/wp-media-sync-skill/releases/latest/download/install.sh | sh -s -- --tool opencode --scope project
```

如果你希望同一个项目目录同时被 Codex 和 OpenCode 发现，也可以把 Skill 安装到项目的 `.agents/skills`；OpenCode 会读取该兼容位置。

同时安装到三个工具：

```bash
curl -fsSL https://github.com/b9b/wp-media-sync-skill/releases/latest/download/install.sh | sh -s -- --tool all --scope user
```

项目级同时安装到三个工具：

```bash
cd /path/to/target-project
curl -fsSL https://github.com/b9b/wp-media-sync-skill/releases/latest/download/install.sh | sh -s -- --tool all --scope project
```

## 目标项目配置

无论这个 Skill 安装在全局目录还是项目目录中，`.env`、`media/log.json` 和 `media/files/` 都必须属于“被处理的目标项目”，而不是 Skill 安装目录。

在目标项目根目录创建 `.env`：

```bash
cd /path/to/target-project
if [ ! -f .env ]; then
  cp /path/to/wp-media-sync/.env.example .env
fi
```

至少填写：

```bash
SSH_HOST=1.2.3.4
SSH_PORT=22
SSH_USER=site_ssh_user
WP_PATH=/www/wwwroot/example.com
```

要求：

- 本机已配置 SSH 密钥免密登录。
- 远端 WordPress 目录可以执行 `WP-CLI`。
- 如果远端 `wp` 不在默认 `PATH` 中，在 `.env` 里设置 `WP_CLI_BIN=/path/to/wp`。

可选配置：

```bash
SSH_KEY_PATH=/Users/you/.ssh/id_ed25519
SSH_EXTRA_OPTS=-o ProxyJump=jump-host
WP_CLI_BIN=wp
WP_ALLOW_ROOT=0
WP_REMOTE_TMP_DIR=/tmp/wp-media-sync
```

## 命令行使用

先检查远端 WP-CLI：

```bash
bash /path/to/wp-media-sync/scripts/check-wp-cli.sh --project-root /path/to/target-project
```

处理 JSON：

```bash
python3 /path/to/wp-media-sync/scripts/wp-media-sync.py \
  --project-root /path/to/target-project \
  --input /path/to/input.json \
  --output /path/to/output.json \
  --report /path/to/target-project/media/last-report.json
```

处理 HTML：

```bash
python3 /path/to/wp-media-sync/scripts/wp-media-sync.py \
  --project-root /path/to/target-project \
  --input /path/to/input.html \
  --output /path/to/output.html
```

`--project-root` 是去重和凭据边界。脚本会读取：

- `<project-root>/.env`
- `<project-root>/media/log.json`
- `<project-root>/media/files/`

如果 `media/log.json` 不存在，脚本会自动创建。成功上传后，脚本会记录源 URL、文件哈希、附件 ID 和远端 URL，后续遇到相同 URL 或相同文件哈希时会复用已有媒体，避免重复上传。

## AI 工具使用示例

Codex：

```text
使用 $wp-media-sync 处理 /path/to/target-project/input.json，把远程媒体上传到 /path/to/target-project/.env 指向的 WordPress 站点，并输出 /path/to/target-project/output.json。
```

Claude Code：

```text
/wp-media-sync
请同步 /path/to/target-project/input.html 中的远程媒体，项目根目录是 /path/to/target-project，结果保存为 output.html。不要使用 REST API。
```

OpenCode：

```text
使用 wp-media-sync Skill，项目根目录为 /path/to/target-project，处理 input.json 并生成 output.json。
```

## 规则

- 只允许使用 SSH + `WP-CLI` 上传媒体。
- 如果远端 `WP-CLI` 不存在或无法执行，立即报错并终止。
- 所有下载文件必须放在目标项目的 `media/files/`。
- 所有成功上传必须记录到目标项目的 `media/log.json`。
- `<iframe>` 中的媒体 URL 保持原样。
- YouTube、Vimeo、Bilibili、Dailymotion 等外链视频保持原样。
- 直接视频文件超过 20 MB 时保持原样并提示。
- SVG 必须通过安全校验；如需开启 SVG 上传，只允许使用 SSH 在当前主题 `functions.php` 中追加带标记的允许代码。

## 兼容性依据

- Codex：[Agent Skills](https://developers.openai.com/codex/skills) 支持 `.agents/skills` 仓库级 Skill 和 `$HOME/.agents/skills` 用户级 Skill；可通过 `$skill-name` 显式调用。
- Claude Code：[Extend Claude with skills](https://code.claude.com/docs/en/skills) 支持 `~/.claude/skills/<name>/SKILL.md` 和项目 `.claude/skills/<name>/SKILL.md`；可通过 `/skill-name` 显式调用。
- OpenCode：[Agent Skills](https://opencode.ai/docs/skills/) 支持 `.opencode/skills`、`~/.config/opencode/skills`，并兼容 `.claude/skills` 与 `.agents/skills`。
