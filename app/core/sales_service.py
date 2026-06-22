"""
Sales Service
Handles checkout, sale creation, and sales history.
"""
from datetime import date
from dataclasses import dataclass, field
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.models import Sale, SaleItem, Product, Invoice
from app.core.product_service import ProductService


@dataclass
class CartItem:
    """Represents a single item in the active shopping cart."""
    product_id: int
    product_name: str
    product_barcode: str
    unit_price: float
    quantity: float
    unit: str = "pcs"
    discount: float = 0.0

    @property
    def line_total(self) -> float:
        return round((self.unit_price * self.quantity) - self.discount, 2)


@dataclass
class Cart:
    items: dict[int, CartItem] = field(default_factory=dict)  # key = product_id
    global_discount: float = 0.0

    @property
    def subtotal(self) -> float:
        return round(sum(i.line_total for i in self.items.values()), 2)

    @property
    def total(self) -> float:
        return round(self.subtotal - self.global_discount, 2)

    @property
    def item_count(self) -> int:
        return sum(int(i.quantity) for i in self.items.values())

    def add_product(self, product: Product, quantity: float = 1.0):
        """Add a product or increase quantity if already in cart."""
        if product.id in self.items:
            self.items[product.id].quantity += quantity
        else:
            self.items[product.id] = (CartItem(
                product_id=product.id,
                product_name=product.name,
                product_barcode=product.barcode or "",
                unit_price=product.price,
                quantity=quantity,
                unit=product.unit
            ))

    def remove_item(self, product_id):
        self.items.pop(product_id, None)

    def update_quantity(self, product_id, quantity):
        if product_id in self.items:
            self.items[product_id].quantity = quantity

    def increase_quantity(self, product_id: int):
        if product_id in self.items:
            self.items[product_id].quantity += 1

    def clear(self):
        self.items.clear()
        self.global_discount = 0.0


class SalesService:

    @staticmethod
    def _generate_sale_number(session: Session) -> str:
        today = date.today().strftime("%Y%m%d")
        count = session.query(func.count(Sale.id)).filter(
            func.date(Sale.created_at) == date.today()
        ).scalar() or 0
        return f"S-{today}-{count + 1:04d}"


    @staticmethod
    def finalize_sale(
        session: Session,
        cart: Cart,
        payment_method: str = "cash",
        amount_tendered: float = None,
        notes: str = None
    ) -> Sale:
        """
        Convert cart to a completed Sale. Deducts stock automatically.
        Returns the saved Sale object.
        """
        if not cart.items:
            raise ValueError("Cannot finalize an empty cart.")

        sale_number = SalesService._generate_sale_number(session)
        change = None
        if payment_method == "cash" and amount_tendered is not None:
            change = round(amount_tendered - cart.total, 2)

        sale = Sale(
            sale_number=sale_number,
            total_amount=cart.subtotal,
            discount_amount=cart.global_discount,
            final_amount=cart.total,
            payment_method=payment_method,
            amount_tendered=amount_tendered,
            change_given=change,
            notes=notes,
            status="completed"
        )
        session.add(sale)
        session.flush()  # Get sale.id without committing

        for cart_item in cart.items.values():
            # Add sale line item
            sale_item = SaleItem(
                sale_id=sale.id,
                product_id=cart_item.product_id,
                product_name=cart_item.product_name,
                product_barcode=cart_item.product_barcode,
                quantity=cart_item.quantity,
                unit_price=cart_item.unit_price,
                discount=cart_item.discount,
                line_total=cart_item.line_total
            )
            session.add(sale_item)

            # Deduct stock
            ProductService.adjust_stock(
                session,
                product_id=cart_item.product_id,
                quantity_change=-cart_item.quantity,
                movement_type="sale",
                reference=sale_number
            )

        session.commit()
        session.refresh(sale)
        return sale

    @staticmethod
    def void_sale(session: Session, sale_id: int, notes: str = None) -> bool:
        """Void a sale and restore stock."""
        sale = session.query(Sale).filter_by(id=sale_id, status="completed").first()
        if not sale:
            return False

        for item in sale.items:
            ProductService.adjust_stock(
                session,
                product_id=item.product_id,
                quantity_change=item.quantity,
                movement_type="return",
                reference=sale.sale_number,
                notes="Sale voided"
            )

        sale.status = "voided"
        if notes:
            sale.notes = (sale.notes or "") + f"\nVoided: {notes}"
        session.commit()
        return True

    @staticmethod
    def finalize_invoice(
        session: Session,
        cart: Cart,
        payment_method: str = "cash",
        amount_tendered: float = None,
        notes: str = None,
        client_id: int = None
    ) -> Invoice:
        if not cart.items:
            raise ValueError("Cannot finalize an empty cart.")

        sale_number = SalesService._generate_sale_number(session)
        change = None
        if payment_method == "cash" and amount_tendered is not None:
            change = round(amount_tendered - cart.total, 2)

        sale = Sale(
            sale_number=sale_number,
            total_amount=cart.subtotal,
            discount_amount=cart.global_discount,
            final_amount=cart.total,
            payment_method=payment_method,
            amount_tendered=amount_tendered,
            change_given=change,
            notes=notes,
            status="completed"
        )
        session.add(sale)
        session.flush()

        for cart_item in cart.items.values():
            session.add(SaleItem(
                sale_id=sale.id,
                product_id=cart_item.product_id,
                product_name=cart_item.product_name,
                product_barcode=cart_item.product_barcode,
                quantity=cart_item.quantity,
                unit_price=cart_item.unit_price,
                discount=cart_item.discount,
                line_total=cart_item.line_total
            ))
            ProductService.adjust_stock(
                session,
                product_id=cart_item.product_id,
                quantity_change=-cart_item.quantity,
                movement_type="sale",
                reference=sale_number
            )

        invoice = Invoice(
            sale_id=sale.id,
            client_id=client_id,
            invoice_number=sale_number.replace("S-", "I-", 1)
        )
        session.add(invoice)
        session.commit()
        session.refresh(sale)
        session.refresh(invoice)
        return invoice

    # ── Reports / Queries ─────────────────────────────────────────────────────

    @staticmethod
    def get_sales_for_date(session: Session, target_date: date) -> list[Sale]:
        return (
            session.query(Sale)
            .filter(func.date(Sale.created_at) == target_date)
            .filter(Sale.status == "completed")
            .order_by(Sale.created_at.desc())
            .all()
        )

    @staticmethod
    def get_daily_summary(session: Session, target_date: date) -> dict:
        sales = SalesService.get_sales_for_date(session, target_date)
        total_revenue = sum(s.final_amount for s in sales)
        total_transactions = len(sales)
        avg_transaction = total_revenue / total_transactions if total_transactions else 0

        return {
            "date": target_date,
            "total_revenue": round(total_revenue, 2),
            "total_transactions": total_transactions,
            "average_transaction": round(avg_transaction, 2),
            "cash_sales": sum(s.final_amount for s in sales if s.payment_method == "cash"),
            "card_sales": sum(s.final_amount for s in sales if s.payment_method == "card"),
        }

    @staticmethod
    def get_sales_range(session: Session, start: date, end: date) -> list[Sale]:
        return (
            session.query(Sale)
            .filter(
                func.date(Sale.created_at) >= start,
                func.date(Sale.created_at) <= end,
                Sale.status == "completed"
            )
            .order_by(Sale.created_at.desc())
            .all()
        )
