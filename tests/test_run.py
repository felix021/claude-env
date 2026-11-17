import json
import os
import shutil
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from claude_env.cli import is_headless
from tests.mock_provider import MockAnthropicProvider


NOISE_LINES = [
    '[claude-code:unrecognized_model] {"model":"fake-model","query_source":"sdk"}',
    "We're changing auto mode to no longer charge for classifier requests in Claude Code. "
    "see https://code.claude.com/docs/en/auto-mode-classifier-billing",
]
REAL_STDERR_LINE = "real diagnostic: fake claude"


def write_fake_claude(bin_dir: Path) -> Path:
    args_file = bin_dir / "claude_args.txt"
    env_file = bin_dir / "claude_env.txt"
    process_env_file = bin_dir / "claude_process_env.txt"
    pid_file = bin_dir / "claude_pid.txt"
    fake = bin_dir / "claude"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, signal, sys, urllib.request\n"
        "args = sys.argv[1:]\n"
        "args_file = r'" + str(args_file).replace("\\", "\\\\") + "'\n"
        "env_file = r'" + str(env_file).replace("\\", "\\\\") + "'\n"
        "process_env_file = r'" + str(process_env_file).replace("\\", "\\\\") + "'\n"
        "pid_file = r'" + str(pid_file).replace("\\", "\\\\") + "'\n"
        "with open(pid_file, 'w') as f:\n"
        "    f.write(str(os.getpid()))\n"
        "with open(args_file, 'w') as f:\n"
        "    f.write(' '.join(args))\n"
        "with open(process_env_file, 'w') as f:\n"
        "    f.write(json.dumps({'ENABLE_CLAUDEAI_MCP_SERVERS': os.environ.get('ENABLE_CLAUDEAI_MCP_SERVERS')}))\n"
        "stderr = sys.stderr\n"
        "for line in " + repr(NOISE_LINES) + ":\n"
        "    stderr.write(line + '\\n')\n"
        "if os.environ.get('FAKE_CLAUDE_STDERR_FLOOD'):\n"
        "    for _ in range(1000):\n"
        "        stderr.write('[claude-code:unrecognized_model] flood\\n')\n"
        "stderr.write(" + repr(REAL_STDERR_LINE) + " + '\\n')\n"
        "stderr.flush()\n"
        "if os.environ.get('FAKE_CLAUDE_SLEEP'):\n"
        "    import time\n"
        "    time.sleep(float(os.environ['FAKE_CLAUDE_SLEEP']))\n"
        "if os.environ.get('FAKE_CLAUDE_SIGNAL'):\n"
        "    os.kill(os.getpid(), int(os.environ['FAKE_CLAUDE_SIGNAL']))\n"
        "    sys.exit(1)\n"
        "model = None\n"
        "prompt = ''\n"
        "settings_env = {}\n"
        "i = 0\n"
        "while i < len(args):\n"
        "    arg = args[i]\n"
        "    if arg == '--settings':\n"
        "        val = args[i + 1]\n"
        "        with open(val) as f:\n"
        "            settings_env = json.load(f).get('env', {})\n"
        "        i += 2\n"
        "    elif arg.startswith('--settings='):\n"
        "        with open(arg[len('--settings='):]) as f:\n"
        "            settings_env = json.load(f).get('env', {})\n"
        "        i += 1\n"
        "    elif arg == '--model':\n"
        "        model = args[i + 1]\n"
        "        i += 2\n"
        "    elif arg.startswith('--model='):\n"
        "        model = arg.split('=', 1)[1]\n"
        "        i += 1\n"
        "    elif arg.startswith('-'):\n"
        "        i += 1\n"
        "    else:\n"
        "        prompt = arg\n"
        "        i += 1\n"
        "base_url = settings_env.get('ANTHROPIC_BASE_URL', '')\n"
        "token = settings_env.get('ANTHROPIC_AUTH_TOKEN', '')\n"
        "with open(env_file, 'w') as f:\n"
        "    f.write(json.dumps(settings_env))\n"
        "body = json.dumps({'model': model, 'messages': [{'role': 'user', 'content': prompt}]}).encode()\n"
        "req = urllib.request.Request(\n"
        "    base_url,\n"
        "    data=body,\n"
        "    headers={\n"
        "        'content-type': 'application/json',\n"
        "        'x-api-key': token,\n"
        "    },\n"
        "    method='POST',\n"
        ")\n"
        "with urllib.request.urlopen(req, timeout=10) as response:\n"
        "    data = json.loads(response.read().decode())\n"
        "print(data['content'][0]['text'])\n"
        "if os.environ.get('FAKE_CLAUDE_EXIT'):\n"
        "    sys.exit(int(os.environ['FAKE_CLAUDE_EXIT']))\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    # On Windows, also create a .cmd wrapper so shutil.which("claude") finds it
    if os.name == "nt":
        cmd_wrapper = bin_dir / "claude.cmd"
        cmd_wrapper.write_text(
            f'@python "{fake}" %*\r\n',
            encoding="utf-8",
        )


class RunTests(unittest.TestCase):
    def cli_env(
        self,
        home: Path,
        *,
        path_prefix: Path,
        extra_env: dict[str, str] | None = None,
    ) -> dict[str, str]:
        env = os.environ.copy()
        for key in (
            "CLAUDE_ENV_NO_STDERR_FILTER",
            "CLAUDE_ENV_EXEC_MODE",
            "CLAUDE_ENV_EXECUTABLE",
            "CLAUDE_ENV_PLATFORM",
            "CLAUDE_ENV_INSTALLER_URL",
            "FAKE_CLAUDE_EXIT",
            "FAKE_CLAUDE_SIGNAL",
            "FAKE_CLAUDE_SLEEP",
            "FAKE_CLAUDE_STDERR_FLOOD",
            "ENABLE_CLAUDEAI_MCP_SERVERS",
        ):
            env.pop(key, None)
        path_sep = ";" if os.name == "nt" else ":"
        env.update(
            {
                "CLAUDE_ENV_HOME": str(home),
                "CLAUDE_ENV_BIN_DIR": str(home / ".local" / "bin"),
                "CLAUDE_ENV_CONFIG_DIR": str(home / ".config" / "claude-env"),
                "PATH": f"{path_prefix}{path_sep}{env['PATH']}",
                "PYTHONDONTWRITEBYTECODE": "1",
                # Bypass system proxy for mock provider on localhost
                "NO_PROXY": "127.0.0.1,localhost",
            }
        )
        if extra_env:
            env.update(extra_env)
        return env

    def run_cli(
        self,
        home: Path,
        argv: list[str],
        *,
        path_prefix: Path,
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "claude_env", *argv],
            cwd=Path(__file__).resolve().parents[1],
            env=self.cli_env(home, path_prefix=path_prefix, extra_env=extra_env),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            encoding="utf-8",
        )

    def test_run_uses_config_env_and_default_model_with_mock_provider(self):
        with TemporaryDirectory() as temp, MockAnthropicProvider() as provider:
            home = Path(temp)
            bin_dir = home / "fake-bin"
            bin_dir.mkdir()
            write_fake_claude(bin_dir)
            add = self.run_cli(
                home,
                [
                    "add",
                    "glm",
                    "--url",
                    provider.url,
                    "--token",
                    "test-token",
                    "--model",
                    "glm-5-turbo",
                    "-y",
                ],
                path_prefix=bin_dir,
            )
            self.assertEqual(add.returncode, 0, add.stderr)

            result = self.run_cli(home, ["run", "glm", "-p", "hello"], path_prefix=bin_dir)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "OK")
            self.assertEqual(provider.requests[0]["headers"]["X-Api-Key"], "test-token")
            self.assertEqual(provider.requests[0]["body"]["model"], "glm-5-turbo")

    def test_run_falls_back_to_providers_json_default_model(self):
        # Simulate a not-yet-migrated v2 config: model only in providers.json
        with TemporaryDirectory() as temp, MockAnthropicProvider() as provider:
            home = Path(temp)
            bin_dir = home / "fake-bin"
            bin_dir.mkdir()
            write_fake_claude(bin_dir)
            self.run_cli(
                home,
                [
                    "add", "glm",
                    "--url", provider.url,
                    "--token", "test-token",
                    "--model", "glm-5-turbo",
                    "-y",
                ],
                path_prefix=bin_dir,
            )
            config_dir = home / ".config" / "claude-env"
            settings_file = config_dir / "env" / "settings.glm.json"
            settings = json.loads(settings_file.read_text())
            settings.pop("model", None)  # simulate pre-v3 settings file
            settings_file.write_text(json.dumps(settings))
            data = json.loads((config_dir / "providers.json").read_text())
            data["providers"]["glm"]["default_model"] = "legacy-model"
            (config_dir / "providers.json").write_text(json.dumps(data))

            result = self.run_cli(home, ["run", "glm", "-p", "hello"], path_prefix=bin_dir)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(provider.requests[0]["body"]["model"], "legacy-model")

    def test_run_passes_auto_compact_window_via_settings_env(self):
        with TemporaryDirectory() as temp, MockAnthropicProvider() as provider:
            home = Path(temp)
            bin_dir = home / "fake-bin"
            bin_dir.mkdir()
            write_fake_claude(bin_dir)
            self.run_cli(
                home,
                [
                    "add", "glm",
                    "--url", provider.url,
                    "--token", "test-token",
                    "--model", "glm-5-turbo",
                    "--auto-compact-window", "118784",
                    "-y",
                ],
                path_prefix=bin_dir,
            )

            result = self.run_cli(home, ["run", "glm", "-p", "hello"], path_prefix=bin_dir)

            self.assertEqual(result.returncode, 0, result.stderr)
            settings_env = json.loads((bin_dir / "claude_env.txt").read_text())
            self.assertEqual(
                settings_env.get("CLAUDE_CODE_AUTO_COMPACT_WINDOW"), "118784"
            )

    def test_run_runtime_model_overrides_default_model(self):
        with TemporaryDirectory() as temp, MockAnthropicProvider() as provider:
            home = Path(temp)
            bin_dir = home / "fake-bin"
            bin_dir.mkdir()
            write_fake_claude(bin_dir)
            self.run_cli(
                home,
                [
                    "add",
                    "glm",
                    "--url",
                    provider.url,
                    "--token",
                    "test-token",
                    "--model",
                    "glm-5-turbo",
                    "-y",
                ],
                path_prefix=bin_dir,
            )

            result = self.run_cli(
                home,
                ["run", "glm", "--model", "glm-5.1", "-p", "hello"],
                path_prefix=bin_dir,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(provider.requests[0]["body"]["model"], "glm-5.1")

    def test_shortcut_contains_no_credentials_and_dispatches_to_run(self):
        with TemporaryDirectory() as temp, MockAnthropicProvider() as provider:
            home = Path(temp)
            fake_bin = home / "fake-bin"
            fake_bin.mkdir()
            write_fake_claude(fake_bin)
            add = self.run_cli(
                home,
                [
                    "add",
                    "glm",
                    "--url",
                    provider.url,
                    "--token",
                    "test-token",
                    "--model",
                    "glm-5-turbo",
                    "-y",
                ],
                path_prefix=fake_bin,
            )
            self.assertEqual(add.returncode, 0, add.stderr)
            shortcut = home / ".local" / "bin" / "claude-glm"
            suffix = ".cmd" if os.name == "nt" else ""
            shortcut = shortcut.parent / f"{shortcut.name}{suffix}"
            if shortcut.is_symlink():
                shortcut_text = ""
            else:
                shortcut_text = shortcut.read_text(encoding="utf-8")
            self.assertNotIn(provider.url, shortcut_text)
            self.assertNotIn("test-token", shortcut_text)

            path_sep = ";" if os.name == "nt" else ":"
            env = os.environ.copy()
            env.update(
                {
                    "CLAUDE_ENV_HOME": str(home),
                    "CLAUDE_ENV_BIN_DIR": str(home / ".local" / "bin"),
                    "CLAUDE_ENV_CONFIG_DIR": str(home / ".config" / "claude-env"),
                    "PATH": f"{fake_bin}{path_sep}{home / '.local' / 'bin'}{path_sep}{env['PATH']}",
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "NO_PROXY": "127.0.0.1,localhost",
                }
            )
            # Capture bytes and decode to handle Windows console encoding (GBK/CP437)
            result = subprocess.run(
                [str(shortcut), "-p", "hello"],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            stdout = result.stdout.decode("utf-8", errors="replace")
            stderr = result.stderr.decode("utf-8", errors="replace")

            self.assertEqual(result.returncode, 0, stderr)
            self.assertEqual(stdout.strip(), "OK")

    def test_run_overrides_conflicting_global_settings_env(self):
        with TemporaryDirectory() as temp, MockAnthropicProvider() as provider:
            home = Path(temp)
            bin_dir = home / "fake-bin"
            bin_dir.mkdir()
            write_fake_claude(bin_dir)
            # Global settings has conflicting (wrong) creds
            settings_dir = home / ".claude"
            settings_dir.mkdir()
            (settings_dir / "settings.json").write_text(
                json.dumps(
                    {
                        "env": {
                            "ANTHROPIC_BASE_URL": "https://wrong.example",
                            "ANTHROPIC_AUTH_TOKEN": "wrong-token",
                        }
                    }
                ),
                encoding="utf-8",
            )
            add = self.run_cli(
                home,
                [
                    "add",
                    "glm",
                    "--url",
                    provider.url,
                    "--token",
                    "test-token",
                    "--model",
                    "glm-5-turbo",
                    "-y",
                ],
                path_prefix=bin_dir,
            )
            self.assertEqual(add.returncode, 0, add.stderr)

            # Should still work -- settings via --settings overrides global
            result = self.run_cli(home, ["run", "glm", "-p", "hello"], path_prefix=bin_dir)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "OK")
            self.assertEqual(provider.requests[0]["headers"]["X-Api-Key"], "test-token")

    def test_run_yolo_adds_dangerously_skip_permissions(self):
        with TemporaryDirectory() as temp, MockAnthropicProvider() as provider:
            home = Path(temp)
            bin_dir = home / "fake-bin"
            bin_dir.mkdir()
            write_fake_claude(bin_dir)
            self.run_cli(
                home,
                [
                    "add", "glm",
                    "--url", provider.url,
                    "--token", "test-token",
                    "--model", "glm-5-turbo",
                    "-y",
                ],
                path_prefix=bin_dir,
            )

            result = self.run_cli(home, ["run", "glm", "--yolo", "-p", "hello"], path_prefix=bin_dir)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "OK")
            raw_args = (bin_dir / "claude_args.txt").read_text()
            self.assertIn("--dangerously-skip-permissions", raw_args)

    def test_run_without_yolo_does_not_add_dangerously_skip_permissions(self):
        with TemporaryDirectory() as temp, MockAnthropicProvider() as provider:
            home = Path(temp)
            bin_dir = home / "fake-bin"
            bin_dir.mkdir()
            write_fake_claude(bin_dir)
            self.run_cli(
                home,
                [
                    "add", "glm",
                    "--url", provider.url,
                    "--token", "test-token",
                    "--model", "glm-5-turbo",
                    "-y",
                ],
                path_prefix=bin_dir,
            )

            result = self.run_cli(home, ["run", "glm", "-p", "hello"], path_prefix=bin_dir)

            self.assertEqual(result.returncode, 0, result.stderr)
            raw_args = (bin_dir / "claude_args.txt").read_text()
            self.assertNotIn("--dangerously-skip-permissions", raw_args)

    def test_run_allows_unrelated_claude_settings_env_keys(self):
        with TemporaryDirectory() as temp, MockAnthropicProvider() as provider:
            home = Path(temp)
            bin_dir = home / "fake-bin"
            bin_dir.mkdir()
            write_fake_claude(bin_dir)
            settings_dir = home / ".claude"
            settings_dir.mkdir()
            (settings_dir / "settings.json").write_text(
                json.dumps({"env": {"SOME_OTHER_KEY": "value"}}),
                encoding="utf-8",
            )
            add = self.run_cli(
                home,
                [
                    "add",
                    "glm",
                    "--url",
                    provider.url,
                    "--token",
                    "test-token",
                    "--model",
                    "glm-5-turbo",
                    "-y",
                ],
                path_prefix=bin_dir,
            )
            self.assertEqual(add.returncode, 0, add.stderr)

            result = self.run_cli(home, ["run", "glm", "-p", "hello"], path_prefix=bin_dir)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "OK")

    def test_run_resolves_claude_next_to_wrapper_when_not_on_path(self):
        if os.name == "nt":
            self.skipTest("execvp path only applies to POSIX")
        if shutil.which("claude"):
            self.skipTest("a real claude is already on PATH")
        with TemporaryDirectory() as temp, MockAnthropicProvider() as provider:
            home = Path(temp)
            fake_bin = home / "fake-bin"
            fake_bin.mkdir()
            write_fake_claude(fake_bin)
            wrapper = fake_bin / "claude-env"
            wrapper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            wrapper.chmod(0o755)
            empty_path = home / "empty-path"
            empty_path.mkdir()
            add = self.run_cli(
                home,
                [
                    "add",
                    "glm",
                    "--url",
                    provider.url,
                    "--token",
                    "test-token",
                    "--model",
                    "glm-5-turbo",
                    "-y",
                ],
                path_prefix=fake_bin,
            )
            self.assertEqual(add.returncode, 0, add.stderr)

            path_sep = ";" if os.name == "nt" else ":"
            env = os.environ.copy()
            env.update(
                {
                    "CLAUDE_ENV_HOME": str(home),
                    "CLAUDE_ENV_BIN_DIR": str(home / ".local" / "bin"),
                    "CLAUDE_ENV_CONFIG_DIR": str(home / ".config" / "claude-env"),
                    "PATH": f"{empty_path}{path_sep}{env['PATH']}",
                    "CLAUDE_ENV_EXECUTABLE": str(wrapper),
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "NO_PROXY": "127.0.0.1,localhost",
                }
            )
            result = subprocess.run(
                [sys.executable, "-m", "claude_env", "run", "glm", "-p", "hello"],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding="utf-8",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "OK")

    def add_provider(self, home: Path, provider: MockAnthropicProvider, bin_dir: Path) -> None:
        write_fake_claude(bin_dir)
        add = self.run_cli(
            home,
            [
                "add", "glm",
                "--url", provider.url,
                "--token", "test-token",
                "--model", "glm-5-turbo",
                "-y",
            ],
            path_prefix=bin_dir,
        )
        self.assertEqual(add.returncode, 0, add.stderr)

    def test_is_headless_detection(self):
        self.assertTrue(is_headless(["-p", "hello"]))
        self.assertTrue(is_headless(["--print"]))
        self.assertTrue(is_headless(["--output-format", "json"]))
        self.assertTrue(is_headless(["--output-format=stream-json"]))
        self.assertTrue(is_headless(["--input-format=stream-json"]))
        self.assertFalse(is_headless([]))
        self.assertFalse(is_headless(["hello"]))
        self.assertFalse(is_headless(["--", "-p"]))

    def test_run_filters_headless_stderr_noise(self):
        with TemporaryDirectory() as temp, MockAnthropicProvider() as provider:
            home = Path(temp)
            bin_dir = home / "fake-bin"
            bin_dir.mkdir()
            self.add_provider(home, provider, bin_dir)

            result = self.run_cli(home, ["run", "glm", "-p", "hello"], path_prefix=bin_dir)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "OK")
            self.assertEqual(result.stderr, REAL_STDERR_LINE + "\n")

    def test_run_keeps_stderr_noise_without_print_mode(self):
        with TemporaryDirectory() as temp, MockAnthropicProvider() as provider:
            home = Path(temp)
            bin_dir = home / "fake-bin"
            bin_dir.mkdir()
            self.add_provider(home, provider, bin_dir)

            result = self.run_cli(home, ["run", "glm", "hello"], path_prefix=bin_dir)

            self.assertEqual(result.returncode, 0, result.stderr)
            for line in NOISE_LINES:
                self.assertIn(line, result.stderr)

    def test_run_stderr_filter_kill_switch(self):
        with TemporaryDirectory() as temp, MockAnthropicProvider() as provider:
            home = Path(temp)
            bin_dir = home / "fake-bin"
            bin_dir.mkdir()
            self.add_provider(home, provider, bin_dir)

            result = self.run_cli(
                home,
                ["run", "glm", "-p", "hello"],
                path_prefix=bin_dir,
                extra_env={"CLAUDE_ENV_NO_STDERR_FILTER": "1"},
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            for line in NOISE_LINES:
                self.assertIn(line, result.stderr)

    def test_run_sets_enable_claudeai_mcp_servers(self):
        with TemporaryDirectory() as temp, MockAnthropicProvider() as provider:
            home = Path(temp)
            bin_dir = home / "fake-bin"
            bin_dir.mkdir()
            self.add_provider(home, provider, bin_dir)

            result = self.run_cli(home, ["run", "glm", "-p", "hello"], path_prefix=bin_dir)

            self.assertEqual(result.returncode, 0, result.stderr)
            process_env = json.loads((bin_dir / "claude_process_env.txt").read_text())
            self.assertEqual(process_env["ENABLE_CLAUDEAI_MCP_SERVERS"], "0")

    def test_run_keeps_explicit_enable_claudeai_mcp_servers(self):
        with TemporaryDirectory() as temp, MockAnthropicProvider() as provider:
            home = Path(temp)
            bin_dir = home / "fake-bin"
            bin_dir.mkdir()
            self.add_provider(home, provider, bin_dir)

            result = self.run_cli(
                home,
                ["run", "glm", "-p", "hello"],
                path_prefix=bin_dir,
                extra_env={"ENABLE_CLAUDEAI_MCP_SERVERS": "1"},
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            process_env = json.loads((bin_dir / "claude_process_env.txt").read_text())
            self.assertEqual(process_env["ENABLE_CLAUDEAI_MCP_SERVERS"], "1")

    def test_run_forwards_nonzero_exit_code_in_print_mode(self):
        with TemporaryDirectory() as temp, MockAnthropicProvider() as provider:
            home = Path(temp)
            bin_dir = home / "fake-bin"
            bin_dir.mkdir()
            self.add_provider(home, provider, bin_dir)

            result = self.run_cli(
                home,
                ["run", "glm", "-p", "hello"],
                path_prefix=bin_dir,
                extra_env={"FAKE_CLAUDE_EXIT": "7"},
            )

            self.assertEqual(result.returncode, 7, result.stderr)

    def test_run_returns_128_plus_signal_when_child_is_killed(self):
        if os.name == "nt":
            self.skipTest("POSIX signal exit codes only")
        with TemporaryDirectory() as temp, MockAnthropicProvider() as provider:
            home = Path(temp)
            bin_dir = home / "fake-bin"
            bin_dir.mkdir()
            self.add_provider(home, provider, bin_dir)

            result = self.run_cli(
                home,
                ["run", "glm", "-p", "hello"],
                path_prefix=bin_dir,
                extra_env={"FAKE_CLAUDE_SIGNAL": "15"},
            )

            self.assertEqual(result.returncode, 143, result.stderr)

    def test_run_forwards_sigterm_and_reaps_child(self):
        if os.name == "nt":
            self.skipTest("POSIX signal semantics only")
        with TemporaryDirectory() as temp:
            home = Path(temp)
            bin_dir = home / "fake-bin"
            bin_dir.mkdir()
            write_fake_claude(bin_dir)
            add = self.run_cli(
                home,
                [
                    "add", "glm",
                    "--url", "http://127.0.0.1:1/v1",
                    "--token", "test-token",
                    "--model", "fake-model",
                    "-y",
                ],
                path_prefix=bin_dir,
            )
            self.assertEqual(add.returncode, 0, add.stderr)

            process = subprocess.Popen(
                [sys.executable, "-m", "claude_env", "run", "glm", "-p", "hello"],
                cwd=Path(__file__).resolve().parents[1],
                env=self.cli_env(
                    home, path_prefix=bin_dir, extra_env={"FAKE_CLAUDE_SLEEP": "30"}
                ),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            pid_file = bin_dir / "claude_pid.txt"
            deadline = time.time() + 10
            while not pid_file.exists() and time.time() < deadline:
                time.sleep(0.05)
            self.assertTrue(pid_file.exists(), "fake claude did not start")
            child_pid = int(pid_file.read_text())

            process.send_signal(signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=15)

            self.assertEqual(process.returncode, 143, stderr)
            deadline = time.time() + 5
            while time.time() < deadline:
                try:
                    os.kill(child_pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.05)
            else:
                self.fail("claude child survived after claude-env was terminated")

    def test_run_filter_handles_stderr_flood(self):
        with TemporaryDirectory() as temp, MockAnthropicProvider() as provider:
            home = Path(temp)
            bin_dir = home / "fake-bin"
            bin_dir.mkdir()
            self.add_provider(home, provider, bin_dir)

            result = self.run_cli(
                home,
                ["run", "glm", "-p", "hello"],
                path_prefix=bin_dir,
                extra_env={"FAKE_CLAUDE_STDERR_FLOOD": "1"},
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(REAL_STDERR_LINE, result.stderr)
            self.assertNotIn("[claude-code:unrecognized_model] flood", result.stderr)

    def test_run_prints_clear_error_when_claude_is_missing(self):
        with TemporaryDirectory() as temp, MockAnthropicProvider() as provider:
            home = Path(temp)
            empty_path = home / "empty-path"
            empty_path.mkdir()
            add = self.run_cli(
                home,
                [
                    "add",
                    "glm",
                    "--url",
                    provider.url,
                    "--token",
                    "test-token",
                    "--model",
                    "glm-5-turbo",
                    "-y",
                ],
                path_prefix=empty_path,
            )
            self.assertEqual(add.returncode, 0, add.stderr)

            env = os.environ.copy()
            env.pop("CLAUDE_ENV_EXECUTABLE", None)
            env.update(
                {
                    "CLAUDE_ENV_HOME": str(home),
                    "CLAUDE_ENV_BIN_DIR": str(home / ".local" / "bin"),
                    "CLAUDE_ENV_CONFIG_DIR": str(home / ".config" / "claude-env"),
                    # keep PATH fully hermetic so claude is not found anywhere
                    "PATH": str(empty_path),
                    "PYTHONDONTWRITEBYTECODE": "1",
                }
            )
            result = subprocess.run(
                [sys.executable, "-m", "claude_env", "run", "glm", "-p", "hello"],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding="utf-8",
            )

            self.assertEqual(result.returncode, 127, result.stderr)
            self.assertIn("not found", result.stderr)
            self.assertIn("claude", result.stderr)
            self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
