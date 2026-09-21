"""
Sales Service
Handles checkout, sale creation, and sales history.
"""
import json
from datetime import date, datetime, timedelta
from dataclasses import dataclass, field
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.models import Sale, SaleItem, Invoice, Client
from app.core.product_service import ProductService
from app.core.settings_service import get_store_data

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
    base_tax_rate: int = 0  # the product's own rate; tax_rate may be zeroed by retax_for_client()
    base_unit_price: float = 0.0  # the domestic (VAT-incl.) price; unit_price may be netted down by retax_for_client()
    is_reversal: bool = False  # True for a line that reverses an earlier line on a reopened sale
    has_reversal: bool = False  # True once this original line has been reversed (blocks reversing it again)
    reversal_of: "CartItem | None" = None  # the original line this reverses; live-session only, not persisted
    is_open_price: bool = False  # True = unit_price is typed in per sale rather than fixed on the product
    promo_name: str | None = None    # label of the Promo attached to the product when this line was added, if any
    promo_type: str | None = None    # "percent" | "fixed" | None — copied from Promo.discount_type
    promo_value: float = 0.0         # copied from Promo.discount_value

    @property
    def pending(self) -> bool:
        """True while this line still needs an amount typed in before it can
        be paid: a weight/volume item awaiting its quantity, or an
        open-price item awaiting its price."""
        return self.quantity is None or (self.is_open_price and self.unit_price == 0.0)

    @property
    def promo_discount(self) -> float:
        """Discount contributed by the attached promo, recomputed live off the
        current quantity/unit_price so it stays correct even for a pending
        weight/open-price item whose amount is filled in after this line
        already exists. Materialized into a real DiscountEntry by
        Cart.sync_promo_discounts() — not folded into line_total, so the
        item's own row keeps showing its full, undiscounted price and the
        promo shows up as its own labeled line, same as a manual discount.
        Sign-aware so a reversal line (negative quantity) yields a negative
        discount that exactly undoes the original line's."""
        if self.promo_type is None or self.quantity is None:
            return 0.0
        raw = self.unit_price * self.quantity
        if self.promo_type == "percent":
            return round(raw * self.promo_value / 100, 2)
        fixed = self.promo_value * self.quantity
        return round(min(fixed, raw), 2) if raw >= 0 else round(max(fixed, raw), 2)

    @property
    def line_total(self):
        if self.quantity is None:
            return 0.0
        return round(self.unit_price * self.quantity, 2)

@dataclass
class SubtotalMarker(ReceiptEntry):
    pass


@dataclass
class DiscountEntry(ReceiptEntry):
    amount: float   # positive = deducts; negative only for a promo entry undoing a reversed line's discount
    label: str      # display string, e.g. "10%" or "€5.00" or a promo's name
    is_promo: bool = False  # True = synthesized by Cart.sync_promo_discounts(), safe to drop and regenerate

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
    is_domestic: bool = True  # whether the attached client is Belgian; affects unit_price/tax_rate

    def _effective_price(self, base_price: float, base_tax_rate: int) -> float:
        """The price actually charged: the domestic (VAT-incl.) price as-is
        for a Belgian client, netted of VAT for a non-domestic one — the
        store's own margin is unaffected either way, only the VAT portion
        it would otherwise have collected and remitted."""
        if self.is_domestic or base_tax_rate == 0:
            return base_price
        return round(base_price / (1 + base_tax_rate / 100), 2)

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

        if quantity is not None:
            # Walk backwards until we hit a subtotal marker.
            for entry in reversed(self.entries):
                if (isinstance(entry, SubtotalMarker) or
                        isinstance(entry, CartItem) and
                        entry.product_id == product.id and
                        entry.quantity is not None):
                    break

        # No matching item in the current section.
        promo_item = product.active_promo_item
        self.entries.append(
            CartItem(
                product_id=product.id,
                product_name=product.name,
                product_barcode=product.barcode or "",
                unit_price=self._effective_price(product.price, product.tax),
                quantity=quantity,
                unit=product.unit,
                tax_rate=product.tax if self.is_domestic else 0,
                base_tax_rate=product.tax,
                base_unit_price=product.price,
                is_open_price=product.is_open_price,
                promo_name=promo_item.promo.name if promo_item else None,
                promo_type=promo_item.discount_type if promo_item else None,
                promo_value=promo_item.discount_value if promo_item else 0.0,
            )
        )
        self.sync_promo_discounts()

    def sync_promo_discounts(self):
        """Rebuild every promo-driven DiscountEntry from scratch off each
        CartItem's *current* promo_discount. Call this after anything that
        could change a promo'd line's amount: add_product() already does,
        but also after +/- quantity, filling in a pending weight/open-price
        item's amount, reversing a line, or removing one — see callers in
        pos_screen.py. Safe to call repeatedly: it drops every existing
        is_promo entry first, so it never drifts or duplicates.

        A line with has_reversal set is skipped — once a reopened ticket's
        line has been voided by an (appended, negative-quantity) reversal,
        its promo discount line disappears rather than getting a second,
        offsetting entry next to it. The reversal line itself never carries
        promo fields, so it wouldn't generate one anyway."""
        self.entries = [e for e in self.entries if not (isinstance(e, DiscountEntry) and e.is_promo)]
        result = []
        for entry in self.entries:
            result.append(entry)
            if isinstance(entry, CartItem) and not entry.has_reversal and entry.promo_discount != 0:
                result.append(DiscountEntry(amount=entry.promo_discount, label=entry.promo_name, is_promo=True))
        self.entries = result

    def retax_for_client(self, is_domestic: bool):
        """Re-derives every item's effective VAT rate and price for the
        client now attached to the sale: zero-rated and netted of VAT (EU
        reverse-charge / non-EU export) once a non-domestic client is on
        it, restored to the product's own rate/price otherwise. The
        store's margin is unaffected — only the VAT portion changes. Call
        whenever the attached client changes — see pos_screen.set_client()."""
        self.is_domestic = is_domestic
        for entry in self.entries:
            if isinstance(entry, CartItem):
                entry.tax_rate = entry.base_tax_rate if is_domestic else 0
                entry.unit_price = self._effective_price(entry.base_unit_price, entry.base_tax_rate)

    def set_open_price(self, entry: "CartItem", amount: float):
        """Records the cashier-typed price for a pending open-price line,
        applying the sale's current client VAT treatment the same way
        retax_for_client does."""
        entry.base_unit_price = amount
        entry.unit_price = self._effective_price(amount, entry.base_tax_rate)

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
                self.sync_promo_discounts()
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
                    "base_tax_rate": entry.base_tax_rate,
                    "base_unit_price": entry.base_unit_price,
                    "is_reversal": entry.is_reversal,
                    "has_reversal": entry.has_reversal,
                    "is_open_price": entry.is_open_price,
                    "promo_name": entry.promo_name,
                    "promo_type": entry.promo_type,
                    "promo_value": entry.promo_value,
                })
            elif isinstance(entry, DiscountEntry):
                data.append({
                    "type": "discount", "amount": entry.amount, "label": entry.label,
                    "is_promo": entry.is_promo,
                })
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
                    base_tax_rate=raw.get("base_tax_rate", raw.get("tax_rate", 0)),
                    base_unit_price=raw.get("base_unit_price", raw["unit_price"]),
                    is_reversal=raw.get("is_reversal", False),
                    has_reversal=raw.get("has_reversal", False),
                    is_open_price=raw.get("is_open_price", False),
                    promo_name=raw.get("promo_name"),
                    promo_type=raw.get("promo_type"),
                    promo_value=raw.get("promo_value", 0.0),
                ))
            elif kind == "discount":
                entries.append(DiscountEntry(
                    amount=raw["amount"], label=raw["label"], is_promo=raw.get("is_promo", False),
                ))
            elif kind == "subtotal":
                entries.append(SubtotalMarker())
        return cls(entries=entries)


def calc_tax(line_total: float, tax_rate: int) -> float:
    """Return the VAT portion of a tax-inclusive line total."""
    if tax_rate == 0:
        return 0.0
    return round(line_total - line_total / (1 + tax_rate / 100), 2)


@dataclass
class InvoiceLine:
    product_name: str
    quantity: float
    unit_price_excl_tax: float  # full, undiscounted unit price — discount_percent conveys the discount
    unit: str
    tax_rate: int
    line_total_excl_tax: float
    discount_percent: float = 0.0
    is_discount: bool = False

def invoice_lines(invoice: Invoice) -> list[InvoiceLine]:
    cart = Cart.from_snapshot(invoice.line_items_snapshot)
    lines = []
    for entry in cart.entries:
        if isinstance(entry, CartItem):
            if entry.quantity is None:
                continue
            tax = calc_tax(entry.line_total, entry.tax_rate)
            gross = entry.unit_price * entry.quantity
            lines.append(InvoiceLine(
                product_name=entry.product_name,
                quantity=entry.quantity,
                unit_price_excl_tax=round(entry.unit_price / (1 + entry.tax_rate / 100), 2),
                unit=entry.unit,
                tax_rate=entry.tax_rate,
                line_total_excl_tax=round(entry.line_total - tax, 2),
                discount_percent=round(entry.promo_discount / gross * 100, 2) if gross else 0.0,
                is_discount=False
            ))
        elif isinstance(entry, DiscountEntry) and entry.label.startswith("MANUAL DISCOUNT"):
            lines.append(InvoiceLine(
                product_name=entry.label,
                quantity=1,
                unit_price_excl_tax=entry.amount,
                unit="pcs",
                tax_rate=0,
                line_total_excl_tax=entry.amount,
                discount_percent=0.0,
                is_discount=True
            ))
    return lines


def generate_invoice_data(session: Session, invoice: Invoice) -> dict:
    invoice_data = {
        "inv_num": invoice.invoice_number,
        "inv_date": invoice.issued_at.strftime("%Y-%m-%d"),
        "due_date": (invoice.issued_at + timedelta(weeks=1)).strftime("%Y-%m-%d")
    }
    sender = get_store_data(session)
    invoice_data["from"] = sender
    receiver = {
        "name": invoice.client_name,
        "street": invoice.client_street,
        "zip": invoice.client_zip,
        "city": invoice.client_city,
        "vat": invoice.client_vat_number,
        "phone": invoice.client.phone,
        "email": invoice.client.email
    }
    invoice_data["to"] = receiver
    invoice_data["items"] = invoice_lines(invoice)
    invoice_data["notes"] = "Thank you for shopping."

    return invoice_data

    # ── Reports / Queries ─────────────────────────────────────────────────────

class SalesService:

    @staticmethod
    def _generate_sale_number(session: Session) -> str:
        today = date.today().strftime("%d%m%y")
        count = session.query(func.count(Sale.id)).filter(
            func.date(Sale.created_at) == date.today()
        ).scalar() or 0
        return f"S-{today}-{count + 1:03d}"


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
                discount=entry.promo_discount,
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
        if sale.invoice is not None and sale.invoice.sent_at is not None:
            raise ValueError("This invoice has already been sent and can no longer be edited.")

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
                discount=entry.promo_discount,
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
        sale.updated_at = datetime.now()

        # Not-yet-sent invoice: keep its frozen snapshot in step with the
        # edit instead of letting it go stale (see the comment on
        # Invoice.issued_at) — a sent one was already rejected above.
        if sale.invoice is not None:
            sale.invoice.total_amount = sale.total_amount
            sale.invoice.tax_amount = sale.tax_amount
            sale.invoice.final_amount = sale.final_amount
            sale.invoice.line_items_snapshot = cart.to_snapshot()

        session.commit()
        session.refresh(sale)
        return sale

    @staticmethod
    def mark_invoice_sent(session: Session, sale_id: int) -> Invoice:
        """Locks an invoice once it's been transmitted: after this, the
        sale can no longer be reopened/edited (see update_sale above) and
        corrections must go through a credit note instead."""
        sale = session.query(Sale).filter_by(id=sale_id).first()
        if not sale or not sale.invoice:
            raise ValueError(f"Sale {sale_id} has no invoice.")
        if sale.invoice.sent_at is not None:
            return sale.invoice
        sale.invoice.sent_at = datetime.now()
        session.commit()
        session.refresh(sale.invoice)
        return sale.invoice

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

        client = session.query(Client).filter_by(id=client_id).first() if client_id else None
        if not client:
            raise ValueError("An invoice requires a valid client.")

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
                discount=entry.promo_discount,
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

        invoice = Invoice(
            sale_id=sale.id,
            client_id=client_id,
            invoice_number=sale_number.replace("S-", "I-", 1),
            # Snapshot now, once — never re-derived from the live client/sale
            # afterward, so this document can't silently change later.
            client_name=client.name,
            client_vat_number=client.vatNumber,
            client_street=client.street,
            client_zip=client.zip_code,
            client_city=client.city,
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
