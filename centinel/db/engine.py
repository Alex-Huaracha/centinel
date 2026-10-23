from sqlalchemy import Engine, create_engine

from centinel.config import get_settings


def create_db_engine() -> Engine:
    return create_engine(str(get_settings().database_url))
