"""
Product & Inventory Service
All business logic for managing products and stock.
"""
import logging
from typing import Optional
from sqlalchemy import func
from sqlalchemy.orm import Session, InstrumentedAttribute
from app.models.models import Product, Category, StockMovement, Shortcut, ShortcutItem, Promo, PromoItem

logger = logging.getLogger(__name__)

# Stock isn't counted in on every delivery yet, so sales routinely push it
# below zero; it's only held within these bounds, never refused.
STOCK_MIN = -999999
STOCK_MAX = 999999


def clamp_stock(quantity: float) -> float:
    return max(STOCK_MIN, min(STOCK_MAX, quantity))


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
    def get_by_barcode(session: Session, barcode: str, include_inactive: bool = False) -> type[Product] | None:
        """include_inactive: also match deactivated products — `barcode` is
        unique across all of them, so a duplicate check must see those too."""
        query = session.query(Product).filter_by(barcode=barcode)
        if not include_inactive:
            query = query.filter_by(is_active=True)
        return query.first()

    @staticmethod
    def search(session: Session, query: str, include_inactive: bool = False) -> list[type[Product]]:
        """Search by name or barcode."""
        term = f"%{query}%"
        q = session.query(Product).filter(
            (Product.barcode.startswith(term)) | (Product.name.startswith(term))
        )
        if not include_inactive:
            q = q.filter(Product.is_active == True)
        return (
            q.order_by(Product.barcode)
            .limit(50)
            .all()
        )

    @staticmethod
    def create(session: Session, **kwargs) -> Product:
        product = Product(**kwargs)
        session.add(product)
        session.commit()
        session.refresh(product)
        logger.info("Product created: %s %r, barcode %s, price %.2f",
                    product.id, product.name, product.barcode, product.price)
        return product

    @staticmethod
    def update(session: Session, product_id: int, **kwargs) -> Product | None:
        product = session.query(Product).filter_by(id=product_id).first()
        if not product:
            logger.warning("Product update: product %s not found", product_id)
            return None
        changes = {
            key: (getattr(product, key, None), value)
            for key, value in kwargs.items()
            if getattr(product, key, None) != value
        }
        for key, value in kwargs.items():
            setattr(product, key, value)
        session.commit()
        session.refresh(product)
        if changes:
            logger.info("Product updated: %s %r: %s", product.id, product.name,
                        ", ".join(f"{k} {old!r} -> {new!r}" for k, (old, new) in changes.items()))
        return product

    @staticmethod
    def deactivate(session: Session, product_id: int) -> bool:
        """Soft delete — keeps sales history intact."""
        product = session.query(Product).filter_by(id=product_id).first()
        if not product:
            logger.warning("Product deactivate: product %s not found", product_id)
            return False
        product.is_active = False
        session.commit()
        logger.info("Product deactivated: %s %r", product.id, product.name)
        return True

    @staticmethod
    def reactivate(session: Session, product_id: int) -> bool:
        """Undoes deactivate(). Returns False if the product doesn't exist."""
        product = session.query(Product).filter_by(id=product_id).first()
        if not product:
            logger.warning("Product reactivate: product %s not found", product_id)
            return False
        product.is_active = True
        session.commit()
        logger.info("Product reactivated: %s %r", product.id, product.name)
        return True

    INTERNAL_BARCODE_PREFIX = "2060"

    @staticmethod
    def _ean13_check_digit(first12: str) -> str:
        total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(first12))
        return str((10 - total % 10) % 10)

    @staticmethod
    def generate_barcode(session: Session, barcode_type: str = "ean13") -> str:
        """Next free internal EAN-13 (INTERNAL_BARCODE_PREFIX + sequence +
        check digit). Checks inactive products too, since `barcode` is
        unique across the whole table."""
        if barcode_type != "ean13":
            raise ValueError(f"Unsupported barcode type: {barcode_type!r}")

        prefix = ProductService.INTERNAL_BARCODE_PREFIX
        body_len = 12 - len(prefix)
        used = {
            int(b[len(prefix):12])
            for (b,) in session.query(Product.barcode)
                               .filter(Product.barcode.startswith(prefix))
            if len(b) == 13 and b.isdigit()
        }

        # Continue after the highest code issued so far; only if that runs
        # off the end, fall back to the lowest gap.
        max_seq = 10 ** body_len - 1
        seq = max(used, default=0) + 1
        if seq > max_seq:
            seq = next((n for n in range(1, max_seq + 1) if n not in used), None)
            if seq is None:
                logger.error("No free internal barcodes left (prefix %s)", prefix)
                raise RuntimeError("No free internal barcodes left")

        first12 = f"{prefix}{seq:0{body_len}d}"
        return first12 + ProductService._ean13_check_digit(first12)


    # ── Stock Management ──────────────────────────────────────────────────────

    # Commented out for now: nothing in the app calls these yet (only tests did).
    # @staticmethod
    # def adjust_stock(
    #     session: Session,
    #     product_id: int,
    #     quantity_change: float,
    #     movement_type: str,
    #     reference: str = None,
    #     notes: str = None
    # ) -> Optional[StockMovement]:
    #     """
    #     Adjust stock for a product, committed on its own — for a standalone
    #     adjustment (inventory screen). Inside a larger save, use move_stock().
    #     quantity_change: positive = stock in, negative = stock out
    #     movement_type: 'purchase', 'sale', 'adjustment', 'return', 'waste'
    #     """
    #     movement = ProductService.move_stock(
    #         session, product_id, quantity_change, movement_type, reference, notes
    #     )
    #     if movement is not None:
    #         session.commit()
    #         logger.info("Stock adjusted: product %s %+g (%s) -> %g%s",
    #                     product_id, quantity_change, movement_type, movement.quantity_after,
    #                     f", {notes}" if notes else "")
    #     return movement

    @staticmethod
    def change_stock(
        session: Session,
        product_id: int,
        quantity_change: float,
        reference: str = None,
    ) -> tuple[InstrumentedAttribute, InstrumentedAttribute] | None:
        """Change a product's stock (held within STOCK_MIN..STOCK_MAX) so it
        commits or rolls back with the caller's transaction. Used for every
        till sale line: a sale takes its quantity off, a mistake (reversal
        line, negative quantity) puts it back.
        Returns (before, after), or None if the product doesn't exist."""
        product = session.query(Product).filter_by(id=product_id).first()
        if not product:
            logger.warning("Stock change skipped: product %s not found (%s)", product_id, reference)
            return None

        qty_before = product.stock_quantity
        product.stock_quantity = clamp_stock(qty_before + quantity_change)
        if product.stock_quantity != qty_before + quantity_change:
            logger.info("Stock for product %s %r held at %g (change %+g)",
                        product.id, product.name, product.stock_quantity, quantity_change)
        session.flush()
        logger.debug("Stock change: product %s %+g (%s): %g -> %g",
                     product_id, product.stock_quantity - qty_before, reference,
                     qty_before, product.stock_quantity)
        return qty_before, product.stock_quantity

    @staticmethod
    def move_stock(
        session: Session,
        product_id: int,
        quantity_change: float,
        movement_type: str,
        reference: str = None,
        notes: str = None
    ) -> Optional[StockMovement]:
        """change_stock() plus a StockMovement row, for the rare manual
        changes worth a history (purchase, waste, adjustment) — not for till
        sales. Also only flushed, never committed."""
        changed = ProductService.change_stock(session, product_id, quantity_change, reference)
        if changed is None:
            return None
        qty_before, qty_after = changed
        quantity_change = qty_after - qty_before

        movement = StockMovement(
            product_id=product_id,
            movement_type=movement_type,
            quantity=quantity_change,
            quantity_before=qty_before,
            quantity_after=qty_after,
            reference=reference,
            notes=notes
        )
        session.add(movement)
        session.flush()
        return movement

    # Commented out for now: unused (the inventory Low Stock filter uses Product.is_low_stock).
    # @staticmethod
    # def get_low_stock_products(session: Session) -> list[Product]:
    #     return (
    #         session.query(Product)
    #         .filter(
    #             Product.is_active == True,
    #             Product.stock_quantity <= Product.min_stock_level
    #         )
    #         .order_by(Product.stock_quantity)
    #         .all()
    #     )
    #
    # @staticmethod
    # def get_stock_movements(session: Session, product_id: int) -> list[StockMovement]:
    #     return (
    #         session.query(StockMovement)
    #         .filter_by(product_id=product_id)
    #         .order_by(StockMovement.created_at.desc())
    #         .limit(100)
    #         .all()
    #     )

    # ── Categories ────────────────────────────────────────────────────────────

    @staticmethod
    def get_all_categories(session: Session) -> list[Category]:
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
        logger.info("Category created: %s %r", cat.id, cat.name)
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
        old_name = cat.name
        cat.name = new_name
        session.commit()
        session.refresh(cat)
        logger.info("Category renamed: %s %r -> %r", cat.id, old_name, new_name)
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
        uncategorised = session.query(Product).filter_by(category_id=category_id).update(
            {Product.category_id: None}, synchronize_session=False
        )
        name = cat.name
        session.delete(cat)
        session.commit()
        logger.info("Category deleted: %s %r (%d products uncategorised)", category_id, name, uncategorised)
        return True

    # ── Promos ────────────────────────────────────────────────────────────────

    @staticmethod
    def get_all_promos(session: Session) -> list[Promo]:
        return session.query(Promo).order_by(Promo.name).all()

    @staticmethod
    def _promo_by_name(session: Session, name: str) -> Promo | None:
        """Case-insensitive lookup so 'New Year Promo' and 'new year promo' are the same promo."""
        return (
            session.query(Promo)
            .filter(func.lower(Promo.name) == name.strip().lower())
            .first()
        )

    @staticmethod
    def create_promo(
        session: Session, name: str, start_date=None, end_date=None, is_active: bool = True,
    ) -> Promo | None:
        """Create a promo. Returns None if the name is blank or already taken."""
        name = name.strip()
        if not name or ProductService._promo_by_name(session, name):
            return None
        promo = Promo(name=name, start_date=start_date, end_date=end_date, is_active=is_active)
        session.add(promo)
        session.commit()
        session.refresh(promo)
        logger.info("Promo created: %s %r (%s to %s, active=%s)",
                    promo.id, promo.name, start_date, end_date, is_active)
        return promo

    @staticmethod
    def update_promo(
        session: Session, promo_id: int, name: str, start_date=None, end_date=None, is_active: bool = True,
    ) -> Promo | None:
        """
        Update an existing promo. Returns None if it doesn't exist, the new
        name is blank, or the name is already used by another promo.
        """
        name = name.strip()
        if not name:
            return None
        promo = session.query(Promo).filter_by(id=promo_id).first()
        if not promo:
            return None
        clash = (
            session.query(Promo)
            .filter(func.lower(Promo.name) == name.lower(), Promo.id != promo_id)
            .first()
        )
        if clash:
            return None
        promo.name = name
        promo.start_date = start_date
        promo.end_date = end_date
        promo.is_active = is_active
        session.commit()
        session.refresh(promo)
        logger.info("Promo updated: %s %r (%s to %s, active=%s)",
                    promo.id, promo.name, start_date, end_date, is_active)
        return promo

    @staticmethod
    def delete_promo(session: Session, promo_id: int) -> bool:
        """Delete a promo and its per-product discounts (promo_items cascades).
        Returns False if it doesn't exist."""
        promo = session.query(Promo).filter_by(id=promo_id).first()
        if not promo:
            return False
        name = promo.name
        session.delete(promo)
        session.commit()
        logger.info("Promo deleted: %s %r", promo_id, name)
        return True

    @staticmethod
    def get_promo_item_for_product(session: Session, product_id: int) -> PromoItem | None:
        return session.query(PromoItem).filter_by(product_id=product_id).first()

    @staticmethod
    def get_promo_items(session: Session, promo_id: int) -> list[PromoItem]:
        """This promo's per-product discounts, with each item's product
        eagerly usable (same session) and ordered by product name."""
        return (
            session.query(PromoItem)
            .join(Product)
            .filter(PromoItem.promo_id == promo_id)
            .order_by(Product.name)
            .all()
        )

    @staticmethod
    def set_promo_items(session: Session, promo_id: int, items: list[dict]) -> None:
        """Replace a promo's whole product list in one shot.
        `items` = [{"product_id": int, "discount_type": "percent"|"fixed", "discount_value": float}, ...].
        A product belongs to at most one promo at a time, so adding it here
        drops it from whatever other promo it was attached to."""
        wanted_ids = {it["product_id"] for it in items}

        if wanted_ids:
            moved = session.query(PromoItem).filter(
                PromoItem.product_id.in_(wanted_ids), PromoItem.promo_id != promo_id
            ).delete(synchronize_session=False)
            if moved:
                logger.info("Promo %s: %d products taken over from other promos", promo_id, moved)

        session.query(PromoItem).filter(
            PromoItem.promo_id == promo_id, ~PromoItem.product_id.in_(wanted_ids)
        ).delete(synchronize_session=False)

        existing = {
            pi.product_id: pi
            for pi in session.query(PromoItem).filter_by(promo_id=promo_id).all()
        }
        for it in items:
            pid = it["product_id"]
            if pid in existing:
                existing[pid].discount_type = it["discount_type"]
                existing[pid].discount_value = it["discount_value"]
            else:
                session.add(PromoItem(
                    promo_id=promo_id, product_id=pid,
                    discount_type=it["discount_type"], discount_value=it["discount_value"],
                ))
        session.commit()
        logger.info("Promo %s items set: %d products", promo_id, len(items))

    @staticmethod
    def get_all_shortcuts(session: Session) -> list[Shortcut]:
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
        logger.info("Shortcut created: %s %r", sc.id, sc.name)
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
        old_name = sc.name
        sc.name = new_name
        session.commit()
        session.refresh(sc)
        logger.info("Shortcut renamed: %s %r -> %r", sc.id, old_name, new_name)
        return sc

    @staticmethod
    def delete_shortcut(session: Session, shortcut_id: int) -> bool:
        """Delete a shortcut and its items (cascade). Returns False if it doesn't exist."""
        sc = session.query(Shortcut).filter_by(id=shortcut_id).first()
        if not sc:
            return False
        name = sc.name
        session.delete(sc)
        session.commit()
        logger.info("Shortcut deleted: %s %r", shortcut_id, name)
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
        skipped = len(product_ids or []) - len(ordered)
        logger.info("Shortcut %s items set: %d products%s", shortcut_id, len(ordered),
                    f" ({skipped} unknown/duplicate ids skipped)" if skipped else "")
        return True


