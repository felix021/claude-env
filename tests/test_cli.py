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
from claude_env.cli import (
    installer_command,
    installer_url,
    main,
    migrate_storage_v1_to_v2,
    migrate_storage_v2_to_v3,
)


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
        # Drop every inherited claude-env / fake-claude setting so the result
        # does not depend on the developer's shell.
        base = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("CLAUDE_ENV_", "FAKE_CLAUDE_"))
        }
        base.update(env)
        with mock.patch.dict(os.environ, base, clear=True):
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

    def test_settings_file_is_pretty_printed(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)
            self.run_cli(
                ["add", "glm", "--url", "https://provider.example/v1", "--token", "secret", "-y"],
                home=home,
                input_text="\n",
            )
            settings_path = home / ".config" / "claude-env" / "env" / "settings.glm.json"
            raw = settings_path.read_text(encoding="utf-8")
            self.assertTrue(raw.endswith("\n"))
            self.assertIn('\n  "', raw)
            self.assertEqual(json.loads(raw)["env"]["ANTHROPIC_BASE_URL"], "https://provider.example/v1")
            if os.name != "nt":
                self.assertEqual(settings_path.stat().st_mode & 0o777, 0o600)

    def test_update_changes_fields_and_preserves_other_keys(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)
            self.run_cli(
                ["add", "glm", "--url", "https://old.example/v1", "--token", "old-token", "--model", "old-model", "-y"],
                home=home,
            )
            settings_path = home / ".config" / "claude-env" / "env" / "settings.glm.json"
            settings = json.loads(settings_path.read_text())
            settings["env"]["SOME_CUSTOM_KEY"] = "keep-me"
            settings["customTopLevel"] = True
            settings_path.write_text(json.dumps(settings))

            code, stdout, stderr = self.run_cli(
                [
                    "update", "glm",
                    "--url", "https://new.example/v1",
                    "--token", "new-token",
                    "--model", "new-model",
                ],
                home=home,
            )

            self.assertEqual(code, 0, stderr)
            self.assertIn("updated", stdout)
            self.assertNotIn("new-token", stdout)
            updated = json.loads(settings_path.read_text())
            self.assertEqual(updated["env"]["ANTHROPIC_BASE_URL"], "https://new.example/v1")
            self.assertEqual(updated["env"]["ANTHROPIC_AUTH_TOKEN"], "new-token")
            self.assertEqual(updated["env"]["SOME_CUSTOM_KEY"], "keep-me")
            self.assertEqual(updated["model"], "new-model")
            self.assertTrue(updated["customTopLevel"])

            code, stdout, stderr = self.run_cli(["list"], home=home)
            self.assertEqual(code, 0, stderr)
            self.assertIn("https://new.example/v1", stdout)
            self.assertIn("new-model", stdout)
            self.assertNotIn("new-token", stdout)

    def test_update_no_model_clears_default_model(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)
            self.run_cli(
                ["add", "glm", "--url", "https://provider.example/v1", "--token", "token", "--model", "old-model", "-y"],
                home=home,
            )

            code, stdout, stderr = self.run_cli(["update", "glm", "--no-model"], home=home)

            self.assertEqual(code, 0, stderr)
            settings_path = home / ".config" / "claude-env" / "env" / "settings.glm.json"
            self.assertNotIn("model", json.loads(settings_path.read_text()))
            code, stdout, stderr = self.run_cli(["list"], home=home)
            self.assertEqual(code, 0, stderr)
            row = next(line for line in stdout.splitlines() if line.startswith("glm\t"))
            self.assertEqual(row.split("\t")[2], "-")
            self.assertEqual(row.split("\t")[3], "-")

    def test_update_no_model_clears_legacy_default_model(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)
            self.run_cli(
                ["add", "glm", "--url", "https://provider.example/v1", "--token", "token", "-y"],
                home=home,
                input_text="\n",
            )
            config_dir = home / ".config" / "claude-env"
            data = json.loads((config_dir / "providers.json").read_text())
            data["providers"]["glm"]["default_model"] = "legacy-model"
            (config_dir / "providers.json").write_text(json.dumps(data))

            code, stdout, stderr = self.run_cli(["update", "glm", "--no-model"], home=home)

            self.assertEqual(code, 0, stderr)
            data = json.loads((config_dir / "providers.json").read_text())
            self.assertIsNone(data["providers"]["glm"]["default_model"])
            code, stdout, stderr = self.run_cli(["list"], home=home)
            row = next(line for line in stdout.splitlines() if line.startswith("glm\t"))
            self.assertEqual(row.split("\t")[2], "-")

    def test_update_auto_compact_window_and_clear(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)
            self.run_cli(
                ["add", "glm", "--url", "https://provider.example/v1", "--token", "token", "-y"],
                home=home,
                input_text="\n",
            )
            settings_path = home / ".config" / "claude-env" / "env" / "settings.glm.json"

            code, stdout, stderr = self.run_cli(
                ["update", "glm", "--auto-compact-window", "200000"], home=home
            )
            self.assertEqual(code, 0, stderr)
            settings = json.loads(settings_path.read_text())
            self.assertEqual(settings["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"], "200000")

            code, stdout, stderr = self.run_cli(
                ["update", "glm", "--no-auto-compact-window"], home=home
            )
            self.assertEqual(code, 0, stderr)
            settings = json.loads(settings_path.read_text())
            self.assertNotIn("CLAUDE_CODE_AUTO_COMPACT_WINDOW", settings["env"])

    def test_update_requires_at_least_one_option(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)
            self.run_cli(
                ["add", "glm", "--url", "https://provider.example/v1", "--token", "token", "-y"],
                home=home,
                input_text="\n",
            )

            code, stdout, stderr = self.run_cli(["update", "glm"], home=home)

            self.assertEqual(code, 2)
            self.assertIn("nothing to update", stderr)

    def test_update_unknown_provider(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)

            code, stdout, stderr = self.run_cli(
                ["update", "missing", "--model", "m"], home=home
            )

            self.assertEqual(code, 1)
            self.assertIn("not configured", stderr)

    def test_update_rejects_empty_values_and_bad_window(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)
            self.run_cli(
                ["add", "glm", "--url", "https://provider.example/v1", "--token", "token", "-y"],
                home=home,
                input_text="\n",
            )

            for args, message in (
                (["update", "glm", "--url", ""], "--url must not be empty"),
                (["update", "glm", "--token", ""], "--token must not be empty"),
                (["update", "glm", "--model", ""], "--model must not be empty"),
                (["update", "glm", "--auto-compact-window", "0"], "must be a positive integer"),
            ):
                code, stdout, stderr = self.run_cli(args, home=home)
                self.assertEqual(code, 2, args)
                self.assertIn(message, stderr)

    def test_update_model_flags_are_mutually_exclusive(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)
            with self.assertRaises(SystemExit) as raised:
                self.run_cli(["update", "glm", "--model", "m", "--no-model"], home=home)
            self.assertEqual(raised.exception.code, 2)

    def test_update_requires_settings_file(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)
            self.run_cli(
                ["add", "glm", "--url", "https://provider.example/v1", "--token", "token", "-y"],
                home=home,
                input_text="\n",
            )
            (home / ".config" / "claude-env" / "env" / "settings.glm.json").unlink()

            code, stdout, stderr = self.run_cli(["update", "glm", "--model", "m"], home=home)

            self.assertEqual(code, 1)
            self.assertIn("not found", stderr)

    def test_update_accepts_empty_settings_object(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)
            self.run_cli(
                ["add", "glm", "--url", "https://provider.example/v1", "--token", "token", "-y"],
                home=home,
                input_text="\n",
            )
            settings_path = home / ".config" / "claude-env" / "env" / "settings.glm.json"
            settings_path.write_text("{}\n")

            code, stdout, stderr = self.run_cli(
                ["update", "glm", "--model", "new-model"], home=home
            )

            self.assertEqual(code, 0, stderr)
            self.assertEqual(json.loads(settings_path.read_text())["model"], "new-model")

    def test_update_refuses_non_object_env(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)
            self.run_cli(
                ["add", "glm", "--url", "https://provider.example/v1", "--token", "token", "-y"],
                home=home,
                input_text="\n",
            )
            settings_path = home / ".config" / "claude-env" / "env" / "settings.glm.json"
            settings_path.write_text(json.dumps({"env": "broken"}))

            code, stdout, stderr = self.run_cli(
                ["update", "glm", "--model", "m"], home=home
            )

            self.assertEqual(code, 2)
            self.assertIn("env must be an object", stderr)
            self.assertEqual(json.loads(settings_path.read_text())["env"], "broken")

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

    @unittest.skipIf(os.name == "nt", "fake installer is a POSIX shell script")
    def test_upgrade_runs_downloaded_installer_and_reports_new_version(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)
            installer = home / "fake-install.sh"
            installer.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                'app_dir="${CLAUDE_ENV_HOME}/.local/share/claude-env"\n'
                'mkdir -p "${app_dir}/claude_env"\n'
                'printf \'__version__ = "9.9.9"\\n\' > "${app_dir}/claude_env/__init__.py"\n',
                encoding="utf-8",
            )
            (home / ".local" / "share" / "claude-env" / "claude_env").mkdir(parents=True)
            (home / ".local" / "share" / "claude-env" / "claude_env" / "__init__.py").write_text(
                '__version__ = "0.1.0"\n', encoding="utf-8"
            )

            code, stdout, stderr = self.run_cli(
                ["upgrade"],
                home=home,
                extra_env={"CLAUDE_ENV_INSTALLER_URL": installer.as_uri()},
            )

            self.assertEqual(code, 0, stderr)
            self.assertIn("upgraded claude-env 0.1.0 -> 9.9.9", stdout)

    @unittest.skipIf(os.name == "nt", "fake installer is a POSIX shell script")
    def test_upgrade_reports_unchanged_version(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)
            app_dir = home / ".local" / "share" / "claude-env" / "claude_env"
            app_dir.mkdir(parents=True)
            (app_dir / "__init__.py").write_text(
                f'__version__ = "{__version__}"\n', encoding="utf-8"
            )
            installer = home / "fake-install.sh"
            installer.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")

            code, stdout, stderr = self.run_cli(
                ["upgrade"],
                home=home,
                extra_env={"CLAUDE_ENV_INSTALLER_URL": installer.as_uri()},
            )

            self.assertEqual(code, 0, stderr)
            self.assertIn(f"claude-env {__version__} is already installed", stdout)

    @unittest.skipIf(os.name == "nt", "fake installer is a POSIX shell script")
    def test_upgrade_returns_installer_exit_code(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)
            installer = home / "fake-install.sh"
            installer.write_text("#!/usr/bin/env bash\nexit 3\n", encoding="utf-8")

            code, stdout, stderr = self.run_cli(
                ["upgrade"],
                home=home,
                extra_env={"CLAUDE_ENV_INSTALLER_URL": installer.as_uri()},
            )

            self.assertEqual(code, 3)
            self.assertIn("installer exited with status 3", stderr)

    def test_upgrade_reports_download_failure(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)
            missing = home / "missing-install.sh"

            code, stdout, stderr = self.run_cli(
                ["upgrade"],
                home=home,
                extra_env={"CLAUDE_ENV_INSTALLER_URL": missing.as_uri()},
            )

            self.assertEqual(code, 1)
            self.assertIn("failed to download installer", stderr)

    @unittest.skipIf(os.name == "nt", "fake installer is a POSIX shell script")
    def test_upgrade_reports_first_install_and_missing_version(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)

            installer = home / "fake-install.sh"
            installer.write_text(
                "#!/usr/bin/env bash\n"
                'app_dir="${CLAUDE_ENV_HOME}/.local/share/claude-env"\n'
                'mkdir -p "${app_dir}/claude_env"\n'
                'printf \'__version__ = "1.2.3"\\n\' > "${app_dir}/claude_env/__init__.py"\n',
                encoding="utf-8",
            )
            code, stdout, stderr = self.run_cli(
                ["upgrade"],
                home=home,
                extra_env={"CLAUDE_ENV_INSTALLER_URL": installer.as_uri()},
            )
            self.assertEqual(code, 0, stderr)
            self.assertIn("installed claude-env 1.2.3", stdout)

        with TemporaryDirectory() as temp:
            home = Path(temp)
            silent = home / "silent-install.sh"
            silent.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            code, stdout, stderr = self.run_cli(
                ["upgrade"],
                home=home,
                extra_env={"CLAUDE_ENV_INSTALLER_URL": silent.as_uri()},
            )
            self.assertEqual(code, 0, stderr)
            self.assertIn("upgrade finished", stdout)

    @unittest.skipIf(os.name == "nt", "fake installer is a POSIX shell script")
    def test_upgrade_reports_signal_exit_as_128_plus_signal(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)
            installer = home / "killed-install.sh"
            installer.write_text(
                "#!/usr/bin/env bash\nkill -TERM $$\n", encoding="utf-8"
            )

            code, stdout, stderr = self.run_cli(
                ["upgrade"],
                home=home,
                extra_env={"CLAUDE_ENV_INSTALLER_URL": installer.as_uri()},
            )

            self.assertEqual(code, 143)
            self.assertIn("installer exited with status 143", stderr)

    @unittest.skipIf(os.name == "nt", "fake installer is a POSIX shell script")
    def test_upgrade_refuses_downgrade_and_restores_previous_version(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)
            app_dir = home / ".local" / "share" / "claude-env" / "claude_env"
            app_dir.mkdir(parents=True)
            init_file = app_dir / "__init__.py"
            init_file.write_text('__version__ = "2.0.0"\n', encoding="utf-8")
            installer = home / "fake-install.sh"
            installer.write_text(
                "#!/usr/bin/env bash\n"
                'app_dir="${CLAUDE_ENV_HOME}/.local/share/claude-env"\n'
                'printf \'__version__ = "1.0.0"\\n\' > "${app_dir}/claude_env/__init__.py"\n',
                encoding="utf-8",
            )

            code, stdout, stderr = self.run_cli(
                ["upgrade"],
                home=home,
                extra_env={"CLAUDE_ENV_INSTALLER_URL": installer.as_uri()},
            )

            self.assertEqual(code, 1)
            self.assertIn("refusing to downgrade claude-env 2.0.0 -> 1.0.0", stderr)
            self.assertIn("--version 1.0.0", stderr)
            self.assertEqual(init_file.read_text(), '__version__ = "2.0.0"\n')

    @unittest.skipIf(os.name == "nt", "fake installer is a POSIX shell script")
    def test_upgrade_allows_downgrade_with_explicit_version(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)
            app_dir = home / ".local" / "share" / "claude-env" / "claude_env"
            app_dir.mkdir(parents=True)
            (app_dir / "__init__.py").write_text('__version__ = "2.0.0"\n', encoding="utf-8")
            installer = home / "fake-install.sh"
            installer.write_text(
                "#!/usr/bin/env bash\n"
                'app_dir="${CLAUDE_ENV_HOME}/.local/share/claude-env"\n'
                'mkdir -p "${app_dir}/claude_env"\n'
                'printf \'__version__ = "1.0.0"\\n\' > "${app_dir}/claude_env/__init__.py"\n',
                encoding="utf-8",
            )

            code, stdout, stderr = self.run_cli(
                ["upgrade", "--version", "1.0.0"],
                home=home,
                extra_env={"CLAUDE_ENV_INSTALLER_URL": installer.as_uri()},
            )

            self.assertEqual(code, 0, stderr)
            self.assertIn("downgraded claude-env 2.0.0 -> 1.0.0", stdout)
            self.assertNotIn("warning:", stderr)

    @unittest.skipIf(os.name == "nt", "fake installer is a POSIX shell script")
    def test_upgrade_version_sets_archive_url_and_clears_source_overrides(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)
            installer = home / "fake-install.sh"
            installer.write_text(
                "#!/usr/bin/env bash\n"
                'printf "%s\\n%s\\n" "${CLAUDE_ENV_URL:-}" "${CLAUDE_ENV_SOURCE_DIR:-}"'
                ' > "${CLAUDE_ENV_HOME}/installer_env.txt"\n',
                encoding="utf-8",
            )

            code, stdout, stderr = self.run_cli(
                ["upgrade", "--version", "v0.5.0"],
                home=home,
                extra_env={
                    "CLAUDE_ENV_INSTALLER_URL": installer.as_uri(),
                    "CLAUDE_ENV_SOURCE_DIR": "/stale/source",
                },
            )

            self.assertEqual(code, 0, stderr)
            archive_url, source_dir = (
                (home / "installer_env.txt").read_text().splitlines()
            )
            self.assertTrue(archive_url.endswith("/refs/tags/v0.5.0.tar.gz"))
            self.assertEqual(source_dir, "")

    @unittest.skipIf(os.name == "nt", "fake installer is a POSIX shell script")
    def test_upgrade_restores_previous_version_when_installer_fails(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)
            app_dir = home / ".local" / "share" / "claude-env" / "claude_env"
            app_dir.mkdir(parents=True)
            init_file = app_dir / "__init__.py"
            init_file.write_text('__version__ = "2.0.0"\n', encoding="utf-8")
            installer = home / "broken-install.sh"
            installer.write_text(
                "#!/usr/bin/env bash\n"
                'app_dir="${CLAUDE_ENV_HOME}/.local/share/claude-env"\n'
                'printf \'__version__ = "9.9.9"\\n\' > "${app_dir}/claude_env/__init__.py"\n'
                "exit 3\n",
                encoding="utf-8",
            )

            code, stdout, stderr = self.run_cli(
                ["upgrade"],
                home=home,
                extra_env={"CLAUDE_ENV_INSTALLER_URL": installer.as_uri()},
            )

            self.assertEqual(code, 3)
            self.assertIn("installer exited with status 3", stderr)
            self.assertEqual(init_file.read_text(), '__version__ = "2.0.0"\n')

    def test_upgrade_reports_missing_installer_program(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)
            script = home / "install.sh"
            script.write_text("exit 0\n", encoding="utf-8")
            empty_bin = home / "empty-bin"
            empty_bin.mkdir()

            code, stdout, stderr = self.run_cli(
                ["upgrade"],
                home=home,
                extra_env={
                    "CLAUDE_ENV_INSTALLER_URL": script.as_uri(),
                    "PATH": str(empty_bin),
                },
            )

            self.assertEqual(code, 127)
            self.assertIn("failed to run installer", stderr)
            self.assertNotIn("Traceback", stderr)

    def test_installer_url_per_platform(self):
        with mock.patch.dict(
            os.environ,
            {"CLAUDE_ENV_PLATFORM": "windows", "CLAUDE_ENV_INSTALLER_URL": ""},
        ):
            self.assertTrue(installer_url().endswith("install.ps1"))

        with mock.patch.dict(
            os.environ,
            {"CLAUDE_ENV_PLATFORM": "posix", "CLAUDE_ENV_INSTALLER_URL": ""},
        ):
            self.assertTrue(installer_url().endswith("install.sh"))

        with mock.patch.dict(
            os.environ, {"CLAUDE_ENV_INSTALLER_URL": "https://mirror.example/install.sh"}
        ):
            self.assertEqual(installer_url(), "https://mirror.example/install.sh")

    def test_installer_command_per_platform(self):
        with mock.patch.dict(os.environ, {"CLAUDE_ENV_PLATFORM": "posix"}):
            self.assertEqual(
                installer_command(Path("/tmp/install.sh")),
                ["bash", "/tmp/install.sh"],
            )

        with mock.patch.dict(os.environ, {"CLAUDE_ENV_PLATFORM": "windows"}):
            command = installer_command(Path("C:/tmp/install.ps1"))
            self.assertEqual(
                command[:4],
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass"],
            )
            self.assertEqual(command[-2:], ["-File", "C:/tmp/install.ps1"])

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

    def test_add_writes_model_to_settings_file(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)

            code, stdout, stderr = self.run_cli(
                [
                    "add", "glm",
                    "--url", "https://provider.example/v1",
                    "--token", "token",
                    "--model", "glm-5-turbo",
                    "-y",
                ],
                home=home,
            )

            self.assertEqual(code, 0, stderr)
            settings = json.loads(
                (home / ".config" / "claude-env" / "env" / "settings.glm.json").read_text()
            )
            self.assertEqual(settings["model"], "glm-5-turbo")
            data = json.loads((home / ".config" / "claude-env" / "providers.json").read_text())
            self.assertIsNone(data["providers"]["glm"].get("default_model"))

    def test_add_auto_compact_window_to_settings_env(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)

            code, stdout, stderr = self.run_cli(
                [
                    "add", "glm",
                    "--url", "https://provider.example/v1",
                    "--token", "token",
                    "--auto-compact-window", "118784",
                    "-y",
                ],
                home=home,
                input_text="\n",
            )

            self.assertEqual(code, 0, stderr)
            settings = json.loads(
                (home / ".config" / "claude-env" / "env" / "settings.glm.json").read_text()
            )
            self.assertEqual(
                settings["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"], "118784"
            )
            code, stdout, stderr = self.run_cli(["list"], home=home)
            self.assertEqual(code, 0, stderr)
            self.assertIn("118784", stdout)

    def test_add_rejects_non_positive_auto_compact_window(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)

            code, stdout, stderr = self.run_cli(
                [
                    "add", "glm",
                    "--url", "https://provider.example/v1",
                    "--token", "token",
                    "--auto-compact-window", "0",
                    "-y",
                ],
                home=home,
            )

            self.assertEqual(code, 2)
            self.assertIn("auto-compact-window", stderr)
            self.assertFalse(
                (home / ".config" / "claude-env" / "env" / "settings.glm.json").exists()
            )

    def test_migrate_v2_to_v3_moves_model_into_settings(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)
            config_dir = home / ".config" / "claude-env"
            env_dir = config_dir / "env"
            env_dir.mkdir(parents=True)
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
            (env_dir / "settings.glm.json").write_text(
                json.dumps({
                    "env": {
                        "ANTHROPIC_BASE_URL": "https://provider.example/v1",
                        "ANTHROPIC_AUTH_TOKEN": "secret-token",
                    }
                }),
                encoding="utf-8",
            )

            rc = migrate_storage_v2_to_v3(config_dir)

            self.assertEqual(rc, 0)
            data = json.loads((config_dir / "providers.json").read_text())
            self.assertEqual(data["version"], 3)
            self.assertNotIn("default_model", data["providers"]["glm"])
            self.assertEqual(data["providers"]["glm"]["wrapper_path"], "/tmp/claude-glm")
            settings = json.loads((env_dir / "settings.glm.json").read_text())
            self.assertEqual(settings["model"], "glm-5-turbo")
            self.assertEqual(settings["env"]["ANTHROPIC_BASE_URL"], "https://provider.example/v1")
            self.assertEqual(settings["env"]["ANTHROPIC_AUTH_TOKEN"], "secret-token")
            if os.name == "posix":
                mode = (env_dir / "settings.glm.json").stat().st_mode
                self.assertEqual(mode & 0o777, 0o600)

    def test_migrate_v3_is_noop(self):
        with TemporaryDirectory() as temp:
            home = Path(temp)
            config_dir = home / ".config" / "claude-env"
            config_dir.mkdir(parents=True)
            (config_dir / "providers.json").write_text(
                json.dumps({"version": 3, "providers": {}}),
                encoding="utf-8",
            )

            rc = migrate_storage_v2_to_v3(config_dir)

            self.assertEqual(rc, 1)

    def test_migrate_v2_to_v3_keeps_default_model_when_settings_missing(self):
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

            rc = migrate_storage_v2_to_v3(config_dir)

            self.assertEqual(rc, 0)
            data = json.loads((config_dir / "providers.json").read_text())
            # fallback stays readable from providers.json when creds file is gone
            self.assertEqual(data["providers"]["glm"].get("default_model"), "glm-5-turbo")

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
