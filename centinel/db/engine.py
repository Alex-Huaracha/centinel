from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from centinel.config import get_settings


def create_db_engine() -> Engine:
    # Ping each pooled connection before use: the server may have closed it,
    # e.g. Neon suspends an idle database after a few minutes.
    return create_engine(str(get_settings().database_url), pool_pre_ping=True)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine)
