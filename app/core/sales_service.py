"""
Sales Service
Handles checkout, sale creation, and sales history.
"""
import json
from datetime import date
from dataclasses import dataclass, field
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.models import Sale, SaleItem, Product, Invoice, Client
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
    quantity: float | None  # None = amount not entered yet (weight/volume units)
    unit: str = "pcs"
    tax_rate: int = 0
    discount: float = 0.0
    is_reversal: bool = False  # True for a line that reverses an earlier line on a reopened sale
    has_reversal: bool = False  # True once this original line has been reversed (blocks reversing it again)
    reversal_of: "CartItem | None" = None  # the original line this reverses; live-session only, not persisted

    @property
    def line_total(self):
        if self.quantity is None:
            return 0.0
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
class PaymentEntry(ReceiptEntry):
    """A partial tender applied toward the cart total before it's fully paid.
    Not part of subtotal/total — tracked separately via Cart.paid_total."""
    method: str
    amount: float

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
    def paid_total(self) -> float:
        return round(sum(e.amount for e in self.entries if isinstance(e, PaymentEntry)), 2)

    @property
    def remaining_due(self) -> float:
        return round(self.total - self.paid_total, 2)

    @property
    def item_count(self) -> int:
        return sum(
            entry.quantity for entry in self.entries
            if isinstance(entry, CartItem) and entry.quantity is not None
        )

    def add_product(self, product, quantity: float | None = 1):
        # Pending (amount not yet entered) items always get their own row —
        # merging would leave a stale value once the amount is filled in.
        if quantity is not None:
            # Walk backwards until we hit a subtotal marker.
            for entry in reversed(self.entries):
                if (isinstance(entry, SubtotalMarker) or
                        isinstance(entry, CartItem) and
                        entry.product_id == product.id and
                        entry.quantity is not None):
                    break

        # No matching item in the current section.
        self.entries.append(
            CartItem(
                product_id=product.id,
                product_name=product.name,
                product_barcode=product.barcode or "",
                unit_price=product.price,
                quantity=quantity,
                unit=product.unit,
                tax_rate=product.tax,
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

    def to_snapshot(self) -> str:
        """Serialize entries in order, exactly as displayed, for later replay."""
        data = []
        for entry in self.entries:
            if isinstance(entry, CartItem):
                data.append({
                    "type": "item",
                    "product_id": entry.product_id,
                    "product_name": entry.product_name,
                    "product_barcode": entry.product_barcode,
                    "unit_price": entry.unit_price,
                    "quantity": entry.quantity,
                    "unit": entry.unit,
                    "tax_rate": entry.tax_rate,
                    "discount": entry.discount,
                    "is_reversal": entry.is_reversal,
                    "has_reversal": entry.has_reversal,
                })
            elif isinstance(entry, DiscountEntry):
                data.append({"type": "discount", "amount": entry.amount, "label": entry.label})
            elif isinstance(entry, SubtotalMarker):
                data.append({"type": "subtotal"})
        return json.dumps(data)

    @classmethod
    def from_snapshot(cls, snapshot: str) -> "Cart":
        """Rebuild a cart from a string produced by to_snapshot()."""
        entries: list[ReceiptEntry] = []
        for raw in json.loads(snapshot) if snapshot else []:
            kind = raw.get("type")
            if kind == "item":
                entries.append(CartItem(
                    product_id=raw["product_id"],
                    product_name=raw["product_name"],
                    product_barcode=raw["product_barcode"],
                    unit_price=raw["unit_price"],
                    quantity=raw["quantity"],
                    unit=raw.get("unit", "pcs"),
                    tax_rate=raw.get("tax_rate", 0),
                    discount=raw.get("discount", 0.0),
                    is_reversal=raw.get("is_reversal", False),
                    has_reversal=raw.get("has_reversal", False),
                ))
            elif kind == "discount":
                entries.append(DiscountEntry(amount=raw["amount"], label=raw["label"]))
            elif kind == "subtotal":
                entries.append(SubtotalMarker())
        return cls(entries=entries)


def calc_tax(line_total: float, tax_rate: int) -> float:
    """Return the VAT portion of a tax-inclusive line total."""
    if tax_rate == 0:
        return 0.0
    return round(line_total - line_total / (1 + tax_rate / 100), 2)


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
        notes: str = None,
        payment_breakdown: list[dict] = None,
    ) -> Sale:
        """
        Convert cart to a completed Sale. Deducts stock automatically.
        Returns the saved Sale object.
        """
        if not cart.entries:
            raise ValueError("Empty cart.")

        sale_number = SalesService._generate_sale_number(session)
        change = None
        if payment_method in ("cash", "card") and amount_tendered is not None:
            change = round(amount_tendered - cart.total, 2)

        sale = Sale(
            sale_number=sale_number,
            total_amount=cart.subtotal,
            final_amount=cart.total,
            payment_method=payment_method,
            amount_tendered=amount_tendered,
            change_given=change,
            notes=notes,
            status="completed",
            cart_snapshot=cart.to_snapshot(),
            payment_breakdown=json.dumps(payment_breakdown) if payment_breakdown else None,
        )
        session.add(sale)
        session.flush()  # Get sale.id without committing

        total_tax = 0.0
        for entry in cart.entries:

            if not isinstance(entry, CartItem):
                continue
            tax_amount = calc_tax(entry.line_total, entry.tax_rate)
            total_tax += tax_amount
            sale_item = SaleItem(
                sale_id=sale.id,
                product_id=entry.product_id,
                product_name=entry.product_name,
                product_barcode=entry.product_barcode,
                quantity=entry.quantity,
                unit_price=entry.unit_price,
                tax_rate=entry.tax_rate,
                tax_amount=tax_amount,
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

        sale.tax_amount = round(total_tax, 2)
        session.commit()
        session.refresh(sale)
        return sale

    @staticmethod
    def update_sale(
        session: Session,
        sale_id: int,
        cart: Cart,
        payment_method: str = "cash",
        amount_tendered: float = None,
        notes: str = None,
        payment_breakdown: list[dict] = None,
    ) -> Sale:
        """
        Overwrite an existing completed sale with an edited cart, in place.
        Keeps the same id / sale_number / created_at. Stock is reconciled:
        old line quantities are restored, then the new cart's quantities
        are deducted.
        """
        if not cart.entries:
            raise ValueError("Empty cart.")

        sale = session.query(Sale).filter_by(id=sale_id).first()
        if not sale:
            raise ValueError(f"Sale {sale_id} not found.")

        # Restore stock from the old line items before replacing them.
        for old_item in sale.items:
            ProductService.adjust_stock(
                session,
                product_id=old_item.product_id,
                quantity_change=old_item.quantity,
                movement_type="return",
                reference=sale.sale_number,
                notes="Ticket reopened/edited",
            )

        sale.items = []  # cascade="all, delete-orphan" removes the old SaleItem rows
        session.flush()

        change = None
        if payment_method in ("cash", "card") and amount_tendered is not None:
            change = round(amount_tendered - cart.total, 2)

        sale.total_amount = cart.subtotal
        sale.final_amount = cart.total
        sale.payment_method = payment_method
        sale.amount_tendered = amount_tendered
        sale.change_given = change
        sale.cart_snapshot = cart.to_snapshot()
        sale.payment_breakdown = json.dumps(payment_breakdown) if payment_breakdown else None
        if notes:
            sale.notes = notes

        total_tax = 0.0
        for entry in cart.entries:
            if not isinstance(entry, CartItem):
                continue
            tax_amount = calc_tax(entry.line_total, entry.tax_rate)
            total_tax += tax_amount
            sale_item = SaleItem(
                sale_id=sale.id,
                product_id=entry.product_id,
                product_name=entry.product_name,
                product_barcode=entry.product_barcode,
                quantity=entry.quantity,
                unit_price=entry.unit_price,
                tax_rate=entry.tax_rate,
                tax_amount=tax_amount,
                discount=entry.discount,
                line_total=entry.line_total
            )
            session.add(sale_item)

            ProductService.adjust_stock(
                session,
                product_id=entry.product_id,
                quantity_change=-entry.quantity,
                movement_type="sale",
                reference=sale.sale_number,
            )

        sale.tax_amount = round(total_tax, 2)
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
        client_id: int = None,
        payment_breakdown: list[dict] = None,
    ) -> Invoice:
        if not cart.entries:
            raise ValueError("Cannot finalize an empty cart.")

        sale_number = SalesService._generate_sale_number(session)
        change = None
        if payment_method in ("cash", "card") and amount_tendered is not None:
            change = round(amount_tendered - cart.total, 2)

        sale = Sale(
            sale_number=sale_number,
            total_amount=cart.subtotal,
            final_amount=cart.total,
            payment_method=payment_method,
            amount_tendered=amount_tendered,
            change_given=change,
            notes=notes,
            status="completed",
            cart_snapshot=cart.to_snapshot(),
            payment_breakdown=json.dumps(payment_breakdown) if payment_breakdown else None,
        )
        session.add(sale)
        session.flush()

        total_tax = 0.0
        for entry in cart.entries:

            if not isinstance(entry, CartItem):
                continue
            tax_amount = calc_tax(entry.line_total, entry.tax_rate)
            total_tax += tax_amount
            sale_item = SaleItem(
                sale_id=sale.id,
                product_id=entry.product_id,
                product_name=entry.product_name,
                product_barcode=entry.product_barcode,
                quantity=entry.quantity,
                unit_price=entry.unit_price,
                tax_rate=entry.tax_rate,
                tax_amount=tax_amount,
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

        sale.tax_amount = round(total_tax, 2)

        client = session.query(Client).filter_by(id=client_id).first() if client_id else None

        invoice = Invoice(
            sale_id=sale.id,
            client_id=client_id,
            invoice_number=sale_number.replace("S-", "I-", 1),
            # Snapshot now, once — never re-derived from the live client/sale
            # afterward, so this document can't silently change later.
            client_name=client.name if client else None,
            client_vat_number=client.vatNumber if client else None,
            client_address=client.address if client else None,
            total_amount=sale.total_amount,
            tax_amount=sale.tax_amount,
            final_amount=sale.final_amount,
            line_items_snapshot=cart.to_snapshot(),
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
