from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App configuration, read from environment variables or the .env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: PostgresDsn
    # The user's timezone, used to resolve dates like "today" or "this month".
    timezone: ZoneInfo = ZoneInfo("UTC")


@lru_cache
def get_settings() -> Settings:
    return Settings()
