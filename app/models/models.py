"""
Database Models
All tables are defined here using SQLAlchemy ORM.
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean,
    DateTime, ForeignKey, Text, Enum
)
from sqlalchemy.orm import relationship, DeclarativeBase


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
    tax = Column(Integer, nullable=False, default=0)    # 0, 6, 21 %
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
    payment_method = Column(Enum("cash", "card", "bancontact", "meal_voucher", "mixed", name="payment_method"), default="cash")
    amount_tendered = Column(Float, nullable=True)     # Cash given by customer
    change_given = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)
    status = Column(Enum("completed", "refunded", "voided", name="sale_status"), default="completed")
    created_at = Column(DateTime, default=datetime.now)

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
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Float, nullable=False)           # Snapshot at time of sale
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
    name = Column(String(50), unique=True, nullable=False)
    address = Column(String(50), unique=True, nullable=True)
    phone = Column(String(50), unique=True, nullable=True)
    email = Column(String(50), unique=True, nullable=True)
    vatNumber = Column(String(50), unique=True, nullable=False)
    website = Column(String(50), unique=True, nullable=True)
    is_active = Column(Boolean, default=True)

    def __repr__(self):
        return f"<Client {self.name} {self.vatNumber}>"

class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True)
    sale_id = Column(Integer, ForeignKey("sales.id"), unique=True)
    client_id = Column(Integer, ForeignKey("clients.id"))
    invoice_number = Column(String, unique=True)