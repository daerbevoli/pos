"""
Database Setup & Session Management
Handles SQLite connection, table creation, and provides session access.
"""
import os
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
    _seed_defaults()


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
