from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    discord_token: str
    database_path: Path
    lm_studio_base_url: str
    embedding_model_id: str
    lm_studio_api_key: str
    embedding_min_similarity: float


def load_settings() -> Settings:
    load_dotenv()
    minimum_similarity = float(os.environ.get("EMBEDDING_MIN_SIMILARITY", "0.45"))
    if not 0.0 <= minimum_similarity <= 1.0:
        raise ValueError("EMBEDDING_MIN_SIMILARITY must be between 0 and 1")
    return Settings(
        discord_token=os.environ.get("DISCORD_BOT_TOKEN", "").strip(),
        database_path=Path(os.environ.get("DATABASE_PATH", "data/bot.sqlite3")),
        lm_studio_base_url=os.environ.get(
            "LM_STUDIO_BASE_URL", "http://127.0.0.1:1234/v1"
        ).strip(),
        embedding_model_id=os.environ.get(
            "LM_STUDIO_EMBEDDING_MODEL", "text-embedding-embeddinggemma-300m-qat"
        ).strip(),
        lm_studio_api_key=os.environ.get("LM_STUDIO_API_KEY", "lm-studio").strip(),
        embedding_min_similarity=minimum_similarity,
    )
