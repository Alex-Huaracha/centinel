from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from centinel.config import get_settings

# libpq options. Without connect_timeout a connection that never answers waits
# forever, and the tool call hangs with it. Keepalives notice a connection
# whose network dropped without closing it.
CONNECT_ARGS = {
    "connect_timeout": 10,
    "keepalives": 1,
    "keepalives_idle": 30,
    "keepalives_interval": 10,
    "keepalives_count": 3,
}


def create_db_engine() -> Engine:
    # Ping each pooled connection before use: the server may have closed it,
    # e.g. Neon suspends an idle database after a few minutes.
    return create_engine(
        str(get_settings().database_url),
        pool_pre_ping=True,
        connect_args=CONNECT_ARGS,
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine)
