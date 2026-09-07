from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .store import Provider, Store
from .wrapper import validate_provider_name

from . import __version__


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = shortcut_argv(sys.argv)
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "handler"):
        parser.print_help()
        return 0
    try:
        return args.handler(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="claude-env")
    subparsers = parser.add_subparsers(dest="command")

    add = subparsers.add_parser("add", help="add a provider wrapper")
    add.add_argument("name")
    add.add_argument("--url")
    add.add_argument("--token")
    add.add_argument("--model")
    add.add_argument("-y", "--yes", action="store_true")
    add.set_defaults(handler=handle_add)

    run = subparsers.add_parser("run", help="run claude with a managed provider")
    run.add_argument("name")
    run.add_argument("claude_args", nargs=argparse.REMAINDER)
    run.set_defaults(handler=handle_run)

    for command in ("remove", "rm", "delete", "del"):
        remove = subparsers.add_parser(command, help="remove a provider wrapper")
        remove.add_argument("name")
        remove.add_argument("-y", "--yes", action="store_true")
        remove.set_defaults(handler=handle_remove)

    list_cmd = subparsers.add_parser("list", help="list managed provider wrappers")
    list_cmd.set_defaults(handler=handle_list)

    version_cmd = subparsers.add_parser("version", help="print claude-env version")
    version_cmd.set_defaults(handler=handle_version)

    return parser


def handle_add(args: argparse.Namespace) -> int:
    name = validate_provider_name(args.name)
    base_url = args.url or input("Provider base URL: ").strip()
    token = args.token or getpass.getpass("Provider token: ").strip()
    default_model = args.model
    if default_model is None:
        default_model = input(
            "Default model (optional, press Enter to use provider default): "
        ).strip() or None
    if not base_url:
        print("error: provider base URL is required", file=sys.stderr)
        return 2
    if not token:
        print("error: provider token is required", file=sys.stderr)
        return 2

    paths = get_paths()
    wrapper_path = shortcut_path(paths["bin_dir"], name)
    store = Store(config_dir=paths["config_dir"])

    existing = store.get_provider(name)
    if wrapper_path.exists() and not args.yes:
        if not confirm(f"{wrapper_path} already exists. Overwrite?"):
            print(f"{wrapper_path} not overwritten", file=sys.stderr)
            return 1

    paths["bin_dir"].mkdir(parents=True, exist_ok=True)
    create_shortcut(wrapper_path, name)
    store.save_provider(
        Provider(
            name=name,
            default_model=default_model,
            wrapper_path=str(wrapper_path),
        )
    )

    _write_settings_file(paths["config_dir"], name, base_url, token)

    action = "updated" if existing else "created"
    print(f"{action} {wrapper_path}")
    return 0


def handle_run(args: argparse.Namespace) -> int:
    name = validate_provider_name(args.name)
    paths = get_paths()
    store = Store(config_dir=paths["config_dir"])
    provider = store.get_provider(name)
    if provider is None:
        print(f"provider {name!r} is not configured", file=sys.stderr)
        return 1

    settings_path = settings_env_path(paths["config_dir"], name)
    if not settings_path.exists():
        print(f"error: credentials file {settings_path} not found", file=sys.stderr)
        return 1

    claude_args = list(args.claude_args)
    if provider.default_model and not has_model_arg(claude_args):
        claude_args = ["--model", provider.default_model, *claude_args]

    command = [resolve_claude(), "--settings", str(settings_path), *claude_args]
    if is_windows() or os.environ.get("CLAUDE_ENV_EXEC_MODE") == "subprocess":
        return subprocess.call(command)
    os.execvp(command[0], command)
    return 127


def handle_remove(args: argparse.Namespace) -> int:
    name = validate_provider_name(args.name)
    paths = get_paths()
    wrapper_path = shortcut_path(paths["bin_dir"], name)
    store = Store(config_dir=paths["config_dir"])
    provider = store.get_provider(name)

    if provider is None:
        if wrapper_path.exists():
            print(f"{wrapper_path} is not managed by claude-env", file=sys.stderr)
            return 1
        print(f"provider {name!r} is not configured", file=sys.stderr)
        return 1

    managed_path = Path(provider.wrapper_path)
    if managed_path.exists() and not args.yes:
        if not confirm(f"Remove {managed_path}?"):
            print(f"{managed_path} not removed", file=sys.stderr)
            return 1

    if managed_path.exists():
        managed_path.unlink()
    settings_path = settings_env_path(paths["config_dir"], name)
    if settings_path.exists():
        settings_path.unlink()
    store.remove_provider(name)
    print(f"removed {managed_path}")
    return 0


def handle_list(args: argparse.Namespace) -> int:
    paths = get_paths()
    store = Store(config_dir=paths["config_dir"])
    providers = store.list_providers()
    if not providers:
        print("No providers configured.")
        return 0
    print("NAME\tBASE_URL\tDEFAULT_MODEL\tWRAPPER\tTOKEN")
    for provider in providers:
        model = provider.default_model or "-"
        settings_path = settings_env_path(paths["config_dir"], provider.name)
        if settings_path.exists():
            with settings_path.open("r", encoding="utf-8") as f:
                settings = json.load(f)
            base_url = settings.get("env", {}).get("ANTHROPIC_BASE_URL", "-")
        else:
            base_url = "-"
        print(
            f"{provider.name}\t{base_url}\t{model}\t"
            f"{provider.wrapper_path}\t***"
        )
    return 0


def handle_version(args: argparse.Namespace) -> int:
    print(__version__)
    return 0


def confirm(prompt: str) -> bool:
    answer = input(f"{prompt} [y/N] ").strip().lower()
    return answer in {"y", "yes"}


def has_model_arg(args: list[str]) -> bool:
    return any(arg == "--model" or arg.startswith("--model=") for arg in args)


def shortcut_argv(sys_argv: list[str]) -> list[str]:
    if not sys_argv:
        return []
    invoked = Path(sys_argv[0]).name
    if invoked.endswith(".cmd"):
        invoked = invoked[:-4]
    if invoked.startswith("claude-") and invoked != "claude-env":
        return ["run", invoked.removeprefix("claude-"), *sys_argv[1:]]
    return sys_argv[1:]


def create_shortcut(path: Path, name: str) -> None:
    if path.exists() or path.is_symlink():
        path.unlink()

    executable = os.environ.get("CLAUDE_ENV_EXECUTABLE")
    if executable:
        target = Path(executable)
    else:
        target = Path(sys.argv[0])

    if os.name != "nt" and target.exists() and os.access(target, os.X_OK):
        try:
            path.symlink_to(target.resolve())
            return
        except OSError:
            pass

    if is_windows():
        path.write_text(
            "@echo off\r\n"
            f"where claude-env.cmd >nul 2>&1\r\n"
            f"if %errorlevel% equ 0 (\r\n"
            f"  claude-env.cmd run {name} %*\r\n"
            f") else if exist \"%~dp0claude-env.cmd\" (\r\n"
            f"  \"%~dp0claude-env.cmd\" run {name} %*\r\n"
            f") else (\r\n"
            f"  python -m claude_env run {name} %*\r\n"
            f")\r\n",
            encoding="utf-8",
        )
        return

    path.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "script_dir=\"$(cd \"$(dirname \"$0\")\" && pwd)\"\n"
        "if [[ -x \"${script_dir}/claude-env\" ]]; then\n"
        f"  exec \"${{script_dir}}/claude-env\" run {name} \"$@\"\n"
        "elif command -v claude-env >/dev/null 2>&1; then\n"
        f"  exec claude-env run {name} \"$@\"\n"
        "else\n"
        f"  exec python3 -m claude_env run {name} \"$@\"\n"
        "fi\n",
        encoding="utf-8",
    )
    os.chmod(path, 0o755)


def get_paths() -> dict[str, Path]:
    home = Path(os.environ.get("CLAUDE_ENV_HOME", str(Path.home())))
    config_default = home / ".config" / "claude-env"
    if is_windows():
        config_default = Path(os.environ.get("APPDATA", str(home / "AppData" / "Roaming"))) / "claude-env"
    return {
        "home": home,
        "bin_dir": Path(
            os.environ.get("CLAUDE_ENV_BIN_DIR", str(home / ".local" / "bin"))
        ),
        "config_dir": Path(os.environ.get("CLAUDE_ENV_CONFIG_DIR", str(config_default))),
    }


def shortcut_path(bin_dir: Path, name: str) -> Path:
    suffix = ".cmd" if is_windows() else ""
    return bin_dir / f"claude-{name}{suffix}"


def is_windows() -> bool:
    platform = os.environ.get("CLAUDE_ENV_PLATFORM")
    if platform:
        return platform.lower() == "windows"
    return os.name == "nt"


def resolve_claude() -> str:
    found = shutil.which("claude")
    if found:
        return found
    if is_windows():
        found = shutil.which("claude.cmd")
        if found:
            return found
    # Fall back to the claude installed next to this wrapper, so the wrapper
    # still works when ~/.local/bin is not on PATH (cron, ssh, subshells).
    exe = os.environ.get("CLAUDE_ENV_EXECUTABLE")
    if exe:
        candidate = Path(exe).resolve().parent / "claude"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return "claude"


def settings_env_path(config_dir: Path, name: str) -> Path:
    env_dir = config_dir / "env"
    return env_dir / f"settings.{name}.json"


def _write_settings_file(config_dir: Path, name: str, base_url: str, token: str) -> None:
    env_dir = config_dir / "env"
    env_dir.mkdir(parents=True, exist_ok=True)
    settings_path = settings_env_path(config_dir, name)
    settings_data = json.dumps({
        "env": {
            "ANTHROPIC_BASE_URL": base_url,
            "ANTHROPIC_AUTH_TOKEN": token,
        }
    })
    tmp_path = settings_path.with_suffix(".json.tmp")
    tmp_path.write_text(settings_data, encoding="utf-8")
    os.chmod(tmp_path, 0o600)
    tmp_path.replace(settings_path)
    os.chmod(settings_path, 0o600)


def migrate_storage_v1_to_v2(config_dir: Path | None = None) -> int:
    """One-time migration from v1 (url/token in providers.json) to v2 (url/token in env/settings.*.json).
    Returns 0 on success, 1 if no migration needed, 2 on error.
    """
    config_dir = config_dir or get_paths()["config_dir"]
    store_path = config_dir / "providers.json"
    if not store_path.exists():
        return 1

    with store_path.open("r", encoding="utf-8-sig") as f:
        data = json.load(f)

    if data.get("version", 1) >= 2:
        return 1

    providers = data.get("providers", {})
    if not providers:
        return 1

    migrated = 0
    for name, item in providers.items():
        base_url = item.get("base_url")
        token = item.get("token")
        if base_url and token:
            _write_settings_file(config_dir, name, base_url, token)
            item.pop("base_url", None)
            item.pop("token", None)
            item["version"] = 2
            migrated += 1

    data["version"] = 2
    tmp_path = store_path.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
    os.chmod(tmp_path, 0o600)
    tmp_path.replace(store_path)
    os.chmod(store_path, 0o600)
    print(f"migrated {migrated} provider(s) to v2")
    return 0
