from __future__ import annotations

import importlib.util
import os
import sys
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class ConfigDotenvTests(unittest.TestCase):
    def load_settings_from_example(self, environment: dict[str, str]):
        root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as directory:
            temp_root = Path(directory)
            shutil.copyfile(root / "config.py", temp_root / "config.py")
            shutil.copyfile(root / ".env.example", temp_root / ".env")
            spec = importlib.util.spec_from_file_location(
                "isolated_config", temp_root / "config.py"
            )
            self.assertIsNotNone(spec)
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            try:
                with patch.dict(os.environ, environment, clear=True):
                    spec.loader.exec_module(module)
                    return module.load_settings()
            finally:
                sys.modules.pop(spec.name, None)

    def test_example_file_populates_application_settings(self) -> None:
        settings = self.load_settings_from_example({})

        self.assertEqual(settings.discord_token, "replace-with-your-discord-bot-token")
        self.assertEqual(settings.database_path, Path("data/bot.sqlite3"))
        self.assertEqual(
            settings.embedding_model_id, "text-embedding-embeddinggemma-300m-qat"
        )
        self.assertEqual(settings.embedding_min_similarity, 0.45)

    def test_process_environment_overrides_dotenv(self) -> None:
        settings = self.load_settings_from_example(
            {"DISCORD_BOT_TOKEN": "from-process-environment"}
        )

        self.assertEqual(settings.discord_token, "from-process-environment")


if __name__ == "__main__":
    unittest.main()
