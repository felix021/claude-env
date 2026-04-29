# claude-env

[中文](README.md) | English

`claude-env` is a small Claude Code provider profile manager. It stores `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, and an optional default model for each Claude-compatible provider, then runs Claude Code through `claude --settings` to inject provider credentials at runtime via `claude-env run <name>` or shortcut commands such as `claude-<name>`.

Shortcuts do not contain URLs or tokens. Sensitive values live in the local config file, and `list` redacts tokens.

## Features

- Manage multiple Claude Code provider profiles.
- Configure an optional default model per provider.
- Run Claude Code through `claude-env run <name> ...`.
- Create token-free shortcuts such as `claude-glm` and `claude-qwen`.
- Let runtime `--model` override the configured default model.
- Support Linux/macOS through `install.sh`.
- Support Windows through `install.ps1` and `.cmd` shortcuts.
- Use only the Python 3 standard library at runtime.

## Install

Linux/macOS:

```bash
curl -fsSL https://raw.githubusercontent.com/felix021/claude-env/main/install.sh | bash
```

Windows PowerShell:

```powershell
iwr https://raw.githubusercontent.com/felix021/claude-env/main/install.ps1 | iex
```

The Windows installer checks `py -3` and then `python`. If Python 3 is missing, it prints a `winget install Python.Python.3.12` instruction; it does not silently install Python for normal users.

After installation, make sure `~/.local/bin` is in `PATH`. On Windows, the installer prepends `%USERPROFILE%\.local\bin` to the user `PATH` so older shortcut commands with the same name do not win command resolution.

## Install For AI Agents

For automated agents, remote development hosts, or disposable test environments, use these non-interactive commands.

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

Agents should not write real tokens to logs, issues, pull requests, gists, or commit messages. Prefer reading provider secrets from environment variables or a secret manager.

Example:

```bash
claude-env add glm \
  --url "$PROVIDER_BASE_URL" \
  --token "$PROVIDER_TOKEN" \
  --model "glm-5-turbo" \
  -y
```

## Usage

Add a provider:

```bash
claude-env add glm \
  --url "https://provider.example/api/anthropic" \
  --token "your-token" \
  --model "glm-5-turbo"
```

If `--url` or `--token` is omitted, the command prompts interactively. Token input is hidden. If `--model` is omitted, the command also asks for an optional default model; press Enter to leave it unset and use the provider's own default model selection at runtime.

List profiles:

```bash
claude-env list
```

Run a provider:

```bash
claude-env run glm -p "Reply with exactly: OK"
```

The command passes provider credentials via `claude --settings`, which overrides any conflicting values in `~/.claude/settings.json`.

Use the shortcut:

```bash
claude-glm -p "Reply with exactly: OK"
```

Override the default model at runtime:

```bash
claude-glm --model glm-5.1 -p "Reply with exactly: OK"
```

Remove a provider:

```bash
claude-env remove glm
```

Aliases:

```bash
claude-env rm glm
claude-env delete glm
claude-env del glm
```

## File Locations

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

`providers.json` contains tokens. `claude-env` tries to keep it readable and writable only by the current user where practical. Shortcut commands do not contain URLs or tokens.

## Test

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -v
```

The test suite includes a mock Anthropic-compatible provider, so `run` behavior can be verified without spending tokens or depending on real provider uptime.
