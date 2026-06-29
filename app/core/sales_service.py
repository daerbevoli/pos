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
class ReceiptEntry:
    pass


@dataclass
class CartItem(ReceiptEntry):
    product_id: int
    product_name: str
    product_barcode: str
    unit_price: float
    quantity: int
    unit: str = "pcs"
    discount: float = 0.0

    @property
    def line_total(self):
        return round((self.unit_price * self.quantity) - self.discount, 2)




@dataclass
class SubtotalMarker(ReceiptEntry):
    pass


@dataclass
class DiscountEntry(ReceiptEntry):
    amount: float   # always positive; the actual currency value deducted
    label: str      # display string, e.g. "10%" or "€5.00"

    @property
    def line_total(self) -> float:
        return -round(self.amount, 2)

@dataclass
class Cart:
    entries: list[ReceiptEntry] = field(default_factory=list)

    @property
    def subtotal(self):
        return round(
            sum(
                entry.line_total
                for entry in self.entries
                if isinstance(entry, (CartItem, DiscountEntry))
            ),
            2,
        )

    @property
    def total(self) -> float:
        return round(self.subtotal, 2)

    @property
    def item_count(self) -> int:
        return sum(entry.quantity for entry in self.entries if isinstance(entry, CartItem))

    def add_product(self, product, quantity=1):
        # Walk backwards until we hit a subtotal marker.
        for entry in reversed(self.entries):
            if isinstance(entry, SubtotalMarker):
                break

            if (
                    isinstance(entry, CartItem)
                    and entry.product_id == product.id
            ):
                entry.quantity += quantity
                return

        # No matching item in the current section.
        self.entries.append(
            CartItem(
                product_id=product.id,
                product_name=product.name,
                product_barcode=product.barcode or "",
                unit_price=product.price,
                quantity=quantity,
                unit=product.unit,
            )
        )


    def add_subtotal(self):
        self.entries.append(SubtotalMarker())

    def clear_subtotals(self):
        self.entries = [
            e for e in self.entries
            if not isinstance(e, SubtotalMarker)
        ]

    def remove_item(self, product_id):
        for i, entry in enumerate(self.entries):
            if isinstance(entry, CartItem) and entry.product_id == product_id:
                self.entries.pop(i)
                return

    def clear(self):
        self.entries.clear()


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
        if not cart.entries:
            raise ValueError("Empty cart.")

        sale_number = SalesService._generate_sale_number(session)
        change = None
        if payment_method == "cash" and amount_tendered is not None:
            change = round(amount_tendered - cart.total, 2)

        sale = Sale(
            sale_number=sale_number,
            total_amount=cart.subtotal,
            final_amount=cart.total,
            payment_method=payment_method,
            amount_tendered=amount_tendered,
            change_given=change,
            notes=notes,
            status="completed"
        )
        session.add(sale)
        session.flush()  # Get sale.id without committing

        for entry in cart.entries:

            if not isinstance(entry, CartItem):
                continue
            # Add sale line item
            sale_item = SaleItem(
                sale_id=sale.id,
                product_id=entry.product_id,
                product_name=entry.product_name,
                product_barcode=entry.product_barcode,
                quantity=entry.quantity,
                unit_price=entry.unit_price,
                discount=entry.discount,
                line_total=entry.line_total
            )
            session.add(sale_item)

            # Deduct stock
            ProductService.adjust_stock(
                session,
                product_id=entry.product_id,
                quantity_change=-entry.quantity,
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
        if not cart.entries:
            raise ValueError("Cannot finalize an empty cart.")

        sale_number = SalesService._generate_sale_number(session)
        change = None
        if payment_method == "cash" and amount_tendered is not None:
            change = round(amount_tendered - cart.total, 2)

        sale = Sale(
            sale_number=sale_number,
            total_amount=cart.subtotal,
            final_amount=cart.total,
            payment_method=payment_method,
            amount_tendered=amount_tendered,
            change_given=change,
            notes=notes,
            status="completed"
        )
        session.add(sale)
        session.flush()

        for entry in cart.entries:

            if not isinstance(entry, CartItem):
                continue
            # Add sale line item
            sale_item = SaleItem(
                sale_id=sale.id,
                product_id=entry.product_id,
                product_name=entry.product_name,
                product_barcode=entry.product_barcode,
                quantity=entry.quantity,
                unit_price=entry.unit_price,
                discount=entry.discount,
                line_total=entry.line_total
            )

            session.add(sale_item)
            ProductService.adjust_stock(
                session,
                product_id=entry.product_id,
                quantity_change=-entry.quantity,
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
