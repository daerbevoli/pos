"""
Tests for app.core.database: DB path resolution, table creation/seeding,
and the manual migration helpers that patch up older on-disk schemas.

Every test here monkeypatches database.ENGINE / database.SessionFactory to
an isolated in-memory engine before touching anything — never the real
per-user database file.
"""
import os
import sys

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
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path))

    path = database.get_db_path()

    assert path == os.path.join(str(tmp_path), "SuperPOS", "superpos.db")
    assert os.path.isdir(os.path.join(str(tmp_path), "SuperPOS"))


def test_get_db_path_falls_back_to_home_without_appdata(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
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


def test_migrations_drop_client_contact_unique_indexes_from_older_database(monkeypatch):
    """Databases from before only name/VAT were unique still carry unique
    indexes on address/phone/email/website; they must go, the others stay."""
    engine = _memory_engine()
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        conn.exec_driver_sql("CREATE UNIQUE INDEX ux_clients_address_active ON clients (street, zip_code, city) WHERE is_active = 1")
        conn.exec_driver_sql("CREATE UNIQUE INDEX ux_clients_email_active ON clients (email) WHERE is_active = 1")
        conn.commit()
    monkeypatch.setattr(database, "ENGINE", engine)

    database._run_migrations()
    database._run_migrations()  # idempotent

    with engine.connect() as conn:
        names = {row[0] for row in conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'clients'")}
    assert "ux_clients_address_active" not in names and "ux_clients_email_active" not in names
    assert {"ux_clients_name_active", "ux_clients_vatnumber_active"} <= names


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


def test_migrations_add_and_backfill_invoice_change(monkeypatch):
    """An older invoices table gets change_given, filled in from the sale
    where it still exists; an invoice whose sale was purged stays NULL."""
    engine = _memory_engine()
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        conn.exec_driver_sql("ALTER TABLE invoices DROP COLUMN change_given")
        conn.exec_driver_sql(
            "INSERT INTO clients (id, name, street, zip_code, city, country, vatNumber, is_active) "
            "VALUES (1, 'C', 's', '1000', 'Brussels', 'BE', 'V1', 1)")
        conn.exec_driver_sql(
            "INSERT INTO sales (id, sale_number, total_amount, final_amount, change_given) "
            "VALUES (1, 'S-1', 1.25, 1.25, 0.75)")
        for invoice_id, sale_id in ((1, 1), (2, None)):
            conn.exec_driver_sql(
                "INSERT INTO invoices (id, sale_id, client_id, invoice_number, client_name, "
                "client_vat_number, client_street, client_zip, client_city, client_country) "
                f"VALUES ({invoice_id}, {sale_id or 'NULL'}, 1, 'I-{invoice_id}', 'C', 'V1', 's', '1000', 'Brussels', 'BE')")
        conn.commit()
    monkeypatch.setattr(database, "ENGINE", engine)

    database._run_migrations()
    database._run_migrations()  # idempotent

    with engine.connect() as conn:
        rows = conn.exec_driver_sql("SELECT id, change_given FROM invoices ORDER BY id").fetchall()
    assert rows == [(1, 0.75), (2, None)]


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


# ── Timestamps to UTC ────────────────────────────────────────────────────

def _user_version(engine):
    with engine.connect() as conn:
        return conn.exec_driver_sql("PRAGMA user_version").scalar()


def test_new_database_is_marked_utc_without_converting(monkeypatch):
    engine = _memory_engine()
    Base.metadata.create_all(engine)
    monkeypatch.setattr(database, "ENGINE", engine)

    database._run_migrations()

    assert _user_version(engine) == database._UTC_TIMESTAMPS_VERSION


def test_local_timestamps_are_converted_to_utc_once(monkeypatch, brussels_tz):
    """A database from before the switch (user_version 0) holds naive local
    times; they're rewritten as UTC exactly once, whatever the DST period."""
    from datetime import datetime, timezone
    from app.models.models import ZReport
    engine = _memory_engine()
    Base.metadata.create_all(engine)
    monkeypatch.setattr(database, "ENGINE", engine)
    with engine.connect() as conn:
        conn.exec_driver_sql(
            "INSERT INTO z_reports (id, report_number, period_start, period_end, created_at, "
            "transaction_count, total_amount, tax_amount, final_amount) "
            "VALUES (1, 'Z-0001', '2026-01-15 12:00:00.000000', '2026-07-15 12:00:00.500000', NULL, 0, 0, 0, 0)")
        conn.commit()

    database._run_migrations()
    database._run_migrations()  # must not shift the times a second time

    with sessionmaker(bind=engine)() as session:
        z = session.get(ZReport, 1)
        assert z.period_start == datetime(2026, 1, 15, 11, 0, tzinfo=timezone.utc)          # CET
        assert z.period_end == datetime(2026, 7, 15, 10, 0, 0, 500000, tzinfo=timezone.utc)  # CEST
        assert z.created_at is None
    assert _user_version(engine) == database._UTC_TIMESTAMPS_VERSION


def test_timestamp_conversion_skips_already_utc_database(monkeypatch, brussels_tz):
    engine = _memory_engine()
    Base.metadata.create_all(engine)
    monkeypatch.setattr(database, "ENGINE", engine)
    with engine.connect() as conn:
        conn.exec_driver_sql(f"PRAGMA user_version = {database._UTC_TIMESTAMPS_VERSION}")
        conn.exec_driver_sql("INSERT INTO categories (id, name, created_at) "
                             "VALUES (1, 'X', '2026-01-15 12:00:00.000000')")
        conn.commit()

    database._run_migrations()

    with engine.connect() as conn:
        value = conn.exec_driver_sql("SELECT created_at FROM categories").scalar()
    assert value == "2026-01-15 12:00:00.000000"


def test_timestamp_columns_list_covers_every_utc_column():
    """Every UTCDateTime column existing at the switch is in the list the
    conversion rewrites (columns added later must not be added to it)."""
    from app.models.models import UTCDateTime
    columns = {(t.name, c.name) for t in Base.metadata.sorted_tables
               for c in t.columns if isinstance(c.type, UTCDateTime)}
    assert set(database._LOCAL_TIMESTAMP_COLUMNS) <= columns
