"""
Tests for app.core.database: DB path resolution, table creation/seeding,
and the manual migration helpers that patch up older on-disk schemas.

Every test here monkeypatches database.ENGINE / database.SessionFactory to
an isolated in-memory engine before touching anything — never the real
per-user database file.
"""
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.core.database as database
from app.models.models import Base, Settings, Category


def _memory_engine():
    return create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


# ── get_db_path ──────────────────────────────────────────────────────────

def test_get_db_path_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setenv("APPDATA", str(tmp_path))

    path = database.get_db_path()

    assert path == os.path.join(str(tmp_path), "SuperPOS", "superpos.db")
    assert os.path.isdir(os.path.join(str(tmp_path), "SuperPOS"))


def test_get_db_path_falls_back_to_home_without_appdata(monkeypatch, tmp_path):
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path))

    path = database.get_db_path()

    assert path.endswith(os.path.join("SuperPOS", "superpos.db"))


# ── init_db / seeding ────────────────────────────────────────────────────

def test_init_db_creates_tables_and_seeds(monkeypatch):
    engine = _memory_engine()
    monkeypatch.setattr(database, "ENGINE", engine)
    monkeypatch.setattr(database, "SessionFactory", sessionmaker(bind=engine))

    database.init_db()

    with database.SessionFactory() as session:
        settings = session.query(Settings).all()
        categories = session.query(Category).all()

    assert {s.key for s in settings} == {
        "store_name", "store_address", "store_phone", "currency_symbol", "receipt_footer",
        "receipt_printer_vendor_id", "receipt_printer_product_id",
        "label_printer_vendor_id", "label_printer_product_id",
        "erp_url", "erp_db", "erp_api_key",
    }
    assert {c.name for c in categories} == {
        "Fruit & Vegetables", "Dairy & Eggs", "Meat & Fish", "Bakery",
        "Frozen", "Beverages", "Snacks & Confectionery",
        "Cleaning & Household", "Personal Care", "Other",
    }


def test_seed_defaults_is_idempotent(monkeypatch):
    engine = _memory_engine()
    Base.metadata.create_all(engine)
    monkeypatch.setattr(database, "SessionFactory", sessionmaker(bind=engine))

    database._seed_defaults()
    database._seed_defaults()

    with database.SessionFactory() as session:
        assert session.query(Settings).count() == 12
        assert session.query(Category).count() == 10


def test_seed_defaults_preserves_user_edited_values(monkeypatch):
    """Re-running the seed must not clobber a value the user already changed."""
    engine = _memory_engine()
    Base.metadata.create_all(engine)
    monkeypatch.setattr(database, "SessionFactory", sessionmaker(bind=engine))

    database._seed_defaults()
    with database.SessionFactory() as session:
        row = session.query(Settings).filter_by(key="store_name").first()
        row.value = "My Custom Store"
        session.commit()

    database._seed_defaults()

    with database.SessionFactory() as session:
        assert session.query(Settings).filter_by(key="store_name").first().value == "My Custom Store"


# ── _run_migrations ──────────────────────────────────────────────────────

def test_migrations_are_noop_on_current_schema(monkeypatch):
    """Running migrations against an already-current schema must not error."""
    engine = _memory_engine()
    Base.metadata.create_all(engine)
    monkeypatch.setattr(database, "ENGINE", engine)

    database._run_migrations()  # should be a no-op, not raise


def test_column_migration_adds_missing_column_preserving_data(monkeypatch):
    engine = _memory_engine()
    monkeypatch.setattr(database, "ENGINE", engine)
    monkeypatch.setattr(database, "_COLUMN_MIGRATIONS", [
        database._ColumnMigration("widgets", "colour", "TEXT DEFAULT 'red'", "test"),
    ])
    with engine.connect() as conn:
        conn.exec_driver_sql("CREATE TABLE widgets (id INTEGER PRIMARY KEY, name TEXT)")
        conn.exec_driver_sql("INSERT INTO widgets (id, name) VALUES (1, 'a')")
        conn.commit()

    database._run_migrations()
    database._run_migrations()  # idempotent

    with engine.connect() as conn:
        rows = conn.exec_driver_sql("SELECT id, name, colour FROM widgets").fetchall()
    assert rows == [(1, "a", "red")]


def test_migrations_add_invoice_payment_columns_to_older_database(monkeypatch):
    """A database whose invoices table predates the payment snapshot gets
    both columns, and the full model then loads against it."""
    engine = _memory_engine()
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        conn.exec_driver_sql("ALTER TABLE invoices DROP COLUMN payment_method")
        conn.exec_driver_sql("ALTER TABLE invoices DROP COLUMN payment_breakdown")
        conn.commit()
    monkeypatch.setattr(database, "ENGINE", engine)

    database._run_migrations()

    with engine.connect() as conn:
        cols = database._table_columns(conn, "invoices")
    assert {"payment_method", "payment_breakdown"} <= cols


def test_column_migration_skips_missing_table(monkeypatch):
    """A table that doesn't exist yet is left to create_all(), not created here."""
    engine = _memory_engine()
    monkeypatch.setattr(database, "ENGINE", engine)
    monkeypatch.setattr(database, "_COLUMN_MIGRATIONS", [
        database._ColumnMigration("widgets", "colour", "TEXT", "test"),
    ])

    database._run_migrations()

    with engine.connect() as conn:
        assert database._table_columns(conn, "widgets") == set()
