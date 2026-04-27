# CLAUDE.md

## Project Summary

`claude-env` is a small command-line utility for managing provider-specific Claude Code execution profiles.

The tool stores provider configuration and runs `claude` with provider-specific environment variables and, optionally, a default model. It can also create shortcut commands such as `claude-glm` or `claude-qwen`, but those shortcuts must not contain provider credentials.

The wrapper scripts set:

- `ANTHROPIC_BASE_URL`
- `ANTHROPIC_AUTH_TOKEN`

The canonical execution path is:

```bash
claude-env run <name> [claude arguments...]
```

Shortcut commands call the same execution path:

```bash
claude-glm [claude arguments...]
```

## Goals

- Make it easy to create, list, update, remove, and run Claude Code provider profiles.
- Keep installation simple on a new machine.
- Avoid runtime dependencies for the MVP.
- Avoid exposing authentication tokens in normal command output.
- Make generated wrapper ownership explicit so unmanaged user files are not accidentally removed or overwritten.

## Non-Goals

- This project does not implement a replacement for Claude Code.
- This project does not manage provider accounts or issue tokens.
- This project does not require a daemon, background service, or shell plugin.
- This project does not need a package manager dependency for the first version.

## Installation Model

The preferred MVP installation method is a single installer script:

```bash
curl -fsSL https://raw.githubusercontent.com/felix021/claude-env/main/install.sh | bash
```

The installer should:

1. Download the project archive.
2. Install the Python package under `~/.local/share/claude-env/`.
3. Install a launcher at `~/.local/bin/claude-env`.
4. Mark the launcher executable.
5. Check whether `~/.local/bin` is in `PATH`.
6. Print clear shell-specific instructions if the user needs to update `PATH`.

The MVP should be implemented with the Python standard library only. This keeps installation portable and avoids virtual environment or `pip` setup.

Windows should use a PowerShell installer, `install.ps1`, that checks for Python 3 using `py -3` and then `python`. If Python 3 is missing, it should print a clear `winget install Python.Python.3.12` instruction rather than silently installing Python for normal users.

## Command Interface

### Add a Provider Wrapper

```bash
claude-env add <name> --url <url> --token <token> [--model <model>] [-y]
```

Example:

```bash
claude-env add glm --url "<provider-base-url>" --token "<provider-token>" --model "<model-name>"
```

This stores provider metadata and creates a token-free shortcut:

```text
~/.local/bin/claude-<name>
```

On Windows, this creates:

```text
%USERPROFILE%\.local\bin\claude-<name>.cmd
```

If `--url` or `--token` is omitted, the command should prompt interactively. Token input should not be echoed.

If `--model` is provided, it becomes the provider's default model. Users must still be able to override the model at runtime:

```bash
claude-env run glm --model <another-model>
```

If the wrapper already exists, the CLI should prompt before overwriting it. The `-y` flag suppresses the prompt.

### Run a Provider

```bash
claude-env run <name> [claude arguments...]
```

The command reads provider configuration, sets `ANTHROPIC_BASE_URL` and `ANTHROPIC_AUTH_TOKEN` in the child process environment, injects the configured default model only when the user did not pass `--model`, and executes `claude`.

Shortcut commands such as `claude-glm` are equivalent to:

```bash
claude-env run glm
```

### Remove a Provider Wrapper

```bash
claude-env remove <name> [-y]
```

Aliases:

```bash
claude-env rm <name>
claude-env delete <name>
claude-env del <name>
```

The remove command should delete only shortcuts managed by `claude-env`. If a matching file exists but is not managed by this tool, the CLI should refuse removal unless an explicit future force flag is added.

### List Provider Wrappers

```bash
claude-env list
```

The list command should display managed wrappers and useful metadata, such as provider name, wrapper path, base URL, and default model. Tokens must be redacted.

### Recommended Future Commands

```bash
claude-env show <name>
claude-env update <name> [--url <url>] [--token <token>] [--model <model>|--no-model]
```

These are not required for the first implementation, but the storage format should not make them difficult to add.

## Storage Model

Generated shortcuts live in:

```text
~/.local/bin/
```

Provider metadata should live in:

```text
~/.config/claude-env/providers.json
```

The metadata file should record which shortcuts are managed by `claude-env`. This makes `list`, `remove`, and future `update` behavior reliable without parsing shell scripts.

## Shortcut And Run Behavior

`claude-env run` should:

1. Export `ANTHROPIC_BASE_URL`.
2. Export `ANTHROPIC_AUTH_TOKEN`.
3. Execute `claude`.
4. Include the configured default model only when the user did not pass `--model`.
5. Forward all user arguments unchanged.

Generated shortcuts should contain no base URL or token. On POSIX, prefer a symlink to `claude-env` when possible and fall back to a tiny launcher. On Windows, use a `.cmd` launcher.

## Safety Requirements

- Do not print tokens in `list`, `show`, errors, logs, or test output.
- Do not overwrite existing files without confirmation unless `-y` is provided.
- Distinguish managed shortcuts from unmanaged files.
- Use placeholders in examples and documentation instead of real credentials, hostnames, or provider secrets.

## Testing Requirements

Use test-driven development. Tests should be written before implementation changes.

Recommended test coverage:

- `add` creates the expected token-free shortcut and metadata.
- `run` sets provider environment variables from metadata.
- `run` works against a mock Anthropic-compatible provider.
- `add` prompts before overwriting an existing shortcut.
- `add -y` overwrites a managed shortcut without prompting.
- Missing `--url` and `--token` trigger interactive prompts.
- Token prompts do not echo input.
- A configured default model is used when no runtime `--model` is provided.
- A runtime `--model` overrides the configured default.
- `remove` deletes managed shortcuts and metadata.
- `remove` refuses unmanaged files.
- `list` redacts tokens.
- Installer places `claude-env` under `~/.local/bin` and reports missing `PATH` setup.

## Suggested Implementation Structure

```text
claude-env
install.sh
claude_env/
  __main__.py
  cli.py
  store.py
  wrapper.py
tests/
  test_add.py
  test_remove.py
  test_list.py
  test_wrapper.py
```

For the MVP, it is also acceptable to keep the executable as a single Python script if the tests remain clear and behavior stays small.
