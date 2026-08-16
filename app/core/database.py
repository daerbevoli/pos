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
        # address is now NOT NULL; older rows that predate the address
        # requirement get an empty string rather than failing the copy.
        'SELECT id, name, COALESCE(address, \'\'), phone, email, "vatNumber", website, is_active FROM clients_old'
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

    # client_id and the client_name/vat/address snapshot are NOT NULL now,
    # but invoices_old may predate all of that (client_id could be NULL —
    # invoices didn't always require a client — and the snapshot columns
    # may not even exist yet). Route orphaned rows to a placeholder client
    # and backfill missing/NULL snapshot text with '' rather than losing
    # the row or fabricating a real customer.
    old_cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(invoices_old)")}
    has_orphans = "client_id" not in old_cols or conn.exec_driver_sql(
        "SELECT 1 FROM invoices_old WHERE client_id IS NULL LIMIT 1"
    ).fetchone() is not None
    if has_orphans:
        placeholder_id = _ensure_legacy_placeholder_client(conn)
        client_id_expr = f"COALESCE(client_id, {placeholder_id})" if "client_id" in old_cols else str(placeholder_id)
    else:
        client_id_expr = "client_id"
    snapshot_cols = ["client_name", "client_vat_number", "client_address"]
    select_parts = ["id", "sale_id", client_id_expr, "invoice_number"] + [
        f"COALESCE({col}, '')" if col in old_cols else "''" for col in snapshot_cols
    ]
    conn.exec_driver_sql(
        f"INSERT INTO invoices (id, sale_id, client_id, invoice_number, {', '.join(snapshot_cols)}) "
        f"SELECT {', '.join(select_parts)} FROM invoices_old"
    )
    conn.exec_driver_sql("DROP TABLE invoices_old")
    conn.commit()
    conn.exec_driver_sql("PRAGMA foreign_keys=ON")


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
        'INSERT INTO clients (name, address, "vatNumber", is_active) '
        "VALUES ('(legacy invoice, no client on file)', '', 'LEGACY-NO-CLIENT', 0)"
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
