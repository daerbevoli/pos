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
        "store_name", "store_address", "store_phone", "currency_symbol",
        "receipt_footer", "receipt_printer_vendor_id",
        "receipt_printer_product_id", "label_printer_vendor_id",
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
        assert session.query(Settings).count() == 8
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


# ── _run_migrations: additive columns ───────────────────────────────────

def test_migrations_add_missing_columns(monkeypatch):
    engine = _memory_engine()
    monkeypatch.setattr(database, "ENGINE", engine)

    with engine.connect() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE sales (
                id INTEGER PRIMARY KEY,
                sale_number TEXT UNIQUE NOT NULL,
                total_amount REAL NOT NULL,
                final_amount REAL NOT NULL
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE sale_items (
                id INTEGER PRIMARY KEY,
                sale_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                product_name TEXT NOT NULL,
                quantity REAL NOT NULL,
                unit_price REAL NOT NULL,
                line_total REAL NOT NULL
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE clients (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                address TEXT,
                phone TEXT,
                email TEXT,
                vatNumber TEXT NOT NULL,
                website TEXT,
                is_active BOOLEAN DEFAULT 1
            )
        """)
        conn.commit()

    database._run_migrations()

    with engine.connect() as conn:
        sales_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(sales)")}
        sale_item_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(sale_items)")}
        client_indexes = {row[1] for row in conn.exec_driver_sql("PRAGMA index_list(clients)")}

    assert {"cart_snapshot", "payment_breakdown"} <= sales_cols
    assert {"tax_rate", "tax_amount"} <= sale_item_cols
    assert "ux_clients_name_active" in client_indexes


def test_migrations_are_noop_when_columns_already_present(monkeypatch):
    """Running migrations against an already-current schema must not error."""
    engine = _memory_engine()
    Base.metadata.create_all(engine)
    monkeypatch.setattr(database, "ENGINE", engine)

    database._run_migrations()  # should be a no-op, not raise


def test_migrations_add_invoice_snapshot_columns_preserving_data(monkeypatch):
    """An invoices table predating the client/amount snapshot columns gets
    them added, with existing rows preserved."""
    engine = _memory_engine()
    monkeypatch.setattr(database, "ENGINE", engine)

    with engine.connect() as conn:
        # Full old-style clients columns so the (unrelated) client-index
        # migration this triggers can complete — this test is only about
        # the invoices snapshot columns.
        conn.exec_driver_sql("""
            CREATE TABLE clients (
                id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, address TEXT,
                phone TEXT, email TEXT, vatNumber TEXT UNIQUE NOT NULL, website TEXT,
                is_active BOOLEAN DEFAULT 1
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE sales (
                id INTEGER PRIMARY KEY, sale_number TEXT UNIQUE NOT NULL,
                total_amount REAL, final_amount REAL, cart_snapshot TEXT, payment_breakdown TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE sale_items (
                id INTEGER PRIMARY KEY, sale_id INTEGER, product_id INTEGER, product_name TEXT,
                quantity REAL, unit_price REAL, line_total REAL, tax_rate INTEGER, tax_amount REAL
            )
        """)
        # Old-style invoices: just the original 4 columns, no snapshot fields.
        conn.exec_driver_sql("""
            CREATE TABLE invoices (
                id INTEGER PRIMARY KEY, sale_id INTEGER UNIQUE, client_id INTEGER,
                invoice_number TEXT UNIQUE
            )
        """)
        conn.exec_driver_sql(
            "INSERT INTO invoices (sale_id, client_id, invoice_number) VALUES (1, 1, 'I-OLD')"
        )
        conn.commit()

    database._run_migrations()

    with engine.connect() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(invoices)")}
        assert {
            "issued_at", "client_name", "client_vat_number", "client_address",
            "total_amount", "tax_amount", "final_amount", "line_items_snapshot",
        } <= cols

        row = conn.exec_driver_sql(
            "SELECT sale_id, client_id, invoice_number FROM invoices"
        ).fetchone()
        assert row == (1, 1, "I-OLD")


# ── _migrate_clients_to_partial_unique ──────────────────────────────────

def test_migrate_clients_preserves_data_and_relaxes_uniqueness(monkeypatch):
    engine = _memory_engine()
    monkeypatch.setattr(database, "ENGINE", engine)

    with engine.connect() as conn:
        # Old-style schema: column-level UNIQUE constraints baked into the table.
        conn.exec_driver_sql("""
            CREATE TABLE clients (
                id INTEGER PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                address TEXT UNIQUE,
                phone TEXT UNIQUE,
                email TEXT UNIQUE,
                vatNumber TEXT UNIQUE NOT NULL,
                website TEXT UNIQUE,
                is_active BOOLEAN DEFAULT 1
            )
        """)
        conn.exec_driver_sql(
            "INSERT INTO clients (name, vatNumber, is_active) VALUES ('Acme', 'V1', 1)"
        )
        conn.exec_driver_sql("""
            CREATE TABLE sales (
                id INTEGER PRIMARY KEY, sale_number TEXT UNIQUE NOT NULL,
                total_amount REAL, final_amount REAL,
                cart_snapshot TEXT, payment_breakdown TEXT
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE sale_items (
                id INTEGER PRIMARY KEY, sale_id INTEGER, product_id INTEGER,
                product_name TEXT, quantity REAL, unit_price REAL, line_total REAL,
                tax_rate INTEGER, tax_amount REAL
            )
        """)
        # A table with a FOREIGN KEY REFERENCES clients(...), same as the
        # real invoices table — this is what SQLite's RENAME TABLE would
        # silently corrupt without PRAGMA legacy_alter_table=ON (see
        # test_migrate_clients_does_not_corrupt_dependent_foreign_keys).
        conn.exec_driver_sql("""
            CREATE TABLE invoices (
                id INTEGER PRIMARY KEY, sale_id INTEGER UNIQUE, client_id INTEGER,
                invoice_number TEXT UNIQUE,
                FOREIGN KEY(client_id) REFERENCES clients(id),
                FOREIGN KEY(sale_id) REFERENCES sales(id)
            )
        """)
        conn.commit()

    database._run_migrations()

    with engine.connect() as conn:
        rows = list(conn.exec_driver_sql("SELECT name, vatNumber, is_active FROM clients"))
        assert rows == [("Acme", "V1", 1)]

        # Deactivate the original, then a second client can reuse its name —
        # impossible under the old blanket column-level UNIQUE.
        conn.exec_driver_sql("UPDATE clients SET is_active = 0 WHERE name = 'Acme'")
        conn.commit()
        conn.exec_driver_sql("INSERT INTO clients (name, address, vatNumber, is_active) VALUES ('Acme', '2 Main St', 'V2', 1)")
        conn.commit()

        count = conn.exec_driver_sql("SELECT COUNT(*) FROM clients").scalar()
        assert count == 2

        client_indexes = {row[1] for row in conn.exec_driver_sql("PRAGMA index_list(clients)")}
        assert "ux_clients_name_active" in client_indexes


def test_migrate_clients_does_not_corrupt_dependent_foreign_keys(monkeypatch):
    """
    Regression: SQLite's ALTER TABLE ... RENAME TO auto-rewrites *other*
    tables' REFERENCES clauses to follow the renamed table, regardless of
    the foreign_keys pragma (that only controls enforcement, not this
    schema rewrite). Without PRAGMA legacy_alter_table=ON, renaming
    clients -> clients_old silently corrupted invoices.client_id's foreign
    key to point at clients_old, which was then dropped — so every future
    INSERT INTO invoices raised "no such table: main.clients_old" once FK
    enforcement was on. Assert the invoices schema still references
    `clients`, and that inserting a row actually works.
    """
    engine = _memory_engine()
    monkeypatch.setattr(database, "ENGINE", engine)

    with engine.connect() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE clients (
                id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, address TEXT,
                phone TEXT, email TEXT, vatNumber TEXT UNIQUE NOT NULL, website TEXT,
                is_active BOOLEAN DEFAULT 1
            )
        """)
        conn.exec_driver_sql("INSERT INTO clients (name, vatNumber) VALUES ('Acme', 'V1')")
        conn.exec_driver_sql("""
            CREATE TABLE sales (
                id INTEGER PRIMARY KEY, sale_number TEXT UNIQUE NOT NULL,
                total_amount REAL, final_amount REAL, cart_snapshot TEXT, payment_breakdown TEXT
            )
        """)
        conn.exec_driver_sql("INSERT INTO sales (sale_number, total_amount, final_amount) VALUES ('S-1', 1, 1)")
        conn.exec_driver_sql("""
            CREATE TABLE sale_items (
                id INTEGER PRIMARY KEY, sale_id INTEGER, product_id INTEGER,
                product_name TEXT, quantity REAL, unit_price REAL, line_total REAL,
                tax_rate INTEGER, tax_amount REAL
            )
        """)
        conn.exec_driver_sql("""
            CREATE TABLE invoices (
                id INTEGER PRIMARY KEY, sale_id INTEGER UNIQUE, client_id INTEGER,
                invoice_number TEXT UNIQUE,
                FOREIGN KEY(client_id) REFERENCES clients(id),
                FOREIGN KEY(sale_id) REFERENCES sales(id)
            )
        """)
        conn.commit()
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")

    database._run_migrations()

    with engine.connect() as conn:
        invoices_sql = conn.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='invoices'"
        ).fetchone()[0]
        assert "clients_old" not in invoices_sql

        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        conn.exec_driver_sql(
            "INSERT INTO invoices (sale_id, client_id, invoice_number) VALUES (1, 1, 'I-1')"
        )
        conn.commit()  # must not raise "no such table: main.clients_old"


# ── _repair_invoices_fk_if_broken ───────────────────────────────────────

def _create_sale_and_client(conn):
    conn.exec_driver_sql("""
        CREATE TABLE clients (
            id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, vatNumber TEXT UNIQUE NOT NULL,
            is_active BOOLEAN DEFAULT 1
        )
    """)
    conn.exec_driver_sql("INSERT INTO clients (name, vatNumber) VALUES ('Acme', 'V1')")
    conn.exec_driver_sql("""
        CREATE TABLE sales (
            id INTEGER PRIMARY KEY, sale_number TEXT UNIQUE NOT NULL,
            total_amount REAL, final_amount REAL
        )
    """)
    conn.exec_driver_sql("INSERT INTO sales (sale_number, total_amount, final_amount) VALUES ('S-1', 1, 1)")
    conn.commit()


def test_repair_invoices_fk_fixes_already_corrupted_database(monkeypatch):
    """A database that already hit the corruption (e.g. upgraded before
    this fix existed) has invoices.client_id referencing clients_old
    directly in its stored schema. The repair must rebuild it against
    clients, preserving existing rows, so invoice inserts work again."""
    engine = _memory_engine()
    monkeypatch.setattr(database, "ENGINE", engine)

    with engine.connect() as conn:
        _create_sale_and_client(conn)
        # Simulate the already-corrupted schema directly, exactly as it
        # would exist on a machine that hit the bug before this fix.
        conn.exec_driver_sql("""
            CREATE TABLE invoices (
                id INTEGER PRIMARY KEY, sale_id INTEGER UNIQUE, client_id INTEGER,
                invoice_number TEXT UNIQUE,
                FOREIGN KEY(client_id) REFERENCES "clients_old"(id)
            )
        """)
        conn.exec_driver_sql(
            "INSERT INTO invoices (sale_id, client_id, invoice_number) VALUES (1, 1, 'I-OLD')"
        )
        conn.commit()

    with engine.connect() as conn:
        database._repair_invoices_fk_if_broken(conn)

    with engine.connect() as conn:
        invoices_sql = conn.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='invoices'"
        ).fetchone()[0]
        assert "clients_old" not in invoices_sql

        # Pre-existing invoice row survived the rebuild.
        row = conn.exec_driver_sql(
            "SELECT sale_id, client_id, invoice_number FROM invoices"
        ).fetchone()
        assert row == (1, 1, "I-OLD")

        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        conn.exec_driver_sql(
            "INSERT INTO invoices (sale_id, client_id, invoice_number, client_name, client_vat_number, client_address) "
            "SELECT NULL, id, 'I-NEW', name, \"vatNumber\", '1 Main St' FROM clients WHERE id = 1"
        )
        conn.commit()  # must not raise


def test_repair_invoices_fk_is_noop_on_healthy_schema(monkeypatch):
    engine = _memory_engine()
    monkeypatch.setattr(database, "ENGINE", engine)

    with engine.connect() as conn:
        _create_sale_and_client(conn)
        conn.exec_driver_sql("""
            CREATE TABLE invoices (
                id INTEGER PRIMARY KEY, sale_id INTEGER UNIQUE, client_id INTEGER,
                invoice_number TEXT UNIQUE,
                FOREIGN KEY(client_id) REFERENCES clients(id)
            )
        """)
        conn.commit()
        original_sql = conn.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='invoices'"
        ).fetchone()[0]

    with engine.connect() as conn:
        database._repair_invoices_fk_if_broken(conn)

    with engine.connect() as conn:
        unchanged_sql = conn.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='invoices'"
        ).fetchone()[0]
    assert unchanged_sql == original_sql


def test_repair_invoices_fk_noop_when_invoices_table_missing(monkeypatch):
    engine = _memory_engine()
    monkeypatch.setattr(database, "ENGINE", engine)
    with engine.connect() as conn:
        database._repair_invoices_fk_if_broken(conn)  # no invoices table at all — must not raise
