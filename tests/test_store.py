import json
import stat
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from claude_env.store import Provider, Store


class StoreTests(unittest.TestCase):
    def test_save_load_list_and_remove_provider(self):
        with TemporaryDirectory() as temp:
            config_dir = Path(temp) / "config"
            store = Store(config_dir=config_dir)
            provider = Provider(
                name="glm",
                base_url="https://provider.example/v1",
                token="token",
                default_model="glm-5.1",
                wrapper_path="/tmp/bin/claude-glm",
            )

            store.save_provider(provider)

            loaded = Store(config_dir=config_dir)
            self.assertEqual(loaded.get_provider("glm"), provider)
            self.assertEqual(loaded.list_providers(), [provider])

            loaded.remove_provider("glm")

            self.assertIsNone(loaded.get_provider("glm"))
            data = json.loads((config_dir / "providers.json").read_text(encoding="utf-8"))
            self.assertEqual(data["providers"], {})

    def test_metadata_file_is_owner_readable_only(self):
        with TemporaryDirectory() as temp:
            config_dir = Path(temp) / "config"
            store = Store(config_dir=config_dir)

            store.save_provider(
                Provider(
                    name="qwen",
                    base_url="https://provider.example/v1",
                    token="token",
                    default_model=None,
                    wrapper_path="/tmp/bin/claude-qwen",
                )
            )

            mode = stat.S_IMODE((config_dir / "providers.json").stat().st_mode)
            self.assertEqual(mode, 0o600)

    def test_loads_metadata_with_utf8_bom(self):
        with TemporaryDirectory() as temp:
            config_dir = Path(temp) / "config"
            config_dir.mkdir()
            (config_dir / "providers.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "providers": {
                            "glm": {
                                "base_url": "https://provider.example",
                                "token": "token",
                                "default_model": "glm-5-turbo",
                                "wrapper_path": "/tmp/claude-glm",
                            }
                        },
                    }
                ),
                encoding="utf-8-sig",
            )

            provider = Store(config_dir=config_dir).get_provider("glm")

            self.assertIsNotNone(provider)
            self.assertEqual(provider.default_model, "glm-5-turbo")


if __name__ == "__main__":
    unittest.main()
