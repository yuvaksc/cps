"""Centralized settings, loaded from environment / .env (pydantic-settings)."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ── Database (local SQLite) ──
    database_url: str = "sqlite:///./ctmif.db"

    # ── Groq (agents) ──
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

    # ── CT-MIF / replay ──
    artifacts_dir: str = "artifacts"
    replay_dataset_path: str = "data/replay_test.csv.gz"
    replay_default_speed: float = 50.0

    # ── server ──
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    # The dashboard's live component calls the API from a null-origin iframe, so
    # default to "*". Pin to specific origins in production if desired.
    cors_origins: str = "*"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def groq_enabled(self) -> bool:
        return bool(self.groq_api_key)


settings = Settings()
