# claude-env

中文 | [English](README.en.md)

`claude-env` 是一个轻量级 Claude Code Provider 配置管理工具。它可以为不同的 Claude-compatible Provider 保存 `ANTHROPIC_BASE_URL`、`ANTHROPIC_AUTH_TOKEN` 和默认模型，并通过 `claude --settings` 注入 Provider 凭据，运行时通过 `claude-env run <name>` 或 `claude-<name>` 快捷命令启动 Claude Code。

快捷命令本身不保存 URL 或 Token；敏感配置只保存在本地配置文件中，`list` 输出会隐藏 Token。

## 功能

- 管理多个 Claude Code Provider 配置。
- 为每个 Provider 设置可选默认模型。
- 更新已有 Provider 的 URL、Token、默认模型和自动压缩窗口。
- 为小上下文 Provider 设置 `CLAUDE_CODE_AUTO_COMPACT_WINDOW`（自动压缩窗口）。
- 通过 `claude-env run <name> ...` 运行 Claude Code。
- 自动屏蔽第三方 Provider 场景下无用的 stderr 提示。
- 通过 `claude-env upgrade` 一键升级。
- 创建无密钥快捷命令，例如 `claude-glm`、`claude-qwen`。
- 运行时传入的 `--model` 会覆盖默认模型。
- 支持 Linux/macOS 的 `install.sh`。
- 支持 Windows 的 `install.ps1` 和 `.cmd` 快捷命令。
- 无第三方 Python 依赖，只需要 Python 3 标准库。

## 安装

Linux/macOS:

```bash
curl -fsSL https://raw.githubusercontent.com/felix021/claude-env/main/install.sh | bash
```

Windows PowerShell:

```powershell
iwr https://raw.githubusercontent.com/felix021/claude-env/main/install.ps1 | iex
```

Windows 安装脚本会检查 `py -3` 和 `python`。如果没有 Python 3，它会提示使用 `winget install Python.Python.3.12` 安装；脚本不会自动静默安装 Python。

安装后请确认 `~/.local/bin` 已加入 `PATH`。Windows 安装脚本会把 `%USERPROFILE%\.local\bin` 放到用户 `PATH` 的前面，以避免旧的同名快捷命令抢先匹配。

## AI Agent 安装

给自动化 Agent、远程开发环境或一次性测试环境使用时，推荐使用以下非交互命令。

Linux/macOS:

```bash
set -e
curl -fsSL https://raw.githubusercontent.com/felix021/claude-env/main/install.sh | bash
export PATH="$HOME/.local/bin:$PATH"
claude-env --help
```

Windows PowerShell:

```powershell
$ErrorActionPreference = "Stop"
iwr https://raw.githubusercontent.com/felix021/claude-env/main/install.ps1 | iex
$env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
claude-env.cmd --help
```

Agent 不应该把真实 Token 写进日志、Issue、PR、Gist 或提交信息。配置 Provider 时建议从环境变量或密钥管理器读取 Token。

示例:

```bash
claude-env add glm \
  --url "$PROVIDER_BASE_URL" \
  --token "$PROVIDER_TOKEN" \
  --model "glm-5-turbo" \
  -y
```

## 使用

添加 Provider:

```bash
claude-env add glm \
  --url "https://provider.example/api/anthropic" \
  --token "your-token" \
  --model "glm-5-turbo"
```

如果省略 `--url` 或 `--token`，命令会交互式询问；Token 输入不会回显。如果省略 `--model`，命令也会询问默认模型；直接回车表示不设置默认模型，运行时使用 Provider 自己的默认模型选择。默认模型保存在 `env/settings.<name>.json` 的 `model` 字段中。

如果 Provider 的实际上下文窗口比 Claude Code 假设的小（例如本地 llama.cpp 部署的小上下文模型），可以加 `--auto-compact-window` 设置 `CLAUDE_CODE_AUTO_COMPACT_WINDOW`，让自动压缩（auto-compact）提前触发，避免超出 Provider 的上下文上限：

```bash
claude-env add glm \
  --url "https://provider.example/api/anthropic" \
  --token "your-token" \
  --auto-compact-window 118784
```

这个值直接填 Provider 的最大上下文（max ctx）即可，不需要为压缩摘要的输出预留余量：Claude Code 内部会从该窗口预留 autocompact buffer（实测约 33k token，固定值、不随窗口大小变化），并在到达上限之前触发压缩。注意该设置的优先级高于会话内的 `/autocompact` 命令；要调整请运行 `claude-env update <name> --auto-compact-window <tokens>`。

查看配置:

```bash
claude-env list
```

更新已有 Provider（只改传入的字段，未传入的保持原值）：

```bash
claude-env update glm \
  --url "https://new-provider.example/api/anthropic" \
  --token "new-token" \
  --model "glm-5.1" \
  --auto-compact-window 200000
```

清除默认模型或自动压缩窗口：

```bash
claude-env update glm --no-model
claude-env update glm --no-auto-compact-window
```

`update` 不会交互式询问缺失字段，也不会改动快捷命令本身。`env/settings.<name>.json` 以 2 空格缩进、末尾带换行的格式保存，便于直接阅读和复制。

升级 claude-env（下载最新安装脚本并重新安装，已有 Provider 配置不受影响）：

```bash
claude-env upgrade
```

默认从 GitHub `main` 分支安装。默认只允许升级：如果目标版本比当前已安装版本低，`upgrade` 会恢复旧版本并报错退出，不会悄悄降级。确实需要降级时显式指定版本：

```bash
claude-env upgrade --version 0.5.0
```

`CLAUDE_ENV_INSTALLER_URL` 可替换安装脚本地址，`CLAUDE_ENV_URL` 可替换源码归档地址（例如使用镜像）。与 `install.sh` 的用法一致，升级会执行该地址提供的内容。

运行 Provider:

```bash
claude-env run glm -p "Reply with exactly: OK"
```

该命令会通过 `claude --settings` 注入 Provider 的凭据，覆盖 `~/.claude/settings.json` 中可能存在的冲突值。

如果找不到 `claude` 命令（未安装或软链失效），`run` 会直接报错并给出安装提示，而不是抛出 Python traceback。

也可以使用快捷命令:

```bash
claude-glm -p "Reply with exactly: OK"
```

运行时覆盖默认模型:

```bash
claude-glm --model glm-5.1 -p "Reply with exactly: OK"
```

删除 Provider:

```bash
claude-env remove glm
```

可用别名:

```bash
claude-env rm glm
claude-env delete glm
claude-env del glm
```

## stderr 噪音屏蔽

第三方 Provider 场景下，Claude Code 会输出一些与使用无关的提示，`claude-env` 会处理掉：

- `⚠ claude.ai connectors are disabled ...`：启动子进程时设置 `ENABLE_CLAUDEAI_MCP_SERVERS=0`，让 Claude Code 直接跳过 claude.ai connector 加载，告警不再出现。如果你显式导出了该变量，则以你的设置为准。
- `[claude-code:unrecognized_model] ...` 和 `We're changing auto mode to no longer charge for classifier requests ...`：这两条没有官方开关。`run` 在 headless 模式（`-p` / `--print` / `--output-format` / `--input-format`）下按行过滤 stderr，只屏蔽这两类固定内容，其余 stderr 原样输出。交互式 TUI 模式不做过滤。

排障时如果需要看原始 stderr：

```bash
CLAUDE_ENV_NO_STDERR_FILTER=1 claude-glm -p "say ok"
```

## 文件位置

Linux/macOS:

```text
~/.local/bin/claude-env
~/.local/bin/claude-<name>
~/.local/share/claude-env/
~/.config/claude-env/providers.json
~/.config/claude-env/env/settings.<name>.json
```

Windows:

```text
%USERPROFILE%\.local\bin\claude-env.cmd
%USERPROFILE%\.local\bin\claude-<name>.cmd
%USERPROFILE%\.local\share\claude-env\
%APPDATA%\claude-env\providers.json
%APPDATA%\claude-env\env\settings.<name>.json
```

`env/settings.<name>.json` 保存 URL、Token、默认模型和可选的 `CLAUDE_CODE_AUTO_COMPACT_WINDOW`，本工具会尽量使用仅当前用户可读写的权限保存它；`providers.json` 只保存快捷命令路径等元数据。快捷命令不包含 URL 或 Token。旧版本配置会在安装/升级时自动迁移到新格式。

## 测试

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -v
```

测试包含一个 mock Anthropic-compatible Provider，用于验证 `run` 的 `--settings` 注入、默认模型注入和运行时模型覆盖，不依赖真实 API。
