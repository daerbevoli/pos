"""
Database Models
All tables are defined here using SQLAlchemy ORM.
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean,
    DateTime, ForeignKey, Text, Enum, Index, text
)
from sqlalchemy.orm import relationship, backref, DeclarativeBase


class Base(DeclarativeBase):
    pass


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    products = relationship("Product", back_populates="category")

    def __repr__(self):
        return f"<Category {self.name}>"


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    barcode = Column(String(50), unique=True, nullable=True, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Float, nullable=False)
    stock_quantity = Column(Integer, default=0)           # Float to support weight-based items
    min_stock_level = Column(Integer, default=5)          # Alert threshold
    unit = Column(String(20), default="pcs")            # pcs, kg, liter, etc.
    tax = Column(Integer, nullable=False, default=21)    # 0, 6, 21 %
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    category = relationship("Category", back_populates="products")
    sale_items = relationship("SaleItem", back_populates="product")
    stock_movements = relationship("StockMovement", back_populates="product")

    @property
    def is_low_stock(self):
        return self.stock_quantity <= self.min_stock_level

    def __repr__(self):
        return f"<Product {self.name} ({self.barcode})>"


class Sale(Base):
    __tablename__ = "sales"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sale_number = Column(String(20), unique=True, nullable=False)  # e.g. "S-20241201-0042"
    total_amount = Column(Float, nullable=False)
    tax_amount = Column(Float, default=0.0)
    final_amount = Column(Float, nullable=False)
    payment_method = Column(Enum("cash", "card", name="payment_method"), default="cash")
    amount_tendered = Column(Float, nullable=True)     # Cash given by customer
    change_given = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)
    status = Column(Enum("completed", "refunded", "voided", name="sale_status"), default="completed")
    created_at = Column(DateTime, default=datetime.now)
    cart_snapshot = Column(Text, nullable=True)  # JSON: ordered cart entries as they were at payment time
    payment_breakdown = Column(Text, nullable=True)  # JSON: [{"method": "cash", "amount": 20.0}, ...] — how much of final_amount each method covered

    items = relationship("SaleItem", back_populates="sale", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Sale {self.sale_number} €{self.final_amount:.2f}>"


class SaleItem(Base):
    __tablename__ = "sale_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sale_id = Column(Integer, ForeignKey("sales.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    product_name = Column(String(200), nullable=False)  # Snapshot at time of sale
    product_barcode = Column(String(50), nullable=True)
    quantity = Column(Float, nullable=False)
    unit_price = Column(Float, nullable=False)           # Snapshot at time of sale
    tax_rate = Column(Integer, default=0)               # Snapshot of product.tax at sale time (0, 6, 21)
    tax_amount = Column(Float, default=0.0)             # Tax portion of line_total (incl. tax price)
    discount = Column(Float, default=0.0)
    line_total = Column(Float, nullable=False)

    sale = relationship("Sale", back_populates="items")
    product = relationship("Product", back_populates="sale_items")

    def __repr__(self):
        return f"<SaleItem {self.product_name} x{self.quantity}>"


class StockMovement(Base):
    __tablename__ = "stock_movements"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    movement_type = Column(
        Enum("purchase", "sale", "adjustment", "return", "waste", name="movement_type"),
        nullable=False
    )
    quantity = Column(Integer, nullable=False)             # Positive = in, Negative = out
    quantity_before = Column(Integer, nullable=False)
    quantity_after = Column(Integer, nullable=False)
    reference = Column(String(50), nullable=True)        # Sale number or PO number
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    product = relationship("Product", back_populates="stock_movements")

    def __repr__(self):
        return f"<StockMovement {self.product_id} {self.movement_type} {self.quantity}>"


class Settings(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(Text, nullable=True)
    description = Column(Text, nullable=True)

    def __repr__(self):
        return f"<Setting {self.key}={self.value}>"

class Client(Base):
    __tablename__ = "clients"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False)
    address = Column(String(50), nullable=False)
    phone = Column(String(50), nullable=True)
    email = Column(String(50), nullable=True)
    vatNumber = Column(String(50), nullable=False)
    website = Column(String(50), nullable=True)
    is_active = Column(Boolean, default=True)

    # Uniqueness only matters among active clients — deactivating a client
    # (soft delete) frees up its name/address/phone/email/vat/website for reuse.
    __table_args__ = (
        Index("ux_clients_name_active", "name", unique=True, sqlite_where=text("is_active = 1")),
        Index("ux_clients_address_active", "address", unique=True, sqlite_where=text("is_active = 1")),
        Index("ux_clients_phone_active", "phone", unique=True, sqlite_where=text("is_active = 1")),
        Index("ux_clients_email_active", "email", unique=True, sqlite_where=text("is_active = 1")),
        Index("ux_clients_vatnumber_active", "vatNumber", unique=True, sqlite_where=text("is_active = 1")),
        Index("ux_clients_website_active", "website", unique=True, sqlite_where=text("is_active = 1")),
    )

    def __repr__(self):
        return f"<Client {self.name} {self.vatNumber}>"

class ZReport(Base):
    __tablename__ = "z_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_number = Column(String(20), unique=True, nullable=False)  # e.g. "Z-0001"
    period_start = Column(DateTime, nullable=False)
    period_end = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.now)
    transaction_count = Column(Integer, nullable=False, default=0)
    total_amount = Column(Float, nullable=False, default=0.0)   # excl. tax
    tax_amount = Column(Float, nullable=False, default=0.0)
    final_amount = Column(Float, nullable=False, default=0.0)   # incl. tax
    vat_breakdown = Column(Text, nullable=True)      # JSON: {"0": {"base":.., "tax":..}, "6": {...}, "21": {...}}
    category_breakdown = Column(Text, nullable=True)
    payment_breakdown = Column(Text, nullable=True)  # JSON: [{"method": "cash", "amount": ..}, ...]

    def __repr__(self):
        return f"<ZReport {self.report_number} €{self.final_amount:.2f}>"


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True)
    sale_id = Column(Integer, ForeignKey("sales.id"), unique=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    invoice_number = Column(String, unique=True)

    # Snapshot of billing-relevant data as of the moment the invoice was
    # issued. Deliberately duplicated from Client/Sale rather than read live
    # through the relationships below, so the legal document this row
    # represents can never change after the fact — even if the client is
    # later renamed/deactivated or the underlying sale is edited/reopened.
    issued_at = Column(DateTime, default=datetime.now)
    client_name = Column(String, nullable=False)
    client_vat_number = Column(String, nullable=False)
    client_address = Column(String, nullable=False)
    total_amount = Column(Float, nullable=True)
    tax_amount = Column(Float, nullable=True)
    final_amount = Column(Float, nullable=True)
    line_items_snapshot = Column(Text, nullable=True)  # JSON; same shape as Sale.cart_snapshot

    sale   = relationship("Sale", backref=backref("invoice", uselist=False))
    client = relationship("Client", backref=backref("invoices", uselist=True))