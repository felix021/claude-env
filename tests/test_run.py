import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.mock_provider import MockAnthropicProvider


def write_fake_claude(bin_dir: Path) -> None:
    fake = bin_dir / "claude"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys, urllib.request\n"
        "args = sys.argv[1:]\n"
        "model = None\n"
        "prompt = ''\n"
        "i = 0\n"
        "while i < len(args):\n"
        "    arg = args[i]\n"
        "    if arg == '--model':\n"
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
        "body = json.dumps({'model': model, 'messages': [{'role': 'user', 'content': prompt}]}).encode()\n"
        "req = urllib.request.Request(\n"
        "    os.environ['ANTHROPIC_BASE_URL'],\n"
        "    data=body,\n"
        "    headers={\n"
        "        'content-type': 'application/json',\n"
        "        'x-api-key': os.environ['ANTHROPIC_AUTH_TOKEN'],\n"
        "    },\n"
        "    method='POST',\n"
        ")\n"
        "with urllib.request.urlopen(req, timeout=10) as response:\n"
        "    data = json.loads(response.read().decode())\n"
        "print(data['content'][0]['text'])\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)


class RunTests(unittest.TestCase):
    def run_cli(self, home: Path, argv: list[str], *, path_prefix: Path) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.update(
            {
                "CLAUDE_ENV_HOME": str(home),
                "CLAUDE_ENV_BIN_DIR": str(home / ".local" / "bin"),
                "CLAUDE_ENV_CONFIG_DIR": str(home / ".config" / "claude-env"),
                "PATH": f"{path_prefix}:{env['PATH']}",
                "PYTHONDONTWRITEBYTECODE": "1",
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
            if shortcut.is_symlink():
                shortcut_text = ""
            else:
                shortcut_text = shortcut.read_text(encoding="utf-8")
            self.assertNotIn(provider.url, shortcut_text)
            self.assertNotIn("test-token", shortcut_text)

            env = os.environ.copy()
            env.update(
                {
                    "CLAUDE_ENV_HOME": str(home),
                    "CLAUDE_ENV_BIN_DIR": str(home / ".local" / "bin"),
                    "CLAUDE_ENV_CONFIG_DIR": str(home / ".config" / "claude-env"),
                    "PATH": f"{fake_bin}:{home / '.local' / 'bin'}:{env['PATH']}",
                    "PYTHONDONTWRITEBYTECODE": "1",
                }
            )
            result = subprocess.run(
                [str(shortcut), "-p", "hello"],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "OK")

    def test_run_refuses_when_claude_settings_env_overrides_provider_env(self):
        with TemporaryDirectory() as temp, MockAnthropicProvider() as provider:
            home = Path(temp)
            bin_dir = home / "fake-bin"
            bin_dir.mkdir()
            write_fake_claude(bin_dir)
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

            result = self.run_cli(home, ["run", "glm", "-p", "hello"], path_prefix=bin_dir)

            self.assertEqual(result.returncode, 1)
            self.assertEqual(provider.requests, [])
            self.assertIn("settings.json", result.stderr)
            self.assertIn("ANTHROPIC_BASE_URL", result.stderr)
            self.assertIn("ANTHROPIC_AUTH_TOKEN", result.stderr)
            self.assertNotIn("wrong-token", result.stderr)
            self.assertNotIn("test-token", result.stderr)

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


if __name__ == "__main__":
    unittest.main()
