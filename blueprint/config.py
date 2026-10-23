"""Runtime settings, read from environment variables (or a local .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    openai_api_key: str | None = field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    extraction_model: str = field(default_factory=lambda: os.getenv("BLUEPRINT_EXTRACTION_MODEL", "gpt-5-mini"))
    agent_model: str = field(default_factory=lambda: os.getenv("BLUEPRINT_AGENT_MODEL", "gpt-5-mini"))
    chat_model: str = field(default_factory=lambda: os.getenv("BLUEPRINT_CHAT_MODEL", "gpt-5-mini"))
    embedding_model: str = field(
        default_factory=lambda: os.getenv("BLUEPRINT_EMBEDDING_MODEL", "text-embedding-3-small")
    )
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("BLUEPRINT_DATA_DIR", ROOT / "storage")))
    # Overrun allowed on recurring tasks before an interval is "beyond tolerance" (provisional 10%).
    tolerance: float = field(default_factory=lambda: float(os.getenv("BLUEPRINT_TOLERANCE", "0.10")))
    vector_backend: str = field(default_factory=lambda: os.getenv("BLUEPRINT_VECTOR_BACKEND", "chroma"))

    @property
    def sqlite_path(self) -> Path:
        return self.data_dir / "blueprint.db"

    @property
    def chroma_path(self) -> Path:
        return self.data_dir / "chroma"


def get_settings() -> Settings:
    return Settings()
