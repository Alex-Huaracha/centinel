from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from centinel.config import get_settings
from centinel.db.models import Base, Category


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    # Never fall back to DATABASE_URL: the tests drop every table.
    url = get_settings().test_database_url
    if url is None:
        pytest.exit("Set TEST_DATABASE_URL, see .env.example.", returncode=1)
    engine = create_engine(str(url))
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
