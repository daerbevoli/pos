"""
Database Setup & Session Management
Handles SQLite connection, table creation, and provides session access.
"""
import os
from typing import NamedTuple
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from app.models.models import Base, Settings, Category

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


class _ColumnMigration(NamedTuple):
    """One column that create_all() won't add to an already-existing table.
    `why` is kept right next to the column it explains instead of scattered
    in comments, as a lightweight in-code changelog of the schema."""
    table: str
    column: str
    sql_type: str
    why: str


# Every plain "add a column" migration, in the order they were introduced.
# Anything that renames/rebuilds a table or moves data between tables is a
# bigger step than one column — give it its own function, called from
# _run_migrations(), instead.
#
# The schema was reset to a clean baseline before the first shop went live;
# everything below was added after that baseline. The history of how the
# schema got to the baseline is in git.
_COLUMN_MIGRATIONS: list[_ColumnMigration] = [
    _ColumnMigration(
        "invoices", "payment_method", "VARCHAR(20)",
        why="Invoices snapshot how they were paid, so the reports' payment "
            "breakdown still works after a Z report purges their sale. NULL on "
            "older invoices — invoice_payment_breakdown() falls back to the sale.",
    ),
    _ColumnMigration(
        "invoices", "payment_breakdown", "TEXT",
        why="Per-method split of the invoice's payment (JSON), snapshotted "
            "alongside payment_method for the same reason.",
    ),
]


def _run_migrations():
    """Applies every schema change create_all() can't make to an
    already-existing table (it only creates missing tables, never alters
    existing ones). Each step here checks before acting, so this is safe
    to run unconditionally on every startup, including a brand new
    database with nothing to do."""
    with ENGINE.connect() as conn:
        for migration in _COLUMN_MIGRATIONS:
            _add_column_if_missing(conn, migration.table, migration.column, migration.sql_type)


def _table_columns(conn, table: str) -> set[str]:
    """Column names of `table`, or an empty set if it doesn't exist yet —
    create_all() will have created it fresh, with every current column, so
    there's nothing to migrate."""
    return {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}


def _add_column_if_missing(conn, table: str, column: str, sql_type: str):
    cols = _table_columns(conn, table)
    if cols and column not in cols:
        conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}")
        conn.commit()


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
            ("label_printer_product_id", "", "USB product ID for label printer"),
            ("erp_url", "", "Odoo base URL, e.g. https://mycompany.odoo.com"),
            ("erp_db", "", "Odoo database name"),
            ("erp_api_key", "", "Odoo API key used for invoice export"),
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
