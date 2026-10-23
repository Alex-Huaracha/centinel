import os

from sqlalchemy import Engine, create_engine


def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set. Copy .env.example to .env.")
    return url


def create_db_engine() -> Engine:
    return create_engine(get_database_url())
