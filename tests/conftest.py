from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from centinel.config import get_settings
from centinel.db.models import Base, Category


def _test_database_url() -> URL:
    # Same server and credentials as the app, but a separate "<name>_test" database.
    url = make_url(str(get_settings().database_url))
    return url.set(database=f"{url.database}_test")


def _create_database_if_missing(url: URL) -> None:
    admin_engine = create_engine(
        url.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    with admin_engine.connect() as connection:
        exists = connection.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": url.database},
        )
        if not exists:
            connection.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin_engine.dispose()


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    url = _test_database_url()
    _create_database_if_missing(url)
    engine = create_engine(url)
    # Fresh schema on every run; migrations are checked separately with `alembic check`.
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> Iterator[sessionmaker[Session]]:
    """Sessions whose changes are rolled back after each test, even if the code commits."""
    with engine.connect() as connection:
        transaction = connection.begin()
        factory = sessionmaker(
            bind=connection, join_transaction_mode="create_savepoint"
        )
        with factory() as session:
            session.add_all(
                [Category(name=name) for name in ("food", "transport", "shopping")]
            )
            session.commit()
        yield factory
        transaction.rollback()


@pytest.fixture
def session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    with session_factory() as session:
        yield session
