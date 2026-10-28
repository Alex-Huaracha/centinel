from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import Field, HttpUrl, PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App configuration, read from environment variables or the .env file."""

    # env_ignore_empty: a variable left empty, as in .env.example, means unset.
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", env_ignore_empty=True
    )

    database_url: PostgresDsn
    # The user's timezone, used to resolve dates like "today" or "this month".
    timezone: ZoneInfo = ZoneInfo("UTC")
    # Apps Script web app that reads Gmail (see apps_script/). Unset = no email intake.
    gmail_script_url: HttpUrl | None = None
    gmail_script_secret: SecretStr | None = None
    # How many days back each email search looks.
    email_lookback_days: int = Field(default=30, ge=1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
