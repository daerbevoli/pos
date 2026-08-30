"""
Product & Inventory Service
All business logic for managing products and stock.
"""
from typing import Optional
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.models.models import Product, Category, StockMovement, Shortcut, ShortcutItem
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
                (Product.barcode.startswith(term)) | (Product.name.startswith(term))
            )
            .order_by(Product.barcode)
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
    def _category_by_name(session: Session, name: str) -> Category | None:
        """Case-insensitive lookup so 'Bakery' and 'bakery' are the same category."""
        return (
            session.query(Category)
            .filter(func.lower(Category.name) == name.strip().lower())
            .first()
        )

    @staticmethod
    def create_category(session: Session, name: str, description: str = None) -> Category | None:
        """Create a category. Returns None if the name is blank or already taken."""
        name = name.strip()
        if not name or ProductService._category_by_name(session, name):
            return None
        cat = Category(name=name, description=description)
        session.add(cat)
        session.commit()
        session.refresh(cat)
        return cat

    @staticmethod
    def rename_category(session: Session, category_id: int, new_name: str) -> Category | None:
        """
        Rename an existing category. Returns None if the category doesn't exist,
        the new name is blank, or the name is already used by another category.
        """
        new_name = new_name.strip()
        if not new_name:
            return None
        cat = session.query(Category).filter_by(id=category_id).first()
        if not cat:
            return None
        clash = (
            session.query(Category)
            .filter(
                func.lower(Category.name) == new_name.lower(),
                Category.id != category_id,
            )
            .first()
        )
        if clash:
            return None
        cat.name = new_name
        session.commit()
        session.refresh(cat)
        return cat

    @staticmethod
    def delete_category(session: Session, category_id: int) -> bool:
        """
        Delete a category. Any products in it are left uncategorised
        (category_id set to NULL). Returns False if it doesn't exist.
        """
        cat = session.query(Category).filter_by(id=category_id).first()
        if not cat:
            return False
        session.query(Product).filter_by(category_id=category_id).update(
            {Product.category_id: None}, synchronize_session=False
        )
        session.delete(cat)
        session.commit()
        return True

    @staticmethod
    def get_all_shortcuts(session: Session) -> list[type[Shortcut]]:
        return session.query(Shortcut).order_by(Shortcut.name).all()

    @staticmethod
    def _shortcut_by_name(session: Session, name: str) -> Shortcut | None:
        """Case-insensitive lookup so 'Bakery' and 'bakery' are the same category."""
        return (
            session.query(Shortcut)
            .filter(func.lower(Shortcut.name) == name.strip().lower())
            .first()
        )

    @staticmethod
    def create_shortcut(session: Session, name: str) -> Shortcut | None:
        """Create a shortcut. Returns None if the name is blank or already taken."""
        name = name.strip()
        if not name or ProductService._shortcut_by_name(session, name):
            return None
        sc = Shortcut(name=name)
        session.add(sc)
        session.commit()
        session.refresh(sc)
        return sc

    @staticmethod
    def get_shortcut(session: Session, shortcut_id: int) -> Shortcut | None:
        return session.query(Shortcut).filter_by(id=shortcut_id).first()

    @staticmethod
    def get_shortcut_product_ids(session: Session, shortcut_id: int) -> list[int]:
        """Ordered product ids for a shortcut (position order). Empty if it doesn't exist."""
        sc = session.query(Shortcut).filter_by(id=shortcut_id).first()
        if not sc:
            return []
        return [item.product_id for item in sc.items]

    @staticmethod
    def rename_shortcut(session: Session, shortcut_id: int, new_name: str) -> Shortcut | None:
        """
        Rename an existing shortcut. Returns None if the shortcut doesn't exist,
        the new name is blank, or the name is already used by another shortcut.
        """
        new_name = new_name.strip()
        if not new_name:
            return None
        sc = session.query(Shortcut).filter_by(id=shortcut_id).first()
        if not sc:
            return None
        clash = (
            session.query(Shortcut)
            .filter(
                func.lower(Shortcut.name) == new_name.lower(),
                Shortcut.id != shortcut_id,
            )
            .first()
        )
        if clash:
            return None
        sc.name = new_name
        session.commit()
        session.refresh(sc)
        return sc

    @staticmethod
    def delete_shortcut(session: Session, shortcut_id: int) -> bool:
        """Delete a shortcut and its items (cascade). Returns False if it doesn't exist."""
        sc = session.query(Shortcut).filter_by(id=shortcut_id).first()
        if not sc:
            return False
        session.delete(sc)
        session.commit()
        return True

    @staticmethod
    def set_shortcut_items(session: Session, shortcut_id: int, product_ids: list[int]) -> bool:
        """
        Replace a shortcut's item list wholesale with `product_ids`, in order.
        Covers add / remove / reorder in one call. Ids that don't resolve to a
        product (or repeats) are skipped. Returns False if the shortcut is gone.
        """
        sc = session.query(Shortcut).filter_by(id=shortcut_id).first()
        if not sc:
            return False

        valid_ids = {
            pid for (pid,) in session.query(Product.id).filter(Product.id.in_(product_ids or [])).all()
        } if product_ids else set()

        seen: set[int] = set()
        ordered = []
        for pid in product_ids or []:
            if pid in valid_ids and pid not in seen:
                seen.add(pid)
                ordered.append(pid)

        # Clear then re-add. The explicit flush() between the two makes the
        # DELETEs land before the INSERTs, so re-adding a product that was
        # already in the shortcut doesn't collide on the (shortcut_id,
        # product_id) unique constraint mid-flush.
        session.query(ShortcutItem).filter_by(shortcut_id=shortcut_id).delete(
            synchronize_session="fetch"
        )
        session.flush()
        for position, pid in enumerate(ordered):
            session.add(ShortcutItem(shortcut_id=shortcut_id, product_id=pid, position=position))
        session.commit()
        return True


