import contextlib
import io
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from claude_env.cli import main


class CliTests(unittest.TestCase):
    def run_cli(self, argv, *, home: Path, input_text: str = "", extra_env: dict | None = None):
        stdout = io.StringIO()
        stderr = io.StringIO()
        stdin = io.StringIO(input_text)
        env = {
            "CLAUDE_ENV_HOME": str(home),
            "CLAUDE_ENV_BIN_DIR": str(home / ".local" / "bin"),
            "CLAUDE_ENV_CONFIG_DIR": str(home / ".config" / "claude-env"),
        }
        if extra_env:
            env.update(extra_env)
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch("sys.stdin", stdin):
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    code = main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_add_creates_wrapper_and_list_redacts_token(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)

            code, stdout, stderr = self.run_cli(
                [
                    "add",
                    "glm",
                    "--url",
                    "https://provider.example/v1",
                    "--token",
                    "super-secret-token",
                    "--model",
                    "glm-5.1",
                    "-y",
                ],
                home=home,
            )

            self.assertEqual(code, 0, stderr)
            wrapper = home / ".local" / "bin" / "claude-glm"
            self.assertTrue(wrapper.exists())
            if wrapper.is_symlink():
                wrapper_content = ""
            else:
                wrapper_content = wrapper.read_text(encoding="utf-8")
            self.assertNotIn("https://provider.example/v1", wrapper_content)
            self.assertNotIn("super-secret-token", wrapper_content)
            self.assertIn("created", stdout)

            code, stdout, stderr = self.run_cli(["list"], home=home)

            self.assertEqual(code, 0, stderr)
            self.assertIn("glm", stdout)
            self.assertIn("https://provider.example/v1", stdout)
            self.assertIn("glm-5.1", stdout)
            self.assertNotIn("super-secret-token", stdout)
            self.assertIn("***", stdout)

    def test_add_prompts_for_missing_url_and_token(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)

            code, stdout, stderr = self.run_cli(
                ["add", "qwen", "-y"],
                home=home,
                input_text="https://provider.example/v1\nprompt-token\n",
            )

            self.assertEqual(code, 0, stderr)
            wrapper = home / ".local" / "bin" / "claude-qwen"
            content = "" if wrapper.is_symlink() else wrapper.read_text(encoding="utf-8")
            self.assertNotIn("https://provider.example/v1", content)
            self.assertNotIn("prompt-token", content)
            self.assertNotIn("prompt-token", stdout)

    def test_add_refuses_overwrite_without_confirmation(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)
            self.run_cli(
                ["add", "glm", "--url", "https://one.example", "--token", "one", "-y"],
                home=home,
            )

            code, stdout, stderr = self.run_cli(
                ["add", "glm", "--url", "https://two.example", "--token", "two"],
                home=home,
                input_text="n\n",
            )

            self.assertEqual(code, 1)
            self.assertIn("not overwritten", stderr)

    def test_remove_deletes_managed_wrapper_and_alias_works(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)
            self.run_cli(
                ["add", "glm", "--url", "https://provider.example", "--token", "token", "-y"],
                home=home,
            )

            code, stdout, stderr = self.run_cli(["rm", "glm", "-y"], home=home)

            self.assertEqual(code, 0, stderr)
            self.assertFalse((home / ".local" / "bin" / "claude-glm").exists())
            self.assertIn("removed", stdout)

            code, stdout, stderr = self.run_cli(["list"], home=home)
            self.assertEqual(code, 0, stderr)
            self.assertIn("No providers", stdout)

    def test_remove_refuses_unmanaged_file(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)
            bin_dir = home / ".local" / "bin"
            bin_dir.mkdir(parents=True)
            wrapper = bin_dir / "claude-glm"
            wrapper.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

            code, stdout, stderr = self.run_cli(["remove", "glm", "-y"], home=home)

            self.assertEqual(code, 1)
            self.assertTrue(wrapper.exists())
            self.assertIn("not managed", stderr)

    def test_add_creates_cmd_shortcut_on_windows(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)

            code, stdout, stderr = self.run_cli(
                [
                    "add",
                    "glm",
                    "--url",
                    "https://provider.example/v1",
                    "--token",
                    "super-secret-token",
                    "--model",
                    "glm-5-turbo",
                    "-y",
                ],
                home=home,
                extra_env={"CLAUDE_ENV_PLATFORM": "windows"},
            )

            self.assertEqual(code, 0, stderr)
            shortcut = home / ".local" / "bin" / "claude-glm.cmd"
            self.assertTrue(shortcut.exists())
            content = shortcut.read_text(encoding="utf-8")
            self.assertIn("claude-env.cmd\" run glm %*", content)
            self.assertNotIn("super-secret-token", content)


if __name__ == "__main__":
    unittest.main()
