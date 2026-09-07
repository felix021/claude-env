import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.mock_provider import MockAnthropicProvider


def write_fake_claude(bin_dir: Path) -> Path:
    args_file = bin_dir / "claude_args.txt"
    fake = bin_dir / "claude"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys, urllib.request\n"
        "args = sys.argv[1:]\n"
        "args_file = r'" + str(args_file).replace("\\", "\\\\") + "'\n"
        "with open(args_file, 'w') as f:\n"
        "    f.write(' '.join(args))\n"
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
        "print(data['content'][0]['text'])\n",
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
    def run_cli(self, home: Path, argv: list[str], *, path_prefix: Path) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
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
        return subprocess.run(
            [sys.executable, "-m", "claude_env", *argv],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
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


if __name__ == "__main__":
    unittest.main()
