import unittest

from claude_env.wrapper import validate_provider_name


class WrapperTests(unittest.TestCase):
    def test_validate_provider_name_accepts_safe_names(self):
        for name in ["glm", "qwen3", "provider-name", "provider_name"]:
            with self.subTest(name=name):
                self.assertEqual(validate_provider_name(name), name)

    def test_validate_provider_name_rejects_unsafe_names(self):
        for name in ["", "../x", "x y", "x/y", "-bad", "bad$", ".hidden"]:
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    validate_provider_name(name)


if __name__ == "__main__":
    unittest.main()
