# claude-env Design Spec

Date: 2026-04-27

## Purpose

`claude-env` is a token-conscious provider profile manager for Claude Code. It stores provider configuration, exposes `claude-env run <name>`, and creates small provider-specific shortcuts such as `claude-glm` that dispatch to `run` without containing credentials.

The project optimizes for a simple installation path, predictable behavior, and safe handling of authentication tokens.

## Requirements

- Provide a CLI named `claude-env`.
- Install the CLI to `~/.local/bin/claude-env`.
- Create token-free provider shortcuts under `~/.local/bin/claude-<name>`.
- Support provider-specific `ANTHROPIC_BASE_URL` and `ANTHROPIC_AUTH_TOKEN`.
- Support an optional default model per wrapper.
- Allow runtime `--model` arguments to override the configured default model.
- Prompt before overwriting existing wrappers unless `-y` is provided.
- Prompt interactively for missing URL or token values.
- Support removing existing managed wrappers with confirmation unless `-y` is provided.
- Support listing managed wrappers without exposing tokens.
- Support `claude-env run <name> [claude arguments...]`.
- Support Windows `.cmd` shortcuts and a PowerShell installer.
- Keep the MVP dependency-free beyond Python 3 and the standard library.

## Command Design

### `add`

```bash
claude-env add <name> --url <url> --token <token> [--model <model>] [-y]
```

Stores provider metadata and creates a managed shortcut named:

```text
~/.local/bin/claude-<name>
```

If `--url` or `--token` is omitted, the command asks for the missing value interactively. Token input must be hidden.

If a target wrapper already exists, the command prompts before overwriting. With `-y`, the command overwrites without prompting.

The shortcut must not include the base URL or token.

### `run`

```bash
claude-env run <name> [claude arguments...]
```

Reads provider metadata, sets `ANTHROPIC_BASE_URL` and `ANTHROPIC_AUTH_TOKEN` for the child process, injects the provider default model only when the caller did not pass `--model`, and executes `claude`.

Shortcut commands are equivalent:

```bash
claude-glm -p "hello"
claude-env run glm -p "hello"
```

### `remove`

```bash
claude-env remove <name> [-y]
```

Aliases:

```bash
claude-env rm <name>
claude-env delete <name>
claude-env del <name>
```

Removes the managed wrapper and updates provider metadata. The command refuses to delete files that are not known to be managed by `claude-env`.

### `list`

```bash
claude-env list
```

Lists configured providers, wrapper paths, base URLs, and default models. Tokens are always redacted.

### Future Commands

```bash
claude-env show <name>
claude-env update <name> [--url <url>] [--token <token>] [--model <model>|--no-model]
```

The MVP does not need these commands, but the metadata format should support them later.

## Installation Design

The simplest install experience is:

```bash
curl -fsSL https://raw.githubusercontent.com/felix021/claude-env/main/install.sh | bash
```

The POSIX installer downloads the project archive, installs the Python package under `~/.local/share/claude-env/`, writes a launcher to `~/.local/bin/claude-env`, marks it executable, and checks whether `~/.local/bin` is in `PATH`.

If `~/.local/bin` is missing from `PATH`, the installer prints shell-specific instructions instead of editing shell configuration silently.

The Windows installer is `install.ps1`. It checks `py -3` and then `python` for Python 3. If Python is missing, it prints a clear install instruction instead of silently installing Python for normal users.

The first implementation should use Python standard library only. This avoids a virtual environment, `pip`, `pipx`, or packaging requirement on a new machine.

## Storage Design

Shortcuts live in:

```text
~/.local/bin/
```

Managed provider metadata lives in:

```text
~/.config/claude-env/providers.json
```

The metadata file records provider name, wrapper path, base URL, token, optional default model, and management marker/version. Normal CLI output must redact the token.

Keeping metadata separate from generated shell scripts makes `list`, `remove`, and future `update` commands reliable.

## Run And Shortcut Design

`claude-env run`:

1. Sets `ANTHROPIC_BASE_URL`.
2. Sets `ANTHROPIC_AUTH_TOKEN`.
3. Detects whether the user supplied `--model`.
4. Calls `claude` with the configured default model only when no runtime model was supplied.
5. Forwards all original user arguments.

Generated shortcuts do not contain provider base URLs or tokens. POSIX shortcuts should prefer symlinks to `claude-env` and fall back to a tiny launcher. Windows shortcuts should be `.cmd` files that call `claude-env run <name> %*`.

## Error Handling

- Invalid provider names should fail before writing files.
- Existing files should not be overwritten without confirmation or `-y`.
- Unmanaged files should not be removed by default.
- Missing interactive input should fail with a clear error.
- Metadata write failures should not leave a misleading successful wrapper state.
- Wrapper write failures should not update metadata as though the wrapper exists.

## Security And Privacy

- Tokens must never be printed by `list`, `show`, normal errors, installer output, or tests.
- Documentation examples must use placeholders.
- Provider metadata contains tokens and must be owner-readable only where practical.
- Shortcuts must not contain tokens or base URLs.
- Publishing workflows must avoid real hostnames, credentials, IPs, and provider secrets.

## Testing Strategy

Follow TDD: write failing tests first, then implement behavior, then verify.

Core tests should use temporary directories for home, config, and bin paths.

Required coverage:

- Adding a provider creates a wrapper and metadata.
- Adding a provider creates a token-free shortcut.
- Running a provider sets environment variables from metadata.
- Running a provider works against a mock Anthropic-compatible provider.
- Adding a provider with a default model generates correct fallback behavior.
- Passing runtime `--model` overrides the configured default.
- Missing URL or token triggers interactive input.
- Token input is not echoed.
- Existing wrapper overwrite prompts by default.
- `-y` suppresses overwrite prompts.
- Removing a managed wrapper deletes the file and metadata entry.
- Removing an unmanaged wrapper is refused.
- Listing providers redacts tokens.
- Installer writes to `~/.local/bin/claude-env` and reports missing `PATH`.

## Implementation Shape

Recommended structure:

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

A single-file executable is acceptable for the first version if tests remain readable. The project should split into modules once wrapper generation, metadata storage, and command parsing start to obscure each other.

## Open Decisions

- Whether `update` ships in the MVP or waits for a second iteration.
- Whether metadata should store tokens directly or only record management state while wrappers store executable credentials.
- Whether the installer should support release artifacts in addition to downloading the main branch script.

The recommended MVP is to ship `add`, `remove`, and `list`; use a dependency-free Python package; include metadata under `~/.config/claude-env/providers.json`; and install through `install.sh`.
