# claude-env

中文 | [English](README.en.md)

`claude-env` 是一个轻量级 Claude Code Provider 配置管理工具。它可以为不同的 Claude-compatible Provider 保存 `ANTHROPIC_BASE_URL`、`ANTHROPIC_AUTH_TOKEN` 和默认模型，并通过 `claude-env run <name>` 或 `claude-<name>` 快捷命令启动 Claude Code。

快捷命令本身不保存 URL 或 Token；敏感配置只保存在本地配置文件中，`list` 输出会隐藏 Token。

## 功能

- 管理多个 Claude Code Provider 配置。
- 为每个 Provider 设置可选默认模型。
- 通过 `claude-env run <name> ...` 运行 Claude Code。
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

如果省略 `--url` 或 `--token`，命令会交互式询问；Token 输入不会回显。如果省略 `--model`，命令也会询问默认模型；直接回车表示不设置默认模型，运行时使用 Provider 自己的默认模型选择。

查看配置:

```bash
claude-env list
```

运行 Provider:

```bash
claude-env run glm -p "Reply with exactly: OK"
```

如果 `~/.claude/settings.json` 的 `env` 字段包含 `ANTHROPIC_BASE_URL` 或 `ANTHROPIC_AUTH_TOKEN`，`claude-env run` 会拒绝启动。Claude Code 会读取这些设置并可能覆盖 `claude-env` 设置的 Provider 环境变量，所以请先从 settings.json 中移除这两个键。

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

## 文件位置

Linux/macOS:

```text
~/.local/bin/claude-env
~/.local/bin/claude-<name>
~/.local/share/claude-env/
~/.config/claude-env/providers.json
```

Windows:

```text
%USERPROFILE%\.local\bin\claude-env.cmd
%USERPROFILE%\.local\bin\claude-<name>.cmd
%USERPROFILE%\.local\share\claude-env\
%APPDATA%\claude-env\providers.json
```

`providers.json` 包含 Token，本工具会尽量使用仅当前用户可读写的权限保存它。快捷命令不包含 URL 或 Token。

## 测试

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -v
```

测试包含一个 mock Anthropic-compatible Provider，用于验证 `run` 的环境变量注入、默认模型注入和运行时模型覆盖，不依赖真实 API。
