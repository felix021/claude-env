# claude-env Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a dependency-free Python CLI that creates, lists, and removes Claude Code provider wrappers.

**Architecture:** The CLI uses Python standard library modules split by responsibility: argument parsing in `cli.py`, metadata persistence in `store.py`, wrapper script rendering in `wrapper.py`, and executable entrypoints in `__main__.py` plus `claude-env`. Tests run against temporary config/bin directories so user files are untouched.

**Tech Stack:** Python 3 standard library, `unittest` for tests, Bash for generated wrappers and installer.

---

## File Structure

- Create `claude-env`: executable Python entrypoint for direct installation.
- Create `claude_env/__init__.py`: package marker and version.
- Create `claude_env/__main__.py`: `python -m claude_env` entrypoint.
- Create `claude_env/cli.py`: command parsing, prompts, command handlers.
- Create `claude_env/store.py`: JSON metadata load/save and path handling.
- Create `claude_env/wrapper.py`: provider-name validation and shell wrapper rendering.
- Create `install.sh`: dependency-free installer.
- Create `tests/test_cli.py`: add/list/remove behavior.
- Create `tests/test_wrapper.py`: wrapper rendering and model override behavior.
- Create `tests/test_install.py`: installer behavior.

## Tasks

### Task 1: Add Wrapper Rendering Tests

**Files:**
- Create: `tests/test_wrapper.py`
- Create after red: `claude_env/wrapper.py`

- [ ] Write tests proving generated wrappers export URL/token, call `claude`, use default model only when no runtime model exists, and reject invalid provider names.
- [ ] Run `python3 -m unittest tests.test_wrapper` and confirm it fails because `claude_env` does not exist.
- [ ] Implement `validate_provider_name`, `shell_quote`, and `render_wrapper`.
- [ ] Run `python3 -m unittest tests.test_wrapper` and confirm it passes.

### Task 2: Add Store Tests

**Files:**
- Create: `tests/test_store.py`
- Create after red: `claude_env/store.py`

- [ ] Write tests proving metadata can be saved, loaded, listed, removed, and written with owner-only permissions.
- [ ] Run `python3 -m unittest tests.test_store` and confirm it fails because `Store` does not exist.
- [ ] Implement JSON-backed `Store`.
- [ ] Run `python3 -m unittest tests.test_store` and confirm it passes.

### Task 3: Add CLI Tests

**Files:**
- Create: `tests/test_cli.py`
- Create after red: `claude_env/cli.py`, `claude_env/__init__.py`, `claude_env/__main__.py`, `claude-env`

- [ ] Write tests for `add`, interactive missing token, `list` redaction, `remove`, remove aliases, overwrite prompts, and unmanaged-file refusal.
- [ ] Run `python3 -m unittest tests.test_cli` and confirm it fails because CLI functions do not exist.
- [ ] Implement argparse command handling and executable entrypoints.
- [ ] Run `python3 -m unittest tests.test_cli` and confirm it passes.

### Task 4: Add Installer Tests

**Files:**
- Create: `tests/test_install.py`
- Create after red: `install.sh`

- [ ] Write tests proving `install.sh` installs from a local source override to `HOME/.local/bin/claude-env`, makes it executable, and reports when `~/.local/bin` is missing from `PATH`.
- [ ] Run `python3 -m unittest tests.test_install` and confirm it fails because `install.sh` does not exist.
- [ ] Implement installer with `CLAUDE_ENV_SOURCE` override for tests and URL download fallback.
- [ ] Run `python3 -m unittest tests.test_install` and confirm it passes.

### Task 5: Full Verification

**Files:**
- Read all created files.

- [ ] Run `python3 -m unittest discover -v`.
- [ ] Run a private-value scan over docs and code.
- [ ] Run `python3 -m claude_env --help`.
- [ ] Report changed files and verification results.
