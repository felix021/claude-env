import os
import stat
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


class InstallTests(unittest.TestCase):
    def test_installer_copies_source_to_local_bin_and_reports_missing_path(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            home.mkdir()
            source = root / "claude-env-source"
            source.write_text("#!/usr/bin/env python3\nprint('hello')\n", encoding="utf-8")
            env = os.environ.copy()
            env.update(
                {
                    "HOME": str(home),
                    "PATH": "/usr/bin:/bin",
                    "CLAUDE_ENV_SOURCE": str(source),
                }
            )

            result = subprocess.run(
                ["bash", "install.sh"],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            target = home / ".local" / "bin" / "claude-env"
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(target.read_text(encoding="utf-8"), source.read_text(encoding="utf-8"))
            self.assertTrue(stat.S_IMODE(target.stat().st_mode) & stat.S_IXUSR)
            self.assertIn("installed", result.stdout)
            self.assertIn("not in PATH", result.stdout)

    def test_installer_from_source_dir_installs_runnable_cli(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            home.mkdir()
            env = os.environ.copy()
            env.update(
                {
                    "HOME": str(home),
                    "PATH": "/usr/bin:/bin",
                    "CLAUDE_ENV_SOURCE_DIR": str(Path(__file__).resolve().parents[1]),
                    "PYTHONDONTWRITEBYTECODE": "1",
                }
            )

            install = subprocess.run(
                ["bash", "install.sh"],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(install.returncode, 0, install.stderr)

            target = home / ".local" / "bin" / "claude-env"
            result = subprocess.run(
                [str(target), "--help"],
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("usage: claude-env", result.stdout)
            self.assertTrue((home / ".local" / "share" / "claude-env" / "claude_env").is_dir())
            self.assertIn(
                "CLAUDE_ENV_EXECUTABLE",
                target.read_text(encoding="utf-8"),
            )

    def test_windows_installer_has_python_check_and_cmd_launcher(self):
        installer = Path(__file__).resolve().parents[1] / "install.ps1"

        self.assertTrue(installer.exists())
        content = installer.read_text(encoding="utf-8")
        self.assertIn("py -3", content)
        self.assertIn("python", content)
        self.assertIn("claude-env.cmd", content)
        self.assertIn("claude_env", content)
        self.assertIn("SetEnvironmentVariable", content)
        self.assertIn("$env:Path = \"$InstallDir;", content)


if __name__ == "__main__":
    unittest.main()
