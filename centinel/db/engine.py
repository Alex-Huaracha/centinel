from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from centinel.config import get_settings


def create_db_engine() -> Engine:
    return create_engine(str(get_settings().database_url))


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine)
