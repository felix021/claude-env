import contextlib
import io
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from claude_env.cli import main
from claude_env import __version__
from claude_env.cli import main, migrate_storage_v1_to_v2


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
            suffix = ".cmd" if os.name == "nt" else ""
            wrapper = wrapper.parent / f"{wrapper.name}{suffix}"
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
                input_text="https://provider.example/v1\nprompt-token\n\n",
            )

            self.assertEqual(code, 0, stderr)
            suffix = ".cmd" if os.name == "nt" else ""
            wrapper = home / ".local" / "bin" / f"claude-qwen{suffix}"
            content = "" if wrapper.is_symlink() else wrapper.read_text(encoding="utf-8")
            self.assertNotIn("https://provider.example/v1", content)
            self.assertNotIn("prompt-token", content)
            self.assertNotIn("prompt-token", stdout)

            code, stdout, stderr = self.run_cli(["list"], home=home)
            self.assertEqual(code, 0, stderr)
            self.assertIn("qwen", stdout)
            self.assertIn("\t-\t", stdout)

    def test_add_prompts_for_missing_default_model(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)

            code, stdout, stderr = self.run_cli(
                ["add", "qwen", "--url", "https://provider.example/v1", "--token", "token", "-y"],
                home=home,
                input_text="qwen3.6-plus\n",
            )

            self.assertEqual(code, 0, stderr)
            code, stdout, stderr = self.run_cli(["list"], home=home)
            self.assertEqual(code, 0, stderr)
            self.assertIn("qwen3.6-plus", stdout)

    def test_add_refuses_overwrite_without_confirmation(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)
            self.run_cli(
                ["add", "glm", "--url", "https://one.example", "--token", "one", "-y"],
                home=home,
                input_text="\n",
            )

            code, stdout, stderr = self.run_cli(
                ["add", "glm", "--url", "https://two.example", "--token", "two"],
                home=home,
                input_text="\nn\n",
            )

            self.assertEqual(code, 1)
            self.assertIn("not overwritten", stderr)

    def test_remove_deletes_managed_wrapper_and_alias_works(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)
            self.run_cli(
                ["add", "glm", "--url", "https://provider.example", "--token", "token", "-y"],
                home=home,
                input_text="\n",
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
            suffix = ".cmd" if os.name == "nt" else ""
            wrapper = bin_dir / f"claude-glm{suffix}"
            wrapper.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

            code, stdout, stderr = self.run_cli(["remove", "glm", "-y"], home=home)

            self.assertEqual(code, 1)
            self.assertTrue(wrapper.exists())
            self.assertIn("not managed", stderr)

    def test_add_creates_cmd_shortcut_on_windows(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)

            env = {
                "CLAUDE_ENV_HOME": str(home),
                "CLAUDE_ENV_BIN_DIR": str(home / ".local" / "bin"),
                "CLAUDE_ENV_CONFIG_DIR": str(home / ".config" / "claude-env"),
                "CLAUDE_ENV_PLATFORM": "windows",
            }
            stdout = io.StringIO()
            stderr = io.StringIO()
            stdin = io.StringIO("\n")
            # Delete CLAUDE_ENV_EXECUTABLE so symlink branch is skipped
            with mock.patch.dict(os.environ, env, clear=False):
                os.environ.pop("CLAUDE_ENV_EXECUTABLE", None)
                with mock.patch("sys.stdin", stdin):
                    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                        code = main([
                            "add",
                            "glm",
                            "--url",
                            "https://provider.example/v1",
                            "--token",
                            "super-secret-token",
                            "--model",
                            "glm-5-turbo",
                            "-y",
                        ])

            self.assertEqual(code, 0, stderr)
            shortcut = home / ".local" / "bin" / "claude-glm.cmd"
            self.assertTrue(shortcut.exists())
            content = shortcut.read_text(encoding="utf-8")
            self.assertIn("claude-env.cmd\" run glm %*", content)
            self.assertIn("%errorlevel%", content)
            self.assertNotIn("%%errorlevel%%", content)
            self.assertIn("%~dp0", content)
            self.assertNotIn("%%~dp0", content)
            self.assertNotIn("super-secret-token", content)

    def test_version_prints_version(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)

            code, stdout, stderr = self.run_cli(["version"], home=home)

            self.assertEqual(code, 0, stderr)
            self.assertEqual(stdout.strip(), __version__)

    def test_add_creates_settings_file_with_0600_permissions(self):
        import stat
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
            )

            self.assertEqual(code, 0, stderr)
            config_dir = home / ".config" / "claude-env"
            settings_file = config_dir / "env" / "settings.glm.json"
            self.assertTrue(settings_file.exists())
            content = json.loads(settings_file.read_text(encoding="utf-8"))
            self.assertEqual(content["env"]["ANTHROPIC_BASE_URL"], "https://provider.example/v1")
            self.assertEqual(content["env"]["ANTHROPIC_AUTH_TOKEN"], "super-secret-token")
            # On Windows, chmod 0o600 doesn't fully restrict permissions (ACLs used instead)
            if os.name == "posix":
                mode = settings_file.stat().st_mode
                self.assertEqual(mode & 0o777, 0o600)

    def test_remove_deletes_settings_file(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)

            self.run_cli(
                ["add", "glm", "--url", "https://provider.example", "--token", "token", "-y"],
                home=home,
                input_text="\n",
            )
            settings_file = home / ".config" / "claude-env" / "env" / "settings.glm.json"
            self.assertTrue(settings_file.exists())

            code, stdout, stderr = self.run_cli(["rm", "glm", "-y"], home=home)

            self.assertEqual(code, 0, stderr)
            self.assertFalse(settings_file.exists())
            self.assertIn("removed", stdout)

    def test_add_yolo_creates_yolo_shortcut(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)

            code, stdout, stderr = self.run_cli(
                [
                    "add", "glm",
                    "--url", "https://provider.example/v1",
                    "--token", "super-secret-token",
                    "--model", "glm-5-turbo",
                    "--yolo", "-y",
                ],
                home=home,
            )

            self.assertEqual(code, 0, stderr)
            suffix = ".cmd" if os.name == "nt" else ""
            main_wrapper = home / ".local" / "bin" / f"claude-glm{suffix}"
            yolo_wrapper = home / ".local" / "bin" / f"claude-glm-yolo{suffix}"
            self.assertTrue(main_wrapper.exists())
            self.assertTrue(yolo_wrapper.exists())
            self.assertIn("created", stdout)

    def test_add_yolo_shortcut_contains_no_credentials(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)

            code, stdout, stderr = self.run_cli(
                [
                    "add", "glm",
                    "--url", "https://provider.example/v1",
                    "--token", "super-secret-token",
                    "--yolo", "-y",
                ],
                home=home,
                input_text="\n",
            )

            self.assertEqual(code, 0, stderr)
            suffix = ".cmd" if os.name == "nt" else ""
            yolo_wrapper = home / ".local" / "bin" / f"claude-glm-yolo{suffix}"
            content = "" if yolo_wrapper.is_symlink() else yolo_wrapper.read_text(encoding="utf-8")
            self.assertNotIn("https://provider.example/v1", content)
            self.assertNotIn("super-secret-token", content)

    def test_add_without_yolo_does_not_create_yolo_shortcut(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)

            code, stdout, stderr = self.run_cli(
                [
                    "add", "glm",
                    "--url", "https://provider.example/v1",
                    "--token", "token", "-y",
                ],
                home=home,
                input_text="\n",
            )

            self.assertEqual(code, 0, stderr)
            suffix = ".cmd" if os.name == "nt" else ""
            yolo_wrapper = home / ".local" / "bin" / f"claude-glm-yolo{suffix}"
            self.assertFalse(yolo_wrapper.exists())

    def test_add_yolo_creates_yolo_shortcut_for_existing_provider(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)

            # First add a provider without yolo
            self.run_cli(
                [
                    "add", "glm",
                    "--url", "https://provider.example/v1",
                    "--token", "token", "-y",
                ],
                home=home,
                input_text="\n",
            )

            suffix = ".cmd" if os.name == "nt" else ""
            yolo_wrapper = home / ".local" / "bin" / f"claude-glm-yolo{suffix}"
            self.assertFalse(yolo_wrapper.exists())

            # Now add yolo shortcut for existing provider
            code, stdout, stderr = self.run_cli(
                ["add-yolo", "glm"],
                home=home,
            )

            self.assertEqual(code, 0, stderr)
            self.assertTrue(yolo_wrapper.exists())
            self.assertIn("created", stdout)

    def test_add_yolo_fails_for_nonexistent_provider(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)

            code, stdout, stderr = self.run_cli(
                ["add-yolo", "nonexistent"],
                home=home,
            )

            self.assertEqual(code, 1, stderr)
            self.assertIn("not configured", stderr)

    def test_migrate_v1_to_v2(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)
            config_dir = home / ".config" / "claude-env"
            config_dir.mkdir(parents=True)
            # Write v1 providers.json with url/token
            (config_dir / "providers.json").write_text(
                json.dumps({
                    "version": 1,
                    "providers": {
                        "glm": {
                            "base_url": "https://provider.example/v1",
                            "token": "secret-token",
                            "default_model": "glm-5-turbo",
                            "wrapper_path": "/tmp/claude-glm",
                        }
                    }
                }),
                encoding="utf-8",
            )

            rc = migrate_storage_v1_to_v2(config_dir)

            self.assertEqual(rc, 0)
            # providers.json should be v2 without url/token
            data = json.loads((config_dir / "providers.json").read_text())
            self.assertEqual(data["version"], 2)
            self.assertNotIn("base_url", data["providers"]["glm"])
            self.assertNotIn("token", data["providers"]["glm"])
            self.assertEqual(data["providers"]["glm"]["default_model"], "glm-5-turbo")
            # env/settings file should exist with creds
            settings_file = config_dir / "env" / "settings.glm.json"
            self.assertTrue(settings_file.exists())
            settings = json.loads(settings_file.read_text())
            self.assertEqual(settings["env"]["ANTHROPIC_BASE_URL"], "https://provider.example/v1")
            self.assertEqual(settings["env"]["ANTHROPIC_AUTH_TOKEN"], "secret-token")

    def test_migrate_v2_is_noop(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)
            config_dir = home / ".config" / "claude-env"
            config_dir.mkdir(parents=True)
            (config_dir / "providers.json").write_text(
                json.dumps({
                    "version": 2,
                    "providers": {
                        "glm": {
                            "default_model": "glm-5-turbo",
                            "wrapper_path": "/tmp/claude-glm",
                        }
                    }
                }),
                encoding="utf-8",
            )

            rc = migrate_storage_v1_to_v2(config_dir)

            self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
