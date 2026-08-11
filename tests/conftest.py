"""
Shared pytest fixtures.

Every fixture that touches the database uses an isolated in-memory SQLite
engine — nothing here ever reads or writes the real per-user database that
app.core.database.get_db_path() points at.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.models import Base


def _make_engine():
    return create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


@pytest.fixture
def db_session():
    """A bare session against a fresh, empty in-memory schema."""
    engine = _make_engine()
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def seeded_session():
    """A session against an in-memory schema seeded like a first run
    (default settings + default categories), via the real seeding logic."""
    import app.core.database as database

    engine = _make_engine()
    Base.metadata.create_all(engine)
    TestSessionFactory = sessionmaker(bind=engine, autoflush=True, autocommit=False)

    real_factory = database.SessionFactory
    database.SessionFactory = TestSessionFactory
    try:
        database._seed_defaults()
    finally:
        database.SessionFactory = real_factory

    session = TestSessionFactory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def patched_db(monkeypatch):
    """Redirect app.core.database.get_session()/SessionFactory/ENGINE to an
    isolated, seeded in-memory DB. Use this for any UI code under test that
    calls get_session() internally, so it never touches the real user DB."""
    import app.core.database as database

    engine = _make_engine()
    Base.metadata.create_all(engine)
    TestSessionFactory = sessionmaker(bind=engine, autoflush=True, autocommit=False)

    monkeypatch.setattr(database, "SessionFactory", TestSessionFactory)
    monkeypatch.setattr(database, "ENGINE", engine)
    database._seed_defaults()

    yield TestSessionFactory
    engine.dispose()
