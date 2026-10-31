"""The eval database, next to the test one on the db-test server.

The pytest tests roll back a transaction after each test, but here the MCP
server runs in another process and commits, so each run starts from a fresh
schema instead.
"""

from sqlalchemy import URL, Engine, create_engine, make_url, text
from sqlalchemy.orm import Session

from centinel.config import get_settings
from centinel.db.models import Base, Category, TrackedSender
from evals.cases import Case

EVAL_DATABASE = "centinel_eval"

# The categories the migrations leave in a new database.
DEFAULT_CATEGORIES = [
    "food",
    "transport",
    "home",
    "health",
    "entertainment",
    "shopping",
    "services",
]


def eval_database_url() -> URL:
    # Never fall back to DATABASE_URL: every run drops every table.
    url = get_settings().test_database_url
    if url is None:
        raise SystemExit("Set TEST_DATABASE_URL, see .env.example.")
    return make_url(str(url)).set(database=EVAL_DATABASE)


def create_eval_engine() -> Engine:
    return create_engine(eval_database_url())


def create_eval_database() -> None:
    # Connected to the test database, since the eval one may not exist yet.
    # CREATE DATABASE cannot run inside a transaction.
    admin = create_engine(
        eval_database_url().set(
            database=make_url(str(get_settings().test_database_url)).database
        ),
        isolation_level="AUTOCOMMIT",
    )
    with admin.connect() as connection:
        exists = connection.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": EVAL_DATABASE},
        )
        if not exists:
            connection.execute(text(f"CREATE DATABASE {EVAL_DATABASE}"))
    admin.dispose()


def reset(engine: Engine, case: Case) -> None:
    """Leave the database as the case starts: its senders tracked, its setup done."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(Category(name=name) for name in DEFAULT_CATEGORIES)
        session.add_all(
            TrackedSender(email=sender)
            for sender in sorted({email.sender for email in case.emails})
        )
        session.commit()
        if case.setup is not None:
            case.setup(session)
