"""
config.py — centralised settings loaded from .env
All secrets live here. Never import os.getenv() directly elsewhere.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Telegram ──────────────────────────────────────────────────────────────
    telegram_bot_token: str
    telegram_webhook_url: str = ""
    telegram_allowed_users: list[int] = []

    @field_validator("telegram_allowed_users", mode="before")
    @classmethod
    def parse_allowed_users(cls, v):
        if isinstance(v, str):
            return [int(uid.strip()) for uid in v.split(",") if uid.strip()]
        return v

    # ── LLMs ──────────────────────────────────────────────────────────────────
    deepseek_api_key: str
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    openai_api_key: str
    openai_model: str = "gpt-4o-mini"

    # ── Search ────────────────────────────────────────────────────────────────
    tavily_api_key: str

    # ── Gmail ─────────────────────────────────────────────────────────────────
    gmail_credentials_path: str = "./secrets/gmail_credentials.json"
    gmail_token_path: str = "./secrets/gmail_token.json"

    # ── LinkedIn ──────────────────────────────────────────────────────────────
    linkedin_li_at_cookie: str = ""
    linkedin_client_id: str = ""
    linkedin_client_secret: str = ""
    linkedin_access_token: str = ""

    # ── Google Sheets ─────────────────────────────────────────────────────────
    google_sheet_id: str = ""

    # ── App ───────────────────────────────────────────────────────────────────
    app_env: str = "development"
    log_level: str = "INFO"
    max_retries: int = 3
    retry_delay_seconds: int = 5
    screenshot_save_path: str = "./screenshots"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings instance. Call this everywhere."""
    return Settings()
