# claude-env

[中文](README.md) | English

`claude-env` is a small Claude Code provider profile manager. It stores `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, and an optional default model for each Claude-compatible provider, then runs Claude Code through `claude --settings` to inject provider credentials at runtime via `claude-env run <name>` or shortcut commands such as `claude-<name>`.

Shortcuts do not contain URLs or tokens. Sensitive values live in the local config file, and `list` redacts tokens.

## Features

- Manage multiple Claude Code provider profiles.
- Configure an optional default model per provider.
- Set `CLAUDE_CODE_AUTO_COMPACT_WINDOW` (the auto-compact window) for providers with a small context window.
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

If `--url` or `--token` is omitted, the command prompts interactively. Token input is hidden. If `--model` is omitted, the command also asks for an optional default model; press Enter to leave it unset and use the provider's own default model selection at runtime. The default model is stored in the `model` field of `env/settings.<name>.json`.

If the provider's real context window is smaller than what Claude Code assumes (for example a small-context model served locally through llama.cpp), add `--auto-compact-window` to set `CLAUDE_CODE_AUTO_COMPACT_WINDOW` so auto-compact triggers early enough to stay under the provider's context limit:

```bash
claude-env add glm \
  --url "https://provider.example/api/anthropic" \
  --token "your-token" \
  --auto-compact-window 118784
```

Set this to the provider's hard max context size as-is; there is no need to reserve room for the compact summary: Claude Code keeps its own autocompact buffer (about 33k tokens in practice, a fixed amount independent of the window size) and compacts before the limit is reached. Note this setting takes precedence over the in-session `/autocompact` command; to change it, re-run `claude-env add`.

List profiles:

```bash
claude-env list
```

Run a provider:

```bash
claude-env run glm -p "Reply with exactly: OK"
```

The command passes provider credentials via `claude --settings`, which overrides any conflicting values in `~/.claude/settings.json`.

If the `claude` executable is missing (not installed or a broken symlink), `run` prints a clear error with install instructions instead of a Python traceback.

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

`env/settings.<name>.json` stores the URL, token, default model, and the optional `CLAUDE_CODE_AUTO_COMPACT_WINDOW`; `claude-env` tries to keep it readable and writable only by the current user where practical. `providers.json` only keeps metadata such as shortcut paths. Shortcut commands do not contain URLs or tokens. Configs from older versions are migrated automatically on install/upgrade.

## Test

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -v
```

The test suite includes a mock Anthropic-compatible provider, so `run` behavior can be verified without spending tokens or depending on real provider uptime.
