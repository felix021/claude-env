from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
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
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="claude-env")
    subparsers = parser.add_subparsers(dest="command")

    add = subparsers.add_parser("add", help="add a provider wrapper")
    add.add_argument("name")
    add.add_argument("--url")
    add.add_argument("--token")
    add.add_argument("--model")
    add.add_argument(
        "--auto-compact-window",
        type=int,
        metavar="TOKENS",
        help=(
            "set env.CLAUDE_CODE_AUTO_COMPACT_WINDOW to the provider's hard max context"
            " size in tokens; no need to reserve room for the compact summary, Claude"
            " Code keeps its own buffer and compacts before the limit"
        ),
    )
    add.add_argument("--yolo", action="store_true", help="also create a yolo shortcut (--dangerously-skip-permissions)")
    add.add_argument("-y", "--yes", action="store_true")
    add.set_defaults(handler=handle_add)

    add_yolo = subparsers.add_parser("add-yolo", help="create a yolo shortcut for an existing provider")
    add_yolo.add_argument("name")
    add_yolo.set_defaults(handler=handle_add_yolo)

    run = subparsers.add_parser("run", help="run claude with a managed provider")
    run.add_argument("name")
    run.add_argument("claude_args", nargs=argparse.REMAINDER)
    run.set_defaults(handler=handle_run)

    update = subparsers.add_parser("update", help="update a provider's settings")
    update.add_argument("name")
    update.add_argument("--url", help="new provider base URL")
    update.add_argument("--token", help="new provider token")
    model_group = update.add_mutually_exclusive_group()
    model_group.add_argument("--model", help="new default model")
    model_group.add_argument("--no-model", action="store_true", help="clear the default model")
    window_group = update.add_mutually_exclusive_group()
    window_group.add_argument(
        "--auto-compact-window", type=int, metavar="TOKENS", help="set the auto-compact window"
    )
    window_group.add_argument(
        "--no-auto-compact-window",
        action="store_true",
        help="clear the auto-compact window",
    )
    update.set_defaults(handler=handle_update)

    for command in ("remove", "rm", "delete", "del"):
        remove = subparsers.add_parser(command, help="remove a provider wrapper")
        remove.add_argument("name")
        remove.add_argument("-y", "--yes", action="store_true")
        remove.set_defaults(handler=handle_remove)

    list_cmd = subparsers.add_parser("list", help="list managed provider wrappers")
    list_cmd.set_defaults(handler=handle_list)

    version_cmd = subparsers.add_parser("version", help="print claude-env version")
    version_cmd.set_defaults(handler=handle_version)

    upgrade_cmd = subparsers.add_parser(
        "upgrade", help="upgrade claude-env to the latest version"
    )
    upgrade_cmd.add_argument(
        "--version",
        metavar="VERSION",
        help=(
            "install a specific version (e.g. 0.5.0 or v0.5.0);"
            " an explicit version may downgrade"
        ),
    )
    upgrade_cmd.set_defaults(handler=handle_upgrade)

    # Internal entry point for the installers. They run migrations through the
    # installed launcher instead of inlining Python code with an install path,
    # which breaks on Windows paths ("C:\Users\..." has \U, \A, ... escapes).
    migrate_cmd = subparsers.add_parser("_migrate", help=argparse.SUPPRESS)
    migrate_cmd.set_defaults(handler=handle_migrate)

    return parser


def handle_add(args: argparse.Namespace) -> int:
    name = validate_provider_name(args.name)
    if args.auto_compact_window is not None and args.auto_compact_window <= 0:
        raise ValueError("--auto-compact-window must be a positive integer (tokens)")
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
            default_model=None,
            wrapper_path=str(wrapper_path),
        )
    )

    _write_settings_file(
        paths["config_dir"],
        name,
        base_url,
        token,
        model=default_model,
        auto_compact_window=args.auto_compact_window,
    )

    action = "updated" if existing else "created"
    print(f"{action} {wrapper_path}")

    if getattr(args, "yolo", False):
        _create_yolo_shortcut(paths["bin_dir"], name)

    return 0


def handle_add_yolo(args: argparse.Namespace) -> int:
    name = validate_provider_name(args.name)
    paths = get_paths()
    store = Store(config_dir=paths["config_dir"])
    provider = store.get_provider(name)
    if provider is None:
        print(f"provider {name!r} is not configured", file=sys.stderr)
        return 1
    _create_yolo_shortcut(paths["bin_dir"], name)
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
    settings = _read_settings(settings_path) or {}
    default_model = settings.get("model") or provider.default_model
    if default_model and not has_model_arg(claude_args):
        claude_args = ["--model", default_model, *claude_args]

    if has_yolo_arg(claude_args):
        claude_args = [a for a in claude_args if a != "--yolo"]
        claude_args.append("--dangerously-skip-permissions")

    claude_path = resolve_claude()
    if claude_path is None:
        print(
            "error: claude executable not found\n"
            "Install Claude Code first, e.g.: curl -fsSL https://claude.ai/install.sh | bash",
            file=sys.stderr,
        )
        return 127

    command = [claude_path, "--settings", str(settings_path), *claude_args]
    child_env = os.environ.copy()
    # Third-party profiles authenticate with ANTHROPIC_AUTH_TOKEN, which always
    # takes precedence over the claude.ai login, so the connectors can never
    # load. Tell Claude Code not to try (and not to warn about it) unless the
    # user explicitly asked for the default behavior.
    child_env.setdefault("ENABLE_CLAUDEAI_MCP_SERVERS", "0")

    if is_headless(claude_args) and not os.environ.get("CLAUDE_ENV_NO_STDERR_FILTER"):
        return run_with_filtered_stderr(command, child_env)
    if is_windows() or os.environ.get("CLAUDE_ENV_EXEC_MODE") == "subprocess":
        return subprocess.call(command, env=child_env)
    os.execvpe(command[0], command, child_env)
    return 127


def handle_update(args: argparse.Namespace) -> int:
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

    if args.auto_compact_window is not None and args.auto_compact_window <= 0:
        raise ValueError("--auto-compact-window must be a positive integer (tokens)")
    if args.url is not None and not args.url.strip():
        raise ValueError("--url must not be empty")
    if args.token is not None and not args.token.strip():
        raise ValueError("--token must not be empty")
    if args.model is not None and not args.model.strip():
        raise ValueError("--model must not be empty; use --no-model to clear it")

    requested = any(
        (
            args.url is not None,
            args.token is not None,
            args.model is not None,
            args.no_model,
            args.auto_compact_window is not None,
            args.no_auto_compact_window,
        )
    )
    if not requested:
        print(
            "error: nothing to update; pass --url, --token, --model, --no-model, "
            "--auto-compact-window or --no-auto-compact-window",
            file=sys.stderr,
        )
        return 2

    settings = _read_settings(settings_path)
    if settings is None:
        print(f"error: could not read credentials file {settings_path}", file=sys.stderr)
        return 1
    env = settings.get("env", {})
    if not isinstance(env, dict):
        raise ValueError(f"invalid credentials file {settings_path}: env must be an object")

    if args.url is not None:
        env["ANTHROPIC_BASE_URL"] = args.url
    if args.token is not None:
        env["ANTHROPIC_AUTH_TOKEN"] = args.token
    if args.auto_compact_window is not None:
        env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = str(args.auto_compact_window)
    if args.no_auto_compact_window:
        env.pop("CLAUDE_CODE_AUTO_COMPACT_WINDOW", None)
    if args.no_model:
        settings.pop("model", None)
    elif args.model is not None:
        settings["model"] = args.model
    settings["env"] = env

    _write_settings_json(settings_path, settings)

    # Also clear the legacy providers.json fallback; otherwise `run` can still
    # inject an old default_model after an explicit --no-model.
    if args.no_model and provider.default_model is not None:
        store.save_provider(
            Provider(
                name=name,
                default_model=None,
                wrapper_path=provider.wrapper_path,
            )
        )

    print(f"updated {name}")
    return 0


NOISE_MARKERS = (
    b"[claude-code:unrecognized_model]",
    b"code.claude.com/docs/en/auto-mode-classifier-billing",
)


def is_noise_line(line: bytes) -> bool:
    return any(marker in line for marker in NOISE_MARKERS)


def is_headless(args: list[str]) -> bool:
    for arg in args:
        if arg == "--":
            break
        if arg in ("-p", "--print"):
            return True
        if arg.startswith(("--print=", "--output-format", "--input-format")):
            return True
    return False


def run_with_filtered_stderr(command: list[str], env: dict[str, str]) -> int:
    # With exec the signal reaches claude directly. Now that we supervise it,
    # forward termination signals ourselves so a wrapper killed by `timeout`,
    # CI, or the job scheduler never leaves an orphan claude behind.
    process: subprocess.Popen | None = None
    pending_signals: list[int] = []
    previous_handlers: dict[int, object] = {}

    def forward(signum: int, frame: object) -> None:
        if process is None:
            pending_signals.append(signum)
        elif process.poll() is None:
            try:
                process.send_signal(signum)
            except OSError:
                pass

    for name in ("SIGTERM", "SIGHUP", "SIGQUIT"):
        signum = getattr(signal, name, None)
        if signum is not None:
            previous_handlers[signum] = signal.signal(signum, forward)

    try:
        try:
            process = subprocess.Popen(command, stderr=subprocess.PIPE, env=env)
        except OSError as exc:
            print(f"error: failed to start claude: {exc}", file=sys.stderr)
            return 127
        for signum in pending_signals:
            if process.poll() is None:
                process.send_signal(signum)

        assert process.stderr is not None
        try:
            try:
                for line in process.stderr:
                    if is_noise_line(line):
                        continue
                    try:
                        _write_stderr_bytes(line)
                    except (BrokenPipeError, OSError):
                        # Our own stderr went away; keep draining the child so it
                        # never blocks on a full pipe.
                        pass
            except KeyboardInterrupt:
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                return 130
        finally:
            process.stderr.close()

        return _normalize_returncode(process.wait())
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


def _write_stderr_bytes(raw: bytes) -> None:
    buffer = getattr(sys.stderr, "buffer", None)
    if buffer is not None:
        buffer.write(raw)
        buffer.flush()
    else:
        sys.stderr.write(raw.decode("utf-8", "replace"))
        sys.stderr.flush()


def _normalize_returncode(returncode: int) -> int:
    # A child killed by signal N reports -N; the shell convention is 128 + N.
    return 128 - returncode if returncode < 0 else returncode


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
    print("NAME\tBASE_URL\tDEFAULT_MODEL\tAUTO_COMPACT_WINDOW\tWRAPPER\tTOKEN")
    for provider in providers:
        settings_path = settings_env_path(paths["config_dir"], provider.name)
        settings = _read_settings(settings_path) if settings_path.exists() else None
        if settings is None:
            settings = {}
        base_url = settings.get("env", {}).get("ANTHROPIC_BASE_URL", "-")
        window = settings.get("env", {}).get("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "-")
        model = settings.get("model") or provider.default_model or "-"
        print(
            f"{provider.name}\t{base_url}\t{model}\t{window}\t"
            f"{provider.wrapper_path}\t***"
        )
    return 0


def handle_version(args: argparse.Namespace) -> int:
    print(__version__)
    return 0


INSTALLER_URL = "https://raw.githubusercontent.com/felix021/claude-env/main/install.sh"
INSTALLER_URL_WINDOWS = "https://raw.githubusercontent.com/felix021/claude-env/main/install.ps1"
APP_DIR_RELATIVE = Path(".local") / "share" / "claude-env"


def installer_url() -> str:
    override = os.environ.get("CLAUDE_ENV_INSTALLER_URL")
    if override:
        return override
    return INSTALLER_URL_WINDOWS if is_windows() else INSTALLER_URL


def installer_command(script_path: Path) -> list[str]:
    if is_windows():
        return [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
        ]
    return ["bash", str(script_path)]


def installed_version(home: Path) -> str | None:
    init_path = home / APP_DIR_RELATIVE / "claude_env" / "__init__.py"
    try:
        text = init_path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r'^__version__ = "([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else None


def download_installer(url: str, dest: Path) -> None:
    with urllib.request.urlopen(url, timeout=60) as response:
        with dest.open("wb") as f:
            shutil.copyfileobj(response, f)


def version_archive_url(version: str) -> str:
    tag = version if version.startswith("v") else f"v{version}"
    suffix = ".zip" if is_windows() else ".tar.gz"
    return f"https://github.com/felix021/claude-env/archive/refs/tags/{tag}{suffix}"


def restore_app_dir(app_dir: Path, backup_dir: Path) -> None:
    """Put the pre-upgrade code back after a failed or refused install."""
    if not backup_dir.is_dir():
        return
    shutil.rmtree(app_dir, ignore_errors=True)
    shutil.copytree(backup_dir, app_dir)


def handle_upgrade(args: argparse.Namespace) -> int:
    paths = get_paths()
    app_dir = paths["home"] / APP_DIR_RELATIVE
    before = installed_version(paths["home"])
    requested = args.version
    url = installer_url()
    print(f"upgrading claude-env (installed: {before or 'none'})...", flush=True)

    tmp_dir = Path(tempfile.mkdtemp(prefix="claude-env-upgrade-"))
    backup_dir = tmp_dir / "backup"
    installer_env = os.environ.copy()
    if requested:
        installer_env["CLAUDE_ENV_URL"] = version_archive_url(requested)
        # A stale local source override would silently win over --version.
        installer_env.pop("CLAUDE_ENV_SOURCE_DIR", None)
        installer_env.pop("CLAUDE_ENV_SOURCE", None)

    try:
        if app_dir.is_dir():
            shutil.copytree(app_dir, backup_dir)

        script = tmp_dir / ("install.ps1" if is_windows() else "install.sh")
        try:
            download_installer(url, script)
        except (OSError, urllib.error.URLError) as exc:
            print(
                f"error: failed to download installer from {url}: {exc}",
                file=sys.stderr,
            )
            return 1

        try:
            rc = subprocess.call(installer_command(script), env=installer_env)
        except OSError as exc:
            print(f"error: failed to run installer: {exc}", file=sys.stderr)
            return 127
        if rc != 0:
            rc = _normalize_returncode(rc)
            restore_app_dir(app_dir, backup_dir)
            print(f"error: installer exited with status {rc}", file=sys.stderr)
            return rc

        after = installed_version(paths["home"])
        if (
            requested is None
            and before is not None
            and after is not None
            and version_key(after) < version_key(before)
        ):
            restore_app_dir(app_dir, backup_dir)
            print(
                f"error: refusing to downgrade claude-env {before} -> {after}"
                f" (restored {before}); to downgrade explicitly, run"
                f" `claude-env upgrade --version {after}`",
                file=sys.stderr,
            )
            return 1
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    if requested and after is not None and after.lstrip("v") != requested.lstrip("v"):
        print(f"warning: requested {requested} but installed {after}", file=sys.stderr)

    if after is None:
        print("upgrade finished")
    elif before is None:
        print(f"installed claude-env {after}")
    elif before == after:
        print(f"claude-env {after} is already installed; reinstalled it")
    elif version_key(after) < version_key(before):
        print(f"downgraded claude-env {before} -> {after}")
    else:
        print(f"upgraded claude-env {before} -> {after}")
    return 0


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", version))


def handle_migrate(args: argparse.Namespace) -> int:
    migrate_storage()
    return 0


def confirm(prompt: str) -> bool:
    answer = input(f"{prompt} [y/N] ").strip().lower()
    return answer in {"y", "yes"}


def has_model_arg(args: list[str]) -> bool:
    return any(arg == "--model" or arg.startswith("--model=") for arg in args)


def has_yolo_arg(args: list[str]) -> bool:
    return "--yolo" in args


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


def _create_yolo_shortcut(bin_dir: Path, name: str) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    yolo_path = shortcut_path(bin_dir, f"{name}-yolo")
    if is_windows():
        yolo_path.write_text(
            "@echo off\r\n"
            f"where claude-env.cmd >nul 2>&1\r\n"
            f"if %errorlevel% equ 0 (\r\n"
            f"  claude-env.cmd run {name} --yolo %*\r\n"
            f") else if exist \"%~dp0claude-env.cmd\" (\r\n"
            f"  \"%~dp0claude-env.cmd\" run {name} --yolo %*\r\n"
            f") else (\r\n"
            f"  python -m claude_env run {name} --yolo %*\r\n"
            f")\r\n",
            encoding="utf-8",
        )
    else:
        yolo_path.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "script_dir=\"$(cd \"$(dirname \"$0\")\" && pwd)\"\n"
            "if [[ -x \"${script_dir}/claude-env\" ]]; then\n"
            f"  exec \"${{script_dir}}/claude-env\" run {name} --yolo \"$@\"\n"
            "elif command -v claude-env >/dev/null 2>&1; then\n"
            f"  exec claude-env run {name} --yolo \"$@\"\n"
            "else\n"
            f"  exec python3 -m claude_env run {name} --yolo \"$@\"\n"
            "fi\n",
            encoding="utf-8",
        )
        os.chmod(yolo_path, 0o755)
    print(f"created {yolo_path}")


def is_windows() -> bool:
    platform = os.environ.get("CLAUDE_ENV_PLATFORM")
    if platform:
        return platform.lower() == "windows"
    return os.name == "nt"


def resolve_claude() -> str | None:
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
    return None


def settings_env_path(config_dir: Path, name: str) -> Path:
    env_dir = config_dir / "env"
    return env_dir / f"settings.{name}.json"


def _read_settings(settings_path: Path) -> dict | None:
    """Return the parsed settings, or None when the file cannot be read."""
    try:
        with settings_path.open("r", encoding="utf-8") as f:
            settings = json.load(f)
    except (OSError, ValueError):
        return None
    return settings if isinstance(settings, dict) else None


def _write_settings_json(settings_path: Path, settings: dict) -> None:
    tmp_path = settings_path.with_suffix(".json.tmp")
    tmp_path.write_text(
        json.dumps(settings, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.chmod(tmp_path, 0o600)
    tmp_path.replace(settings_path)
    os.chmod(settings_path, 0o600)


def _write_settings_file(
    config_dir: Path,
    name: str,
    base_url: str,
    token: str,
    model: str | None = None,
    auto_compact_window: int | None = None,
) -> None:
    env_dir = config_dir / "env"
    env_dir.mkdir(parents=True, exist_ok=True)
    env_settings = {
        "ANTHROPIC_BASE_URL": base_url,
        "ANTHROPIC_AUTH_TOKEN": token,
    }
    if auto_compact_window is not None:
        env_settings["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = str(auto_compact_window)
    settings = {"env": env_settings}
    if model:
        settings["model"] = model
    _write_settings_json(settings_env_path(config_dir, name), settings)


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


def migrate_storage_v2_to_v3(config_dir: Path | None = None) -> int:
    """One-time migration from v2 (default_model in providers.json) to v3 (model in env/settings.*.json).
    Returns 0 on success, 1 if no migration needed, 2 on error.
    """
    config_dir = config_dir or get_paths()["config_dir"]
    store_path = config_dir / "providers.json"
    if not store_path.exists():
        return 1

    with store_path.open("r", encoding="utf-8-sig") as f:
        data = json.load(f)

    if data.get("version", 1) >= 3:
        return 1

    providers = data.get("providers", {})
    migrated = 0
    for name, item in providers.items():
        default_model = item.get("default_model")
        if not default_model:
            continue
        settings_path = settings_env_path(config_dir, name)
        if not settings_path.exists():
            # No credentials file to hold the model; keep the providers.json fallback.
            continue
        settings = _read_settings(settings_path)
        if settings is None:
            continue
        settings.setdefault("model", default_model)
        _write_settings_json(settings_path, settings)
        item.pop("default_model", None)
        item["version"] = 3
        migrated += 1

    data["version"] = 3
    tmp_path = store_path.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
    os.chmod(tmp_path, 0o600)
    tmp_path.replace(store_path)
    os.chmod(store_path, 0o600)
    print(f"migrated {migrated} provider(s) to v3")
    return 0


def migrate_storage(config_dir: Path | None = None) -> None:
    """Run all one-time storage migrations in order."""
    migrate_storage_v1_to_v2(config_dir)
    migrate_storage_v2_to_v3(config_dir)
