"""
Database Setup & Session Management
Handles SQLite connection, table creation, and provides session access.
"""
import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from app.models.models import Base, Settings, Category, Client, Invoice

# Store DB in user's app data folder (works on both Linux and Windows)
def get_db_path() -> str:
    if os.name == "nt":  # Windows
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    else:  # Linux / Mac
        base = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))

    app_dir = os.path.join(base, "SuperPOS")
    os.makedirs(app_dir, exist_ok=True)
    return os.path.join(app_dir, "superpos.db")


DB_PATH = get_db_path()
ENGINE = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
    echo=False  # Set True to log all SQL queries during development
)

# Enable WAL mode for better concurrent read performance
@event.listens_for(ENGINE, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

SessionFactory = sessionmaker(bind=ENGINE, autoflush=True, autocommit=False)


def init_db():
    """Create all tables and seed default data if first run."""
    Base.metadata.create_all(ENGINE)
    _run_migrations()
    _seed_defaults()


def _run_migrations():
    """Add columns that create_all() won't add to an already-existing table."""
    with ENGINE.connect() as conn:
        sales_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(sales)")}
        if "cart_snapshot" not in sales_cols:
            conn.exec_driver_sql("ALTER TABLE sales ADD COLUMN cart_snapshot TEXT")
            conn.commit()
        if "payment_breakdown" not in sales_cols:
            conn.exec_driver_sql("ALTER TABLE sales ADD COLUMN payment_breakdown TEXT")
            conn.commit()

        sale_item_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(sale_items)")}
        if "tax_rate" not in sale_item_cols:
            conn.exec_driver_sql("ALTER TABLE sale_items ADD COLUMN tax_rate INTEGER DEFAULT 0")
            conn.commit()
        if "tax_amount" not in sale_item_cols:
            conn.exec_driver_sql("ALTER TABLE sale_items ADD COLUMN tax_amount REAL DEFAULT 0.0")
            conn.commit()

        client_indexes = {row[1] for row in conn.exec_driver_sql("PRAGMA index_list(clients)")}
        if "ux_clients_name_active" not in client_indexes:
            _migrate_clients_to_partial_unique(conn)

        # Rebuilds invoices (if broken) using the current model, so it already
        # has the columns added below — run this first.
        _repair_invoices_fk_if_broken(conn)

        invoice_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(invoices)")}
        if invoice_cols:  # empty means the table doesn't exist yet — create_all() will make it current
            new_invoice_columns = {
                "issued_at": "DATETIME",
                "client_name": "TEXT",
                "client_vat_number": "TEXT",
                "client_address": "TEXT",
                "total_amount": "REAL",
                "tax_amount": "REAL",
                "final_amount": "REAL",
                "line_items_snapshot": "TEXT",
            }
            for col, col_type in new_invoice_columns.items():
                if col not in invoice_cols:
                    conn.exec_driver_sql(f"ALTER TABLE invoices ADD COLUMN {col} {col_type}")
                    conn.commit()


def _migrate_clients_to_partial_unique(conn):
    """
    Older schema had column-level UNIQUE constraints on clients
    (name/address/phone/email/vatNumber/website), which SQLite bakes into
    the table definition — they can't be dropped with ALTER TABLE, so the
    table has to be rebuilt. Replaces them with partial unique indexes that
    only apply to active clients (see Client.__table_args__).

    PRAGMA legacy_alter_table=ON is essential here: SQLite's default (smart)
    RENAME TABLE rewrites *other* tables' REFERENCES clauses to follow the
    renamed table — regardless of the foreign_keys pragma, which only
    controls constraint *enforcement*, not this schema-rewrite behavior.
    Without it, invoices.client_id (FOREIGN KEY REFERENCES clients) would
    get silently rewritten to REFERENCES clients_old, which is then
    dropped — corrupting invoices permanently (see _repair_invoices_fk_if_broken,
    which fixes databases that already hit this before the pragma was added).
    """
    conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
    conn.exec_driver_sql("PRAGMA legacy_alter_table=ON")
    conn.exec_driver_sql("ALTER TABLE clients RENAME TO clients_old")
    conn.exec_driver_sql("PRAGMA legacy_alter_table=OFF")
    Client.__table__.create(conn)
    conn.exec_driver_sql(
        'INSERT INTO clients (id, name, address, phone, email, "vatNumber", website, is_active) '
        'SELECT id, name, address, phone, email, "vatNumber", website, is_active FROM clients_old'
    )
    conn.exec_driver_sql("DROP TABLE clients_old")
    conn.commit()
    conn.exec_driver_sql("PRAGMA foreign_keys=ON")


def _repair_invoices_fk_if_broken(conn):
    """
    One-time repair for databases that already hit the bug described in
    _migrate_clients_to_partial_unique: their invoices table's stored schema
    still references the long-dropped clients_old table, which makes every
    future invoice INSERT/UPDATE fail with "no such table: main.clients_old"
    once foreign key enforcement is on. Rebuilds invoices against the
    correct FOREIGN KEY(client_id) REFERENCES clients(id) if so.
    """
    row = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='invoices'"
    ).fetchone()
    if row is None or row[0] is None or "clients_old" not in row[0]:
        return

    conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
    conn.exec_driver_sql("PRAGMA legacy_alter_table=ON")
    conn.exec_driver_sql("ALTER TABLE invoices RENAME TO invoices_old")
    conn.exec_driver_sql("PRAGMA legacy_alter_table=OFF")
    Invoice.__table__.create(conn)
    conn.exec_driver_sql(
        "INSERT INTO invoices (id, sale_id, client_id, invoice_number) "
        "SELECT id, sale_id, client_id, invoice_number FROM invoices_old"
    )
    conn.exec_driver_sql("DROP TABLE invoices_old")
    conn.commit()
    conn.exec_driver_sql("PRAGMA foreign_keys=ON")


def get_session() -> Session:
    """Get a new database session. Always close it when done."""
    return SessionFactory()


def _seed_defaults():
    """Insert default settings and categories on first run."""
    with SessionFactory() as session:
        # Default settings
        defaults = [
            ("store_name", "My Supermarket", "Store name shown on receipts"),
            ("store_address", "", "Store address for receipts"),
            ("store_phone", "", "Store phone number"),
            ("currency_symbol", "€", "Currency symbol"),
            ("receipt_footer", "Thank you for shopping with us!", "Receipt footer text"),
            ("receipt_printer_vendor_id", "", "USB vendor ID for receipt printer"),
            ("receipt_printer_product_id", "", "USB product ID for receipt printer"),
            ("label_printer_vendor_id", "", "USB vendor ID for label printer"),
            # ("logo", "Browse logo", "Logo shown on receipts")
        ]
        for key, value, desc in defaults:
            exists = session.query(Settings).filter_by(key=key).first()
            if not exists:
                session.add(Settings(key=key, value=value, description=desc))

        # Default categories
        default_categories = [
            "Fruit & Vegetables", "Dairy & Eggs", "Meat & Fish",
            "Bakery", "Frozen", "Beverages", "Snacks & Confectionery",
            "Cleaning & Household", "Personal Care", "Other"
        ]
        for cat_name in default_categories:
            exists = session.query(Category).filter_by(name=cat_name).first()
            if not exists:
                session.add(Category(name=cat_name))

        session.commit()
