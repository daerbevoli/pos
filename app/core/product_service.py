"""
Product & Inventory Service
All business logic for managing products and stock.
"""
from typing import Optional
from sqlalchemy.orm import Session
from app.models.models import Product, Category, StockMovement
from app.core.database import get_session


class ProductService:

    # ── Product CRUD ──────────────────────────────────────────────────────────

    @staticmethod
    def get_all(session: Session, active_only=True) -> list[type[Product]]:
        q = session.query(Product)
        if active_only:
            q = q.filter(Product.is_active == True)
        return q.order_by(Product.name).all()

    @staticmethod
    def get_by_id(session: Session, product_id: int) -> type[Product] | None:
        return session.query(Product).filter_by(id=product_id).first()

    @staticmethod
    def get_by_barcode(session: Session, barcode: str) -> type[Product] | None:
        return session.query(Product).filter_by(barcode=barcode, is_active=True).first()

    @staticmethod
    def search(session: Session, query: str) -> list[type[Product]]:
        """Search by name or barcode."""
        term = f"%{query}%"
        return (
            session.query(Product)
            .filter(
                Product.is_active == True,
                (Product.name.ilike(term)) | (Product.barcode.ilike(term))
            )
            .order_by(Product.name)
            .limit(50)
            .all()
        )

    @staticmethod
    def create(session: Session, **kwargs) -> Product:
        product = Product(**kwargs)
        session.add(product)
        session.commit()
        session.refresh(product)
        return product

    @staticmethod
    def update(session: Session, product_id: int, **kwargs) -> type[Product] | None:
        product = session.query(Product).filter_by(id=product_id).first()
        if not product:
            return None
        for key, value in kwargs.items():
            setattr(product, key, value)
        session.commit()
        session.refresh(product)
        return product

    @staticmethod
    def deactivate(session: Session, product_id: int) -> bool:
        """Soft delete — keeps sales history intact."""
        product = session.query(Product).filter_by(id=product_id).first()
        if not product:
            return False
        product.is_active = False
        session.commit()
        return True

    # ── Stock Management ──────────────────────────────────────────────────────

    @staticmethod
    def adjust_stock(
        session: Session,
        product_id: int,
        quantity_change: float,
        movement_type: str,
        reference: str = None,
        notes: str = None
    ) -> Optional[StockMovement]:
        """
        Adjust stock for a product.
        quantity_change: positive = stock in, negative = stock out
        movement_type: 'purchase', 'sale', 'adjustment', 'return', 'waste'
        """
        product = session.query(Product).filter_by(id=product_id).first()
        if not product:
            return None

        qty_before = product.stock_quantity
        product.stock_quantity += quantity_change

        movement = StockMovement(
            product_id=product_id,
            movement_type=movement_type,
            quantity=quantity_change,
            quantity_before=qty_before,
            quantity_after=product.stock_quantity,
            reference=reference,
            notes=notes
        )
        session.add(movement)
        session.commit()
        return movement

    @staticmethod
    def get_low_stock_products(session: Session) -> list[type[Product]]:
        return (
            session.query(Product)
            .filter(
                Product.is_active == True,
                Product.stock_quantity <= Product.min_stock_level
            )
            .order_by(Product.stock_quantity)
            .all()
        )

    @staticmethod
    def get_stock_movements(session: Session, product_id: int) -> list[type[StockMovement]]:
        return (
            session.query(StockMovement)
            .filter_by(product_id=product_id)
            .order_by(StockMovement.created_at.desc())
            .limit(100)
            .all()
        )

    # ── Categories ────────────────────────────────────────────────────────────

    @staticmethod
    def get_all_categories(session: Session) -> list[type[Category]]:
        return session.query(Category).order_by(Category.name).all()

    @staticmethod
    def create_category(session: Session, name: str, description: str = None) -> Category:
        cat = Category(name=name, description=description)
        session.add(cat)
        session.commit()
        session.refresh(cat)
        return cat
