"""
Sales Service
Handles checkout, sale creation, and sales history.
"""
import json
from datetime import date, datetime, timedelta
from dataclasses import dataclass, field
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.models import Sale, SaleItem, Invoice, Client, OpenTicket, NumberSequence
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
    base_tax_rate: int = 0  # the product's own rate; tax_rate may be zeroed by retax_for_client()
    base_unit_price: float = 0.0  # the domestic (VAT-incl.) price; unit_price may be netted down by retax_for_client()
    is_reversal: bool = False  # True for a line that reverses an earlier line on a reopened sale
    has_reversal: bool = False  # True once this original line has been reversed (blocks reversing it again)
    reversal_of: "CartItem | None" = None  # the original line this reverses; saved by position in to_snapshot()
    locked: bool = False  # True for a line already saved on a reopened sale (qty can't change); live-session only, not persisted
    is_open_price: bool = False  # True = unit_price is typed in per sale rather than fixed on the product
    promo_name: str | None = None    # label of the Promo attached to the product when this line was added, if any
    promo_type: str | None = None    # "percent" | "fixed" | None — copied from Promo.discount_type
    discount: float = 0.0            # copied from PromoItem.discount_value: a percent or a fixed amount per unit, per promo_type

    @property
    def pending(self) -> bool:
        """True while this line still needs an amount typed in before it can
        be paid: a weight/volume item awaiting its quantity, or an
        open-price item awaiting its price."""
        return self.quantity is None or (self.is_open_price and self.unit_price == 0.0)

    @property
    def discount_amount(self) -> float:
        """Discount amount contributed by the attached promo, recomputed live off the
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
            return round(raw * self.discount / 100, 2)
        fixed = self.discount * self.quantity
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
    is_refund: bool = False  # RF/CN mode: every line added goes in with a negative quantity

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

    def net_line_totals(self) -> list[tuple["CartItem", float]]:
        """Every CartItem with its line total after the discounts that apply
        to it — the amount VAT is actually due on (a discount the customer
        gets lowers the taxable amount; EU VAT Directive art. 79(b)).

        Mirrors how POSScreen._get_discount_base() aims a discount: one
        right after an item (promo or manual, skipping earlier discount
        rows) comes off that item; one right after a SubtotalMarker is
        spread over that section's items in proportion to their amounts,
        the last item taking the rounding remainder. The nets therefore
        always sum to exactly self.total."""
        items = [e for e in self.entries if isinstance(e, CartItem)]
        net = {id(item): item.line_total for item in items}
        section: list[CartItem] = []
        target: list[CartItem] = []  # what the next DiscountEntry applies to
        for entry in self.entries:
            if isinstance(entry, CartItem):
                section.append(entry)
                target = [entry]
            elif isinstance(entry, SubtotalMarker):
                target, section = section, []
            elif isinstance(entry, DiscountEntry):
                recipients = target or items  # a discount with nothing before it: spread over the cart
                if not recipients:
                    continue
                base = sum(net[id(item)] for item in recipients)
                remaining = round(entry.amount, 2)
                for i, item in enumerate(recipients):
                    if i == len(recipients) - 1:
                        share = remaining
                    elif base:
                        share = round(entry.amount * net[id(item)] / base, 2)
                    else:
                        share = round(entry.amount / len(recipients), 2)
                    net[id(item)] = round(net[id(item)] - share, 2)
                    remaining = round(remaining - share, 2)
        return [(item, net[id(item)]) for item in items]

    @property
    def item_count(self) -> int:
        return sum(
            entry.quantity for entry in self.entries
            if isinstance(entry, CartItem) and entry.quantity is not None
        )

    def add_product(self, product, quantity: float | None = 1, price: float | None = None):
        """price overrides product.price for this line only — used for the
        cashier-typed amount on an open-price item."""
        base_price = product.price if price is None else price
        if quantity is not None and self.is_refund:
            quantity = -abs(quantity)

        promo_item = product.active_promo_item
        self.entries.append(
            CartItem(
                product_id=product.id,
                product_name=product.name,
                product_barcode=product.barcode or "",
                unit_price=self._effective_price(base_price, product.tax),
                quantity=quantity,
                unit=product.unit,
                tax_rate=product.tax if self.is_domestic else 0,
                base_tax_rate=product.tax,
                base_unit_price=base_price,
                is_open_price=product.is_open_price,
                promo_name=promo_item.promo.name if promo_item else None,
                promo_type=promo_item.discount_type if promo_item else None,
                discount=promo_item.discount_value if promo_item else 0.0,
            )
        )
        self.sync_promo_discounts()

    def sync_promo_discounts(self):
        """Rebuild every promo-driven DiscountEntry from scratch off each
        CartItem's *current* discount_amount. Call this after anything that
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
            if isinstance(entry, CartItem) and not entry.has_reversal and entry.discount_amount != 0:
                result.append(DiscountEntry(amount=entry.discount_amount, label=entry.promo_name, is_promo=True))
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
        """Empties the ticket for the next sale. The client's VAT treatment
        goes with it (the caller drops the attached client too); refund mode
        stays on, since only the RF/CN button leaves it."""
        self.entries.clear()
        self.is_domestic = True

    def to_snapshot(self) -> str:
        """Serialize entries in order, exactly as displayed, for later replay.
        A reversal's link to the line it voids is saved as that line's
        position among the items ("reversal_of"), so a reopened ticket can
        still delete the reversal and un-void the original."""
        item_positions = {
            id(e): i for i, e in enumerate(e for e in self.entries if isinstance(e, CartItem))
        }
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
                    "reversal_of": item_positions.get(id(entry.reversal_of)),
                    "is_open_price": entry.is_open_price,
                    "promo_name": entry.promo_name,
                    "promo_type": entry.promo_type,
                    "discount": entry.discount,
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
        items: list[CartItem] = []
        reversal_links: list[tuple[CartItem, int | None]] = []
        for raw in json.loads(snapshot) if snapshot else []:
            kind = raw.get("type")
            if kind == "item":
                item = CartItem(
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
                    # Snapshots saved before the rename still carry "promo_value".
                    discount=raw.get("discount", raw.get("promo_value", 0.0)),
                )
                entries.append(item)
                items.append(item)
                if item.is_reversal:
                    reversal_links.append((item, raw.get("reversal_of")))
            elif kind == "discount":
                entries.append(DiscountEntry(
                    amount=raw["amount"], label=raw["label"], is_promo=raw.get("is_promo", False),
                ))
            elif kind == "subtotal":
                entries.append(SubtotalMarker())
        _relink_reversals(items, reversal_links)
        return cls(entries=entries)


def _relink_reversals(items: list[CartItem], links: list[tuple[CartItem, int | None]]):
    """Restore each reversal's reversal_of after from_snapshot(). Uses the
    saved position when there is one; snapshots saved before it existed
    fall back to the earliest still-unclaimed reversed line with the same
    product, price and opposite quantity — identical lines are
    interchangeable, so whichever one is picked voids the same amount."""
    claimed: set[int] = set()
    for reversal, position in links:
        original = None
        if position is not None and 0 <= position < len(items) and items[position].has_reversal:
            original = items[position]
        else:
            original = next(
                (
                    item for item in items
                    if item.has_reversal and not item.is_reversal and id(item) not in claimed
                    and item.product_id == reversal.product_id
                    and item.unit_price == reversal.unit_price
                    and item.quantity is not None and reversal.quantity is not None
                    and item.quantity == -reversal.quantity
                ),
                None,
            )
        if original is not None:
            reversal.reversal_of = original
            claimed.add(id(original))


@dataclass
class OpenTicketData:
    """One V-tab's recovered in-progress cart, read back from `open_tickets`
    at startup — see SalesService.load_open_tickets()."""
    cart: Cart
    is_invoice: bool
    client_id: int | None
    client_name: str
    sale_id: int | None
    is_refund: bool = False


def save_open_ticket(
    session: Session,
    vtab_slot: int,
    cart: Cart,
    is_invoice: bool,
    client_id: int | None,
    client_name: str,
    sale_id: int | None,
    is_refund: bool = False,
) -> None:
    """Upserts the crash-recovery snapshot of one V-tab's in-progress cart.
    Called after every cart mutation while the ticket isn't finished yet."""
    row = session.query(OpenTicket).filter_by(vtab_slot=vtab_slot).first()
    if row is None:
        row = OpenTicket(vtab_slot=vtab_slot)
        session.add(row)
    row.cart_snapshot = cart.to_snapshot()
    row.is_invoice = is_invoice
    row.client_id = client_id
    row.client_name = client_name
    row.sale_id = sale_id
    row.is_refund = is_refund
    session.commit()


def clear_open_ticket(session: Session, vtab_slot: int) -> None:
    """Drops the crash-recovery snapshot for a V-tab once its ticket is no
    longer in progress (paid or explicitly cleared)."""
    session.query(OpenTicket).filter_by(vtab_slot=vtab_slot).delete()
    session.commit()


def load_open_tickets(session: Session) -> dict[int, OpenTicketData]:
    """Every saved in-progress V-tab cart, keyed by vtab slot — read once at
    startup to recover from a crash or unclean close."""
    drafts = {}
    for row in session.query(OpenTicket).all():
        cart = Cart.from_snapshot(row.cart_snapshot)
        cart.is_refund = bool(row.is_refund)
        drafts[row.vtab_slot] = OpenTicketData(
            cart=cart,
            is_invoice=row.is_invoice,
            client_id=row.client_id,
            client_name=row.client_name or "",
            sale_id=row.sale_id,
            is_refund=cart.is_refund,
        )
    return drafts


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
    """One line per item, at its full unit price with every discount that
    applies to it — promo and its share of manual ones — folded into
    discount_percent, so the ERP computes VAT on the discounted amount, the
    same as the POS (Cart.net_line_totals). Manual discounts therefore no
    longer go out as separate lines."""
    cart = Cart.from_snapshot(invoice.line_items_snapshot)
    lines = []
    for entry, net_total in cart.net_line_totals():
        if entry.quantity is None:
            continue
        # If item was added and voided, skip it
        if entry.has_reversal or entry.is_reversal:
            continue
        tax = calc_tax(net_total, entry.tax_rate)
        gross = entry.line_total
        lines.append(InvoiceLine(
            product_name=entry.product_name,
            quantity=entry.quantity,
            unit_price_excl_tax=round(entry.unit_price / (1 + entry.tax_rate / 100), 2),
            unit=entry.unit,
            tax_rate=entry.tax_rate,
            line_total_excl_tax=round(net_total - tax, 2),
            discount_percent=round((gross - net_total) / gross * 100, 2) if gross else 0.0,
            is_discount=False
        ))
    return lines


def generate_invoice_data(invoice: Invoice) -> dict:
    invoice_data = {
        "inv_num": invoice.invoice_number,
        "inv_date": invoice.issued_at.strftime("%Y-%m-%d"),
        "due_date": (invoice.issued_at + timedelta(weeks=1)).strftime("%Y-%m-%d")
    }
    receiver = {
        "name": invoice.client_name,
        "street": invoice.client_street,
        "zip": invoice.client_zip,
        "city": invoice.client_city,
        "country": invoice.client_country,
        "vat": invoice.client_vat_number,
        "phone": invoice.client.phone,
        "email": invoice.client.email
    }
    invoice_data["to"] = receiver
    items = invoice_lines(invoice)
    if invoice.is_credit_note:
        # Odoo books a credit note as its own move type with positive
        # quantities — the refund direction comes from out_refund itself,
        # not from negative lines (which an out_invoice refuses to post).
        for line in items:
            line.quantity = abs(line.quantity)
            line.line_total_excl_tax = abs(line.line_total_excl_tax)
    invoice_data["move_type"] = "out_refund" if invoice.is_credit_note else "out_invoice"
    invoice_data["items"] = items
    invoice_data["notes"] = "Thank you for shopping."

    return invoice_data

    # ── Reports / Queries ─────────────────────────────────────────────────────

# Highest number in a series before it wraps back to 1; also sets the
# zero-padded width ("S-ddmmyy-0042", "I-ddmmyy-042").
SALE_NUMBER_MAX = 9999     # S- / RF-
INVOICE_NUMBER_MAX = 999   # I- / CN-


class SalesService:

    @staticmethod
    def _next_number(session: Session, series: str, column, maximum: int) -> str:
        """Next "<series>-ddmmyy-N…" number. N… counts 1..maximum per series,
        zero-padded to maximum's width, and wraps back to 1, skipping any number still taken in `column`
        (the date usually keeps a wrapped number unique; this covers a
        series that wraps within one day). A series with no stored counter
        yet (database from before counters existed) continues after its
        most recently issued number."""
        row = session.get(NumberSequence, series)
        if row is None:
            latest = session.query(column).filter(column.like(f"{series}-%")) \
                .order_by(column.class_.id.desc()).first()
            suffix = latest[0].rsplit("-", 1)[1] if latest else ""
            row = NumberSequence(series=series, last_value=int(suffix) if suffix.isdigit() else 0)
            session.add(row)

        today = date.today().strftime("%d%m%y")
        value = row.last_value
        width = len(str(maximum))
        for _ in range(maximum):
            value = value % maximum + 1
            number = f"{series}-{today}-{value:0{width}d}"
            if session.query(column).filter(column == number).first() is None:
                row.last_value = value
                return number
        raise ValueError(f"All {maximum} {series}- numbers for today are in use.")

    @staticmethod
    def _generate_sale_number(session: Session, prefix: str = "S") -> str:
        """Sales (S-) and refunds (RF-) each run their own 0001..9999 sequence,
        restarted by every Z report (see reset_sale_sequences())."""
        return SalesService._next_number(session, prefix, Sale.sale_number, SALE_NUMBER_MAX)

    @staticmethod
    def _generate_invoice_number(session: Session, is_credit_note: bool) -> str:
        """Invoices (I-) and credit notes (CN-) each run their own 001..999
        sequence that carries on across Z reports — unlike the sale's
        number, which restarts — so it's independent of the sale's number."""
        return SalesService._next_number(
            session, "CN" if is_credit_note else "I", Invoice.invoice_number, INVOICE_NUMBER_MAX,
        )

    @staticmethod
    def reset_sale_sequences(session: Session) -> None:
        """Called by the Z report: the next sale/refund starts again at 0001.
        Not committed here — it's part of the Z report's transaction."""
        for series in ("S", "RF"):
            row = session.get(NumberSequence, series)
            if row is None:
                session.add(NumberSequence(series=series, last_value=0))
            else:
                row.last_value = 0

    @staticmethod
    def finalize_sale(
        session: Session,
        cart: Cart,
        payment_method: str = "cash",
        amount_tendered: float | None = None,
        notes: str | None = None,
        payment_breakdown: list[dict] = None,
    ) -> Sale:
        """
        Convert cart to a completed Sale. Deducts stock automatically
        (a refund's negative lines put it back). Numbered RF- instead of
        S- when cart.is_refund. Returns the saved Sale object.
        """
        if not cart.entries:
            raise ValueError("Empty cart.")

        sale_number = SalesService._generate_sale_number(session, "RF" if cart.is_refund else "S")
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

        sale.tax_amount = SalesService._add_sale_items(session, sale, cart)
        session.commit()
        session.refresh(sale)
        return sale

    @staticmethod
    def _add_sale_items(session: Session, sale: Sale, cart: Cart) -> float:
        """Adds a SaleItem per cart line and moves its stock; returns the
        sale's total VAT. Each line's VAT is on its amount after the
        discounts that apply to it (Cart.net_line_totals) — a discount the
        customer gets lowers the VAT due — so line_total is that net amount
        and discount everything taken off it (promo + its share of manual)."""
        total_tax = 0.0
        for entry, net_total in cart.net_line_totals():
            tax_amount = calc_tax(net_total, entry.tax_rate)
            total_tax += tax_amount
            session.add(SaleItem(
                sale_id=sale.id,
                product_id=entry.product_id,
                product_name=entry.product_name,
                product_barcode=entry.product_barcode,
                quantity=entry.quantity,
                unit_price=entry.unit_price,
                tax_rate=entry.tax_rate,
                tax_amount=tax_amount,
                discount=round(entry.line_total - net_total, 2),
                line_total=net_total,
            ))
            ProductService.move_stock(
                session,
                product_id=entry.product_id,
                quantity_change=-entry.quantity,
                movement_type="sale",
                reference=sale.sale_number,
            )
        return round(total_tax, 2)

    @staticmethod
    def _new_invoice(session: Session, sale: Sale, client: Client, cart: Cart) -> Invoice:
        """Builds the Invoice document for an already-flushed sale: a refund
        issued to a client is a credit note (CN-…), anything else a regular
        invoice (I-…), numbered by its own sequence (_generate_invoice_number)."""
        invoice_number = SalesService._generate_invoice_number(session, sale.is_refund)
        return Invoice(
            sale_id=sale.id,
            client_id=client.id,
            invoice_number=invoice_number,
            # Snapshot now, once — never re-derived from the live client/sale
            # afterward, so this document can't silently change later.
            client_name=client.name,
            client_vat_number=client.vatNumber,
            client_street=client.street,
            client_zip=client.zip_code,
            client_city=client.city,
            client_country=client.country,
            total_amount=sale.total_amount,
            tax_amount=sale.tax_amount,
            final_amount=sale.final_amount,
            line_items_snapshot=cart.to_snapshot(),
            payment_method=sale.payment_method,
            payment_breakdown=sale.payment_breakdown,
        )

    @staticmethod
    def update_sale(
        session: Session,
        sale_id: int,
        cart: Cart,
        payment_method: str = "cash",
        amount_tendered: float = None,
        notes: str = None,
        payment_breakdown: list[dict] = None,
        client_id: int = None,
    ) -> Sale:
        """
        Overwrite an existing completed sale with an edited cart, in place.
        Keeps the same id / sale_number / created_at. Stock is reconciled:
        old line quantities are restored, then the new cart's quantities
        are deducted. With a client_id, a sale that has no invoice yet gets
        one (S- → I-, RF- → CN-); an unsent one is re-snapshotted for that
        client.
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
            ProductService.move_stock(
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

        sale.tax_amount = SalesService._add_sale_items(session, sale, cart)
        sale.updated_at = datetime.now()

        # Not-yet-sent invoice: keep its frozen snapshot in step with the
        # edit instead of letting it go stale (see the comment on
        # Invoice.issued_at) — a sent one was already rejected above.
        client = session.query(Client).filter_by(id=client_id).first() if client_id else None
        if client_id and not client:
            raise ValueError("An invoice requires a valid client.")
        if sale.invoice is None and client is not None:
            # Reopened receipt/refund turned into an invoice/credit note.
            session.add(SalesService._new_invoice(session, sale, client, cart))
        elif sale.invoice is not None:
            if client is not None and client.id != sale.invoice.client_id:
                sale.invoice.client_id = client.id
                sale.invoice.client_name = client.name
                sale.invoice.client_vat_number = client.vatNumber
                sale.invoice.client_street = client.street
                sale.invoice.client_zip = client.zip_code
                sale.invoice.client_city = client.city
                sale.invoice.client_country = client.country
            sale.invoice.total_amount = sale.total_amount
            sale.invoice.tax_amount = sale.tax_amount
            sale.invoice.final_amount = sale.final_amount
            sale.invoice.line_items_snapshot = cart.to_snapshot()
            sale.invoice.payment_method = sale.payment_method
            sale.invoice.payment_breakdown = sale.payment_breakdown

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
        return SalesService.mark_invoice_id_sent(session, sale.invoice.id)

    @staticmethod
    def mark_invoice_id_sent(session: Session, invoice_id: int) -> Invoice:
        """mark_invoice_sent() by the invoice's own id — for an invoice whose
        sale a Z report has already purged (sale_id is NULL)."""
        invoice = session.get(Invoice, invoice_id)
        if invoice is None:
            raise ValueError(f"Invoice {invoice_id} not found.")
        if invoice.sent_at is not None:
            return invoice
        invoice.sent_at = datetime.now()
        session.commit()
        session.refresh(invoice)
        return invoice

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

        sale_number = SalesService._generate_sale_number(session, "RF" if cart.is_refund else "S")
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

        sale.tax_amount = SalesService._add_sale_items(session, sale, cart)

        invoice = SalesService._new_invoice(session, sale, client, cart)
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
    def get_invoices_range(session: Session, start: date, end: date) -> list[Invoice]:
        """Invoices/credit notes issued in [start, end], newest first. Read
        from the invoices table itself, not through sales: a Z report purges
        the sales but keeps the invoices (their sale_id becomes NULL)."""
        return (
            session.query(Invoice)
            .filter(
                func.date(Invoice.issued_at) >= start,
                func.date(Invoice.issued_at) <= end,
            )
            .order_by(Invoice.issued_at.desc())
            .all()
        )

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
