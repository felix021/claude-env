import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReadmeTests(unittest.TestCase):
    def test_readmes_exist_and_link_each_other(self):
        zh = ROOT / "README.md"
        en = ROOT / "README.en.md"

        self.assertTrue(zh.exists())
        self.assertTrue(en.exists())
        self.assertIn("README.en.md", zh.read_text(encoding="utf-8"))
        self.assertIn("README.md", en.read_text(encoding="utf-8"))

    def test_readmes_include_ai_agent_install_section(self):
        zh = (ROOT / "README.md").read_text(encoding="utf-8")
        en = (ROOT / "README.en.md").read_text(encoding="utf-8")

        self.assertIn("AI Agent", zh)
        self.assertIn("AI Agents", en)
        self.assertIn("raw.githubusercontent.com/felix021/claude-env/main/install.sh", zh)
        self.assertIn("raw.githubusercontent.com/felix021/claude-env/main/install.sh", en)
        self.assertIn("raw.githubusercontent.com/felix021/claude-env/main/install.ps1", zh)
        self.assertIn("raw.githubusercontent.com/felix021/claude-env/main/install.ps1", en)

    def test_installers_default_to_public_repository(self):
        install_sh = (ROOT / "install.sh").read_text(encoding="utf-8")
        install_ps1 = (ROOT / "install.ps1").read_text(encoding="utf-8")

        self.assertIn("github.com/felix021/claude-env", install_sh)
        self.assertIn("github.com/felix021/claude-env", install_ps1)
        self.assertNotIn("<owner>", install_sh)
        self.assertNotIn("<owner>", install_ps1)


if __name__ == "__main__":
    unittest.main()
