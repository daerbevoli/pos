"""
Sales Service
Saving paid tickets as sales/invoices (stock, numbering), reopened-sale
edits, crash-recovery of open tickets, the invoice payload for the ERP,
and sales/invoice lookups. The ticket itself lives in app.core.cart.
"""
import json
import logging
from datetime import date, datetime, timedelta
from dataclasses import dataclass
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.constants.countries import BELGIUM
from app.core.cart import Cart, CartItem, DiscountEntry
from app.models.models import Sale, SaleItem, Invoice, Client, OpenTicket, NumberSequence
from app.core.product_service import ProductService

logger = logging.getLogger(__name__)

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
    logger.debug("Open ticket saved: V-tab %s, %d entries, total %.2f",
                 vtab_slot, len(cart.entries), cart.total)


def clear_open_ticket(session: Session, vtab_slot: int) -> None:
    """Drops the crash-recovery snapshot for a V-tab once its ticket is no
    longer in progress (paid or explicitly cleared)."""
    if session.query(OpenTicket).filter_by(vtab_slot=vtab_slot).delete():
        logger.debug("Open ticket cleared: V-tab %s", vtab_slot)
    session.commit()


def load_open_tickets(session: Session) -> dict[int, OpenTicketData]:
    """Every saved in-progress V-tab cart, keyed by vtab slot — read once at
    startup to recover from a crash or unclean close."""
    drafts = {}
    for row in session.query(OpenTicket).all():
        cart = Cart.from_snapshot(row.cart_snapshot)
        cart.is_refund = bool(row.is_refund)
        # The snapshot holds only the lines; lines added after recovery must
        # still get the attached client's VAT treatment (see set_client()).
        client = session.get(Client, row.client_id) if row.client_id else None
        cart.is_domestic = client is None or client.country == BELGIUM
        drafts[row.vtab_slot] = OpenTicketData(
            cart=cart,
            is_invoice=row.is_invoice,
            client_id=row.client_id,
            client_name=row.client_name or "",
            sale_id=row.sale_id,
            is_refund=cart.is_refund,
        )
        logger.info("Recovered open ticket: V-tab %s, %d entries, total %.2f%s%s",
                    row.vtab_slot, len(cart.entries), cart.total,
                    f", client {row.client_name!r}" if row.client_id else "",
                    f", reopened sale {row.sale_id}" if row.sale_id else "")
    return drafts



@dataclass
class InvoiceLine:
    product_name: str
    quantity: float
    unit_price_excl_tax: float  # full, undiscounted unit price — discount_percent conveys the discount
    unit: str
    tax_rate: int
    line_total_excl_tax: float
    discount_percent: float = 0.0

def invoice_lines(invoice: Invoice) -> list[InvoiceLine]:
    """One line per item, at its full unit price with every discount that
    applies to it — promo and its share of manual ones — folded into
    discount_percent, so the ERP computes VAT on the discounted amount, the
    same as the POS (Cart.net_lines). Manual discounts therefore no
    longer go out as separate lines."""
    cart = Cart.from_snapshot(invoice.line_items_snapshot)
    lines = []
    for line in cart.net_lines():
        entry = line.item
        if entry.quantity is None:
            continue
        # If item was added and voided, skip it
        if entry.has_reversal or entry.is_reversal:
            continue
        lines.append(InvoiceLine(
            product_name=entry.product_name,
            quantity=entry.quantity,
            unit_price_excl_tax=round(entry.unit_price / (1 + entry.tax_rate / 100), 3),
            unit=entry.unit,
            tax_rate=entry.tax_rate,
            line_total_excl_tax=line.net_excl,
            discount_percent=round(line.discount / line.gross * 100, 2) if line.gross else 0.0,
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
    logger.debug("ERP payload built for %s: %s, %d lines",
                 invoice.invoice_number, invoice_data["move_type"], len(items))

    return invoice_data

    # ── Reports / Queries ─────────────────────────────────────────────────────

# Highest number in a series before it wraps back to 1; also sets the
# zero-padded width ("S-ddmmyy-042", "I-ddmmyy-042"). The date keeps a
# number unique across days, so this caps S- (and RF-) tickets per day:
# once all 999 of today's are in use, _next_number() refuses the next one.
SALE_NUMBER_MAX = 999      # S- / RF-
INVOICE_NUMBER_MAX = 999   # I- / CN-


def _describe_sale(sale: Sale, cart: Cart) -> str:
    """One-line summary of a saved sale for the log: total, VAT, line
    counts and how it was paid. Runs after the sale is committed, so it
    must never raise: a logging hiccup can't turn a saved sale into an error."""
    try:
        return _sale_summary(sale, cart)
    except Exception:
        logger.exception("Could not summarise sale %s for the log", sale.sale_number)
        return f"total {sale.final_amount}"


def _sale_summary(sale: Sale, cart: Cart) -> str:
    items = [e for e in cart.entries if isinstance(e, CartItem)]
    reversals = sum(1 for e in items if e.is_reversal)
    discounts = round(sum(e.amount for e in cart.entries if isinstance(e, DiscountEntry)), 2)
    paid = (", ".join(f"{leg.get('method')} {leg.get('amount', 0):.2f}"
                      for leg in json.loads(sale.payment_breakdown))
            if sale.payment_breakdown else sale.payment_method)
    parts = [f"total {sale.final_amount:.2f}", f"VAT {sale.tax_amount:.2f}", f"{len(items)} lines"]
    if reversals:
        parts.append(f"{reversals} reversed")
    if discounts:
        parts.append(f"discounts {discounts:.2f}")
    parts.append(f"paid {paid}")
    if sale.change_given:
        parts.append(f"change {sale.change_given:.2f}")
    return ", ".join(parts)


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
            logger.info("Number series %s- had no counter, starting after %s",
                        series, latest[0] if latest else "nothing")

        today = date.today().strftime("%d%m%y")
        value = row.last_value
        width = len(str(maximum))
        for _ in range(maximum):
            value = value % maximum + 1
            number = f"{series}-{today}-{value:0{width}d}"
            if session.query(column).filter(column == number).first() is None:
                if value < row.last_value:
                    logger.warning("Number series %s- wrapped back to %s", series, number)
                row.last_value = value
                return number
        logger.error("All %d %s- numbers for today are in use", maximum, series)
        raise ValueError(f"All {maximum} {series}- numbers for today are in use.")

    @staticmethod
    def _generate_sale_number(session: Session, prefix: str = "S") -> str:
        """Sales (S-) and refunds (RF-) each run their own 001..999 sequence,
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
        """Called by the Z report: the next sale/refund starts again at 001.
        Not committed here — it's part of the Z report's transaction."""
        for series in ("S", "RF"):
            row = session.get(NumberSequence, series)
            if row is None:
                session.add(NumberSequence(series=series, last_value=0))
            else:
                row.last_value = 0
        logger.info("Sale/refund number sequences reset")

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
        sale = SalesService._save_new_sale(
            session, cart, payment_method, amount_tendered, notes, payment_breakdown)
        session.commit()
        session.refresh(sale)
        logger.info("%s %s completed: %s", "Refund" if cart.is_refund else "Sale",
                    sale.sale_number, _describe_sale(sale, cart))
        return sale

    @staticmethod
    def _save_new_sale(session: Session, cart: Cart, payment_method: str, amount_tendered: float | None,
                       notes: str | None, payment_breakdown: list[dict] | None) -> Sale:
        """Adds the Sale (S-/RF- numbered), its lines and their stock change,
        flushed but not committed — the caller may add an invoice first."""
        sale = Sale(
            sale_number=SalesService._generate_sale_number(session, "RF" if cart.is_refund else "S"),
            notes=notes,
            status="completed",
        )
        SalesService._set_payment(sale, cart, payment_method, amount_tendered, payment_breakdown)
        session.add(sale)
        session.flush()  # Get sale.id without committing
        sale.tax_amount = SalesService._add_sale_items(session, sale, cart)
        return sale

    @staticmethod
    def _set_payment(sale: Sale, cart: Cart, payment_method: str, amount_tendered: float | None,
                     payment_breakdown: list[dict] | None):
        """The cart's totals and snapshot, and how it was paid, onto `sale` —
        a new one or a reopened one being re-saved."""
        sale.total_amount = cart.total
        sale.final_amount = cart.total
        sale.payment_method = payment_method
        sale.amount_tendered = amount_tendered
        sale.change_given = (round(amount_tendered - cart.total, 2)
                             if payment_method in ("cash", "card") and amount_tendered is not None else None)
        sale.cart_snapshot = cart.to_snapshot()
        sale.payment_breakdown = json.dumps(payment_breakdown) if payment_breakdown else None

    @staticmethod
    def _add_sale_items(session: Session, sale: Sale, cart: Cart) -> float:
        """Adds a SaleItem per cart line and changes its stock; returns the
        sale's total VAT. Each line's VAT is on its amount after the
        discounts that apply to it (Cart.net_lines) — a discount the
        customer gets lowers the VAT due — so line_total is that net amount
        and discount everything taken off it (promo + its share of manual)."""
        total_tax = 0.0
        for line in cart.net_lines():
            entry = line.item
            total_tax += line.tax
            session.add(SaleItem(
                sale_id=sale.id,
                product_id=entry.product_id,
                product_name=entry.product_name,
                product_barcode=entry.product_barcode,
                quantity=entry.quantity,
                unit_price=entry.unit_price,
                tax_rate=entry.tax_rate,
                tax_amount=line.tax,
                discount=line.discount,
                line_total=line.net,
            ))
            # A reversal line's quantity is negative, so a mistake puts its stock back.
            ProductService.change_stock(
                session,
                product_id=entry.product_id,
                quantity_change=-entry.quantity,
                reference=sale.sale_number,
            )
        return round(total_tax, 2)

    @staticmethod
    def _new_invoice(session: Session, sale: Sale, client: Client) -> Invoice:
        """Builds the Invoice document for an already-flushed sale: a refund
        issued to a client is a credit note (CN-…), anything else a regular
        invoice (I-…), numbered by its own sequence (_generate_invoice_number)."""
        invoice = Invoice(
            sale_id=sale.id,
            invoice_number=SalesService._generate_invoice_number(session, sale.is_refund),
        )
        SalesService._copy_client(invoice, client)
        SalesService._copy_sale(invoice, sale)
        return invoice

    @staticmethod
    def _copy_client(invoice: Invoice, client: Client):
        """Snapshots the client onto the invoice — never re-derived from the
        live client afterward, so the document can't silently change later."""
        invoice.client_id = client.id
        invoice.client_name = client.name
        invoice.client_vat_number = client.vatNumber
        invoice.client_street = client.street
        invoice.client_zip = client.zip_code
        invoice.client_city = client.city
        invoice.client_country = client.country

    @staticmethod
    def _copy_sale(invoice: Invoice, sale: Sale):
        """Snapshots the sale's amounts, lines and payment onto the invoice,
        which outlives the sale (a Z report purges sales, not invoices)."""
        invoice.total_amount = sale.total_amount
        invoice.tax_amount = sale.tax_amount
        invoice.final_amount = sale.final_amount
        invoice.line_items_snapshot = sale.cart_snapshot
        invoice.payment_method = sale.payment_method
        invoice.payment_breakdown = sale.payment_breakdown
        invoice.change_given = sale.change_given

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

        sale = SalesService.get_by_id(session, sale_id)
        if not sale:
            logger.warning("Sale update refused: sale %s not found", sale_id)
            raise ValueError(f"Sale {sale_id} not found.")
        if sale.invoice is not None and sale.invoice.sent_at is not None:
            logger.warning("Sale update refused: %s's invoice %s was already sent",
                           sale.sale_number, sale.invoice.invoice_number)
            raise ValueError("This invoice has already been sent and can no longer be edited.")
        # Checked before anything below changes stock or items, so a refusal
        # leaves the session exactly as it found it.
        client = session.query(Client).filter_by(id=client_id).first() if client_id else None
        if client_id and not client:
            logger.warning("Sale update refused: %s, client %s not found", sale.sale_number, client_id)
            raise ValueError("An invoice requires a valid client.")
        old_total = sale.final_amount

        # Restore stock from the old line items before replacing them.
        for old_item in sale.items:
            ProductService.change_stock(
                session,
                product_id=old_item.product_id,
                quantity_change=old_item.quantity,
                reference=sale.sale_number,
            )

        sale.items = []  # cascade="all, delete-orphan" removes the old SaleItem rows
        session.flush()

        SalesService._set_payment(sale, cart, payment_method, amount_tendered, payment_breakdown)
        if notes:
            sale.notes = notes

        sale.tax_amount = SalesService._add_sale_items(session, sale, cart)
        sale.updated_at = datetime.now()

        # Not-yet-sent invoice: keep its frozen snapshot in step with the
        # edit instead of letting it go stale (see the comment on
        # Invoice.issued_at) — a sent one was already rejected above.
        new_invoice = None
        if sale.invoice is None and client is not None:
            # Reopened receipt/refund turned into an invoice/credit note.
            new_invoice = SalesService._new_invoice(session, sale, client)
            session.add(new_invoice)
        elif sale.invoice is not None:
            if client is not None and client.id != sale.invoice.client_id:
                logger.info("Invoice %s moved from client %r to %r",
                            sale.invoice.invoice_number, sale.invoice.client_name, client.name)
                SalesService._copy_client(sale.invoice, client)
            SalesService._copy_sale(sale.invoice, sale)

        session.commit()
        session.refresh(sale)
        logger.info("%s %s edited: total %.2f -> %s", "Refund" if sale.is_refund else "Sale",
                    sale.sale_number, old_total, _describe_sale(sale, cart))
        if new_invoice is not None:
            logger.info("%s %s issued for reopened %s, client %r",
                        "Credit note" if new_invoice.is_credit_note else "Invoice",
                        new_invoice.invoice_number, sale.sale_number, client.name)
        return sale

    @staticmethod
    def mark_invoice_sent(session: Session, sale_id: int) -> Invoice:
        """Locks an invoice once it's been transmitted: after this, the
        sale can no longer be reopened/edited (see update_sale above) and
        corrections must go through a credit note instead."""
        sale = SalesService.get_by_id(session, sale_id)
        if not sale or not sale.invoice:
            logger.warning("Mark invoice sent: sale %s has no invoice", sale_id)
            raise ValueError(f"Sale {sale_id} has no invoice.")
        return SalesService.mark_invoice_id_sent(session, sale.invoice.id)

    @staticmethod
    def mark_invoice_id_sent(session: Session, invoice_id: int) -> Invoice:
        """mark_invoice_sent() by the invoice's own id — for an invoice whose
        sale a Z report has already purged (sale_id is NULL)."""
        invoice = session.get(Invoice, invoice_id)
        if invoice is None:
            logger.warning("Mark invoice sent: invoice %s not found", invoice_id)
            raise ValueError(f"Invoice {invoice_id} not found.")
        if invoice.sent_at is not None:
            logger.debug("Invoice %s already marked sent at %s", invoice.invoice_number, invoice.sent_at)
            return invoice
        invoice.sent_at = datetime.now()
        session.commit()
        session.refresh(invoice)
        logger.info("Invoice %s marked sent and locked", invoice.invoice_number)
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
        """finalize_sale() plus its invoice
        a credit note (CN-) for a refund
        committed together."""
        if not cart.entries:
            raise ValueError("Empty cart.")

        client = session.query(Client).filter_by(id=client_id).first() if client_id else None
        if not client:
            logger.warning("Invoice refused: client %s not found", client_id)
            raise ValueError("An invoice requires a valid client.")

        sale = SalesService._save_new_sale(
            session, cart, payment_method, amount_tendered, notes, payment_breakdown)
        invoice = SalesService._new_invoice(session, sale, client)
        session.add(invoice)
        session.commit()
        session.refresh(sale)
        session.refresh(invoice)
        logger.info("%s %s issued (%s), client %r: %s",
                    "Credit note" if invoice.is_credit_note else "Invoice",
                    invoice.invoice_number, sale.sale_number, client.name, _describe_sale(sale, cart))
        return invoice

    @staticmethod
    def get_by_id(session: Session, sale_id: int) -> Sale | None:
        return session.query(Sale).filter_by(id=sale_id).first()

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
