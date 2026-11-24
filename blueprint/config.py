"""Runtime settings, read from environment variables (or a local .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent


_DEFAULT_MODELS = {
    "anthropic": {"chat": "claude-opus-5-5"},
    "openai": {"chat": "gpt-5-mini"},
}


def _env(name: str) -> str | None:
    return os.getenv(name) or None


@dataclass(frozen=True)
class Settings:
    """All runtime settings, read from environment variables (or .env / Streamlit secrets) with POC defaults."""
    # "anthropic" (Claude, default) or "openai". Claude has no embeddings API, so with
    # Claude the vector index uses a small local embedding model (no key needed).
    llm_provider: str = field(default_factory=lambda: os.getenv("BLUEPRINT_LLM_PROVIDER", "anthropic").lower())
    # BLUEPRINT_ANTHROPIC_API_KEY wins: hosted Claude Code sessions reserve ANTHROPIC_API_KEY
    # and ANTHROPIC_BASE_URL for themselves, so the app's own key needs its own name there.
    anthropic_api_key: str | None = field(
        default_factory=lambda: _env("BLUEPRINT_ANTHROPIC_API_KEY") or _env("ANTHROPIC_API_KEY")
    )
    anthropic_base_url: str = field(
        default_factory=lambda: os.getenv("BLUEPRINT_ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    )
    openai_api_key: str | None = field(default_factory=lambda: _env("OPENAI_API_KEY"))
    extraction_model: str | None = field(default_factory=lambda: _env("BLUEPRINT_EXTRACTION_MODEL"))
    agent_model: str | None = field(default_factory=lambda: _env("BLUEPRINT_AGENT_MODEL"))
    chat_model: str | None = field(default_factory=lambda: _env("BLUEPRINT_CHAT_MODEL"))
    # "local" (default with Claude) or "openai" (default with OpenAI).
    embeddings: str | None = field(default_factory=lambda: _env("BLUEPRINT_EMBEDDINGS"))
    embedding_model: str = field(
        default_factory=lambda: os.getenv("BLUEPRINT_EMBEDDING_MODEL", "text-embedding-3-small")
    )
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("BLUEPRINT_DATA_DIR", ROOT / "storage")))
    # Overrun allowed on recurring tasks before an interval is "beyond tolerance" (provisional 10%).
    tolerance: float = field(default_factory=lambda: float(os.getenv("BLUEPRINT_TOLERANCE", "0.10")))
    vector_backend: str = field(default_factory=lambda: os.getenv("BLUEPRINT_VECTOR_BACKEND", "chroma"))

    def __post_init__(self):
        if self.llm_provider not in _DEFAULT_MODELS:
            raise ValueError(f"BLUEPRINT_LLM_PROVIDER must be one of {sorted(_DEFAULT_MODELS)}")
        default = _DEFAULT_MODELS[self.llm_provider]["chat"]
        for name in ("extraction_model", "agent_model", "chat_model"):
            if not getattr(self, name):
                object.__setattr__(self, name, default)
        if not self.embeddings:
            object.__setattr__(self, "embeddings", "openai" if self.llm_provider == "openai" else "local")

    @property
    def sqlite_path(self) -> Path:
        """SQLite database file for structured data."""
        return self.data_dir / "blueprint.db"

    @property
    def chroma_path(self) -> Path:
        """Folder for the Chroma vector index."""
        return self.data_dir / "chroma"


def get_settings() -> Settings:
    """Return a fresh Settings object built from the current environment."""
    return Settings()
