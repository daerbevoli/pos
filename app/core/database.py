"""
Database Setup & Session Management
Handles SQLite connection, table creation, and provides session access.
"""
import os
from typing import NamedTuple
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from app.models.models import Base, Settings, Category, Client, Invoice, Shortcut, ShortcutItem, Promo, PromoItem
from app.constants.countries import BELGIUM

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


_INVOICE_SNAPSHOT_WHY = (
    "An invoice used to be a thin pointer to its Sale/Client; once it had "
    "to stay correct even after the client or sale later changed, it "
    "needed its own frozen snapshot of the client and amounts as of when "
    "it was issued (feat: invoice independent of sale and immutable)."
)

# Every plain "add a column" migration, in the order they were introduced.
# Anything that renames/rebuilds a table or moves data between tables is a
# bigger step than one column — those get their own function below instead.
_COLUMN_MIGRATIONS = [
    _ColumnMigration(
        "sales", "cart_snapshot", "TEXT",
        "Reopening a held/completed ticket needs to replay the exact cart "
        "contents (line items, discounts, subtotals), not just its totals "
        "(feat: reopen ticket)."
    ),
    _ColumnMigration(
        "sales", "payment_breakdown", "TEXT",
        "A sale can be paid with a mix of tenders (split cash/card), so "
        "the single payment_method column alone can't reconstruct a "
        "receipt (feat: multi payment)."
    ),
    _ColumnMigration(
        "sales", "updated_at", "DATETIME",
        "A reopened/edited completed sale needed its own last-modified "
        "timestamp, separate from created_at."
    ),
    _ColumnMigration(
        "sale_items", "tax_rate", "INTEGER DEFAULT 0",
        "VAT reporting (reports, invoices) needs each line's tax rate "
        "frozen at sale time, independent of the product's tax rate "
        "possibly changing later (feat: VAT separation in reports/invoices)."
    ),
    _ColumnMigration(
        "sale_items", "tax_amount", "REAL DEFAULT 0.0",
        "The computed VAT portion of each line, frozen alongside tax_rate "
        "for the same reason."
    ),
    _ColumnMigration(
        "products", "is_open_price", "BOOLEAN NOT NULL DEFAULT 0",
        "Loose/bulk items (deli counter, bakery) need their price typed "
        "in per sale rather than fixed on the product (feat: open-price "
        "items)."
    ),
    _ColumnMigration(
        "clients", "country", f"TEXT NOT NULL DEFAULT '{BELGIUM}'",
        "Invoicing needs a client's country to apply the right VAT "
        "treatment (domestic / EU reverse-charge / non-EU export) — this "
        "POS was Belgium-only before, so existing clients backfill as "
        "domestic."
    ),
    _ColumnMigration("invoices", "issued_at", "DATETIME", _INVOICE_SNAPSHOT_WHY),
    _ColumnMigration("invoices", "client_name", "TEXT", _INVOICE_SNAPSHOT_WHY),
    _ColumnMigration("invoices", "client_vat_number", "TEXT", _INVOICE_SNAPSHOT_WHY),
    _ColumnMigration("invoices", "client_address", "TEXT", _INVOICE_SNAPSHOT_WHY),
    _ColumnMigration("invoices", "total_amount", "REAL", _INVOICE_SNAPSHOT_WHY),
    _ColumnMigration("invoices", "tax_amount", "REAL", _INVOICE_SNAPSHOT_WHY),
    _ColumnMigration("invoices", "final_amount", "REAL", _INVOICE_SNAPSHOT_WHY),
    _ColumnMigration("invoices", "line_items_snapshot", "TEXT", _INVOICE_SNAPSHOT_WHY),
    _ColumnMigration(
        "invoices", "sent_at", "DATETIME",
        "Marks an invoice as transmitted; once set it can no longer be "
        "edited (update_sale refuses), and corrections must go through a "
        "credit note instead."
    ),
    _ColumnMigration(
        "invoices", "updated_at", "DATETIME",
        "Tracks when an unsent invoice's snapshot was last kept in sync "
        "with an edit to its underlying sale."
    ),
    _ColumnMigration(
        "z_reports", "category_breakdown", "TEXT",
        "The Z-report needed a per-category sales breakdown alongside its "
        "totals (feat: X and Z report)."
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

        _migrate_promo_schema(conn)
        _migrate_clients_to_partial_unique(conn)
        # Must run after the clients migration above: it repairs databases
        # that already hit the FK-corruption bug that migration used to have.
        _add_shortcuts_tables(conn)


def _table_columns(conn, table: str) -> set[str]:
    """Column names of `table`, or an empty set if it doesn't exist yet —
    create_all() will have created it fresh, with every current column, so
    there's nothing to migrate."""
    return {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}


def _existing_tables(conn) -> set[str]:
    return {row[0] for row in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'")}


def _add_column_if_missing(conn, table: str, column: str, sql_type: str):
    cols = _table_columns(conn, table)
    if cols and column not in cols:
        conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}")
        conn.commit()


def _migrate_promo_schema(conn):
    """Why: promos moved from one whole-promo discount to a per-product
    discount on a new promo_items table, and gained start_date/end_date, so
    a promo could target specific products over a specific date range
    (feat: promo per product with dated promos). Handles three states: no
    promos table yet (create_all() above already made the current schema —
    nothing to do), an already-current promos table (just backfill
    promo_items if that table is somehow missing), or the old schema (has
    discount_type/discount_value) that needs migrating in place.
    """
    existing_tables = _existing_tables(conn)
    if "promos" not in existing_tables:
        return  # create_all() already built the current schema

    promo_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(promos)")}
    is_old_schema = "discount_type" in promo_cols

    if "promo_items" not in existing_tables:
        PromoItem.__table__.create(conn)
        conn.commit()

    if is_old_schema:
        product_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(products)")}
        if "promo_id" in product_cols:
            conn.exec_driver_sql(
                "INSERT INTO promo_items (promo_id, product_id, discount_type, discount_value) "
                "SELECT p.promo_id, p.id, pr.discount_type, pr.discount_value "
                "FROM products p JOIN promos pr ON pr.id = p.promo_id "
                "WHERE p.promo_id IS NOT NULL"
            )
            conn.commit()
            conn.exec_driver_sql("ALTER TABLE products DROP COLUMN promo_id")
            conn.commit()

        conn.exec_driver_sql("ALTER TABLE promos DROP COLUMN discount_type")
        conn.exec_driver_sql("ALTER TABLE promos DROP COLUMN discount_value")
        conn.commit()
        promo_cols.discard("discount_type")
        promo_cols.discard("discount_value")

    if "start_date" not in promo_cols:
        conn.exec_driver_sql("ALTER TABLE promos ADD COLUMN start_date DATE")
        conn.commit()
    if "end_date" not in promo_cols:
        conn.exec_driver_sql("ALTER TABLE promos ADD COLUMN end_date DATE")
        conn.commit()

    # Old schema also predates products.promo_id being dropped above when
    # there was no old-schema promo data to migrate but the column still
    # lingers (e.g. it was added but never used).
    product_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(products)")}
    if "promo_id" in product_cols:
        conn.exec_driver_sql("ALTER TABLE products DROP COLUMN promo_id")
        conn.commit()


def _migrate_clients_to_partial_unique(conn):
    """Why: the older schema had column-level UNIQUE constraints on clients
    (name/address/phone/email/vatNumber/website); deactivating a client and
    later reusing its name/VAT/etc. hit those constraints, so they're
    replaced with partial unique indexes that only apply to active clients
    (see Client.__table_args__) (feat: change client screen to match
    inventory screen + CSV import). SQLite bakes column-level UNIQUE into
    the table definition — it can't be dropped with ALTER TABLE, so the
    table has to be rebuilt instead.

    PRAGMA legacy_alter_table=ON is essential here: SQLite's default (smart)
    RENAME TABLE rewrites *other* tables' REFERENCES clauses to follow the
    renamed table — regardless of the foreign_keys pragma, which only
    controls constraint *enforcement*, not this schema-rewrite behavior.
    Without it, invoices.client_id (FOREIGN KEY REFERENCES clients) would
    get silently rewritten to REFERENCES clients_old, which is then
    dropped — corrupting invoices permanently (see _repair_invoices_fk_if_broken,
    which fixes databases that already hit this before the pragma was added).
    """
    existing_indexes = {row[1] for row in conn.exec_driver_sql("PRAGMA index_list(clients)")}
    if "ux_clients_name_active" in existing_indexes:
        return  # already migrated

    conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
    conn.exec_driver_sql("PRAGMA legacy_alter_table=ON")
    conn.exec_driver_sql("ALTER TABLE clients RENAME TO clients_old")
    conn.exec_driver_sql("PRAGMA legacy_alter_table=OFF")
    Client.__table__.create(conn)
    conn.exec_driver_sql(
        'INSERT INTO clients (id, name, address, country, phone, email, "vatNumber", website, is_active) '
        # address is now NOT NULL; older rows that predate the address
        # requirement get an empty string rather than failing the copy.
        # country doesn't exist on clients_old at all — this POS is
        # Belgium-only so far, so backfill every row as domestic.
        f'SELECT id, name, COALESCE(address, \'\'), \'{BELGIUM}\', phone, email, "vatNumber", website, is_active FROM clients_old'
    )
    conn.exec_driver_sql("DROP TABLE clients_old")
    conn.commit()
    conn.exec_driver_sql("PRAGMA foreign_keys=ON")


def _add_shortcuts_tables(conn):
    """Why: POS shortcut pages — hand-picked product-button pages, kept
    separate from category browsing (feat: shortcuts). create_all() above
    already creates these tables on any database that reaches here; this
    is the explicit record of when they were introduced and a safety net
    if create_all() is ever skipped."""
    existing_tables = _existing_tables(conn)
    if "shortcuts" not in existing_tables:
        Shortcut.__table__.create(conn)
        conn.commit()
    if "shortcut_items" not in existing_tables:
        ShortcutItem.__table__.create(conn)
        conn.commit()


def _ensure_legacy_placeholder_client(conn) -> int:
    """Inactive client that pre-existing invoices with no client_id get
    attached to, so invoices.client_id (NOT NULL) can be satisfied without
    inventing a real customer. Hidden from normal use since is_active=0."""
    existing = conn.exec_driver_sql(
        "SELECT id FROM clients WHERE \"vatNumber\" = 'LEGACY-NO-CLIENT'"
    ).fetchone()
    if existing:
        return existing[0]
    conn.exec_driver_sql(
        'INSERT INTO clients (name, address, country, "vatNumber", is_active) '
        f"VALUES ('(legacy invoice, no client on file)', '', '{BELGIUM}', 'LEGACY-NO-CLIENT', 0)"
    )
    return conn.exec_driver_sql(
        "SELECT id FROM clients WHERE \"vatNumber\" = 'LEGACY-NO-CLIENT'"
    ).fetchone()[0]


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
