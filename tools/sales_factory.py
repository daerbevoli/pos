"""
Random sales for testing the reports.

Tickets are built the way a cashier could (items, promos, item and subtotal
discounts, refunds, foreign clients, reopening a sale to reverse or remove
lines), paid in cash, card or both, and saved through the real SalesService
into whatever session they're given, spread over shop days, with a Z report
closing every day but the last. Alongside, each sale's effect is recorded
from what was rung up and handed over, so expected_totals() gives what the
reports should show without going through what was saved.

Used by tests/test_cart_invariants.py (tickets only),
tests/test_report_invariants.py (in-memory database) and tools/seed_sales.py
(a demo database to open in the app). Same seed, same sales.
"""
import math
import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from types import SimpleNamespace

from sqlalchemy.orm import Session

from app.constants.vat import VAT_RATES
from app.core.client.client_service import ClientService
from app.core.inventory.product_service import ProductService
from app.core.sale.cart import Cart, CartItem, DiscountEntry, SubtotalMarker
from app.core.sale.report_service import XZReportService
from app.core.sale.sales_service import SalesService
from app.models.models import Category

PRICES = (0.99, 1.5, 2.49, 3.2, 10.0, 12.1, 19.99)
CATEGORIES = ("Fruit & Veg", "Bakery", "Drinks", "Household")
UNCATEGORIZED = "Uncategorized"  # what the reports call a product without a category

# Made-up clients: only Belgian VAT numbers are checksummed, these two pass it.
CLIENTS = (
    ("Demo Bakery", "BE", "BE0123456749"),
    ("Demo Catering", "BE", "BE0000000097"),
    ("Demo SARL", "FR", "FR00123456789"),
    ("Demo BV", "NL", "NL000000000B01"),
    ("Demo GmbH", "DE", "DE000000000"),
)


# ── Tickets ──────────────────────────────────────────────────────────────

def fake_promo(discount_type, value):
    """Stands in for a PromoItem: Cart.add_product reads .promo.name,
    .discount_type and .discount_value."""
    return SimpleNamespace(promo=SimpleNamespace(name="PROMO"), discount_type=discount_type,
                           discount_value=value)


def random_ticket(rng: random.Random, pick_product, foreign_chance: float = 0.3) -> tuple[Cart, Cart]:
    """A ticket built the way a cashier could, from products pick_product(rng)
    returns (anything with id, name, barcode, price, tax and unit; the promo
    is decided here). Returns (first, final): the cart as first paid, and as
    re-paid after reopening it (the POS's snapshot round trip) to reverse or
    remove lines, which is `first` itself if it wasn't reopened.
    foreign_chance: how often it's for a non-Belgian client."""

    def add_item():
        promo = None
        roll = rng.random()
        if roll < 0.2:
            promo = fake_promo("percent", rng.choice((10, 25, 50)))
        elif roll < 0.3:
            promo = fake_promo("fixed", 0.5)
        product = pick_product(rng)
        quantity = rng.choice((0.25, 0.5, 1.2, 2.0)) if product.unit == "kg" else rng.randint(1, 4)
        cart.add_product(SimpleNamespace(
            id=product.id, name=product.name, barcode=product.barcode, price=product.price,
            tax=product.tax, unit=product.unit, is_open_price=False, active_promo_item=promo,
        ), quantity=quantity)

    def random_step():
        roll = rng.random()
        if roll < 0.55:
            add_item()
        elif roll < 0.7:
            cart.apply_percent_discount(rng.choice((5, 10, 25, 50)))
        elif roll < 0.8:
            cart.apply_amount_discount(rng.choice((0.5, 1.0, 2.0, 5.0)))
        elif any(isinstance(e, (CartItem, DiscountEntry)) for e in cart.entries[-1:]):
            cart.add_subtotal()

    cart = Cart()
    if rng.random() < foreign_chance:
        cart.retax_for_client(False)
    cart.is_refund = rng.random() < 0.15

    add_item()
    for _ in range(rng.randint(0, 7)):
        random_step()
    if cart.is_domestic and rng.random() < foreign_chance / 2:
        cart.retax_for_client(False)  # Client pressed after ringing items up
    first = cart

    if rng.random() < 0.6:
        # Saved, then reopened: lines come back from the snapshot, locked.
        cart = Cart.from_snapshot(first.to_snapshot())
        cart.is_domestic, cart.is_refund = first.is_domestic, first.is_refund
        for entry in cart.entries:
            if isinstance(entry, CartItem):
                entry.locked = True
        for _ in range(rng.randint(1, 5)):
            roll = rng.random()
            reversible = [e for e in cart.entries if isinstance(e, CartItem) and e.locked
                          and not e.is_reversal and not e.has_reversal]
            removable = [e for e in cart.entries if isinstance(e, CartItem) and not e.locked]
            # The Error key on a discount or subtotal row, e.g. one that was
            # already on the saved sale.
            markers = [e for e in cart.entries if isinstance(e, (DiscountEntry, SubtotalMarker))]
            if roll < 0.45 and reversible:
                cart.reverse(rng.choice(reversible))
            elif roll < 0.6 and removable:
                cart.remove_entry(rng.choice(removable))
            elif roll < 0.75 and markers:
                cart.remove_entry(rng.choice(markers))
            else:
                random_step()
    return first, cart


def _payable(cart: Cart, reopened: bool) -> bool:
    """Whether the POS would let this cart be paid: a sale can't come to
    less than 0.00, a new refund must pay something out (a reopened one may
    settle at 0.00: that cancels it)."""
    if cart.is_refund:
        return cart.total < 0 or (reopened and cart.total == 0)
    return cart.total >= 0


# ── Payments ─────────────────────────────────────────────────────────────

@dataclass
class Payment:
    method: str                # "cash", "card" or "mixed", as the POS saves it
    tendered: float
    breakdown: list[dict]      # one leg per method, as tendered (what the POS saves)
    taken: dict[str, float]    # what each method really took in: change already handed back


def random_payment(rng: random.Random, total: float, is_refund: bool) -> Payment:
    """Paid the ways the POS allows (see POSScreen._settle/_read_tender):
    exact cash or card, cash with change, or card then cash; only cash can
    be overpaid. A refund is paid out in one method."""
    if is_refund:
        method = rng.choice(("cash", "card"))
        return Payment(method, total, [{"method": method, "amount": total}], {method: total})
    roll = rng.random()
    if 0.7 <= roll < 0.9 and total > 0:
        note = rng.choice((5, 10, 20, 50))
        tendered = float((math.floor(total / note) + 1) * note)
        return Payment("cash", tendered, [{"method": "cash", "amount": tendered}], {"cash": total})
    if roll >= 0.9:
        card = round(total * rng.uniform(0.2, 0.8), 2)
        cash_due = round(total - card, 2)
        if card > 0 and cash_due > 0:
            cash = float(math.ceil(cash_due)) if rng.random() < 0.5 else cash_due
            return Payment("mixed", round(card + cash, 2),
                           [{"method": "card", "amount": card}, {"method": "cash", "amount": cash}],
                           {"card": card, "cash": cash_due})
    method = "card" if 0.35 <= roll < 0.7 else "cash"
    return Payment(method, total, [{"method": method, "amount": total}], {method: total})


# ── Saving ───────────────────────────────────────────────────────────────

@dataclass
class SaleRecord:
    """One saved sale and what it should add to the reports."""
    sale_id: int
    day: date                  # local shop day it was rung up on
    when: datetime             # aware UTC, its created_at
    cart: Cart                 # as finally paid
    taken: dict[str, float]    # per method, change handed back
    invoice_number: str | None


@dataclass
class Seeded:
    records: list[SaleRecord]
    category_of: dict[int, str]  # product id -> category name, as the reports name it


def _create_catalog(session: Session, rng: random.Random) -> list[SimpleNamespace]:
    categories = {}
    for name in CATEGORIES:
        category = session.query(Category).filter_by(name=name).first() or Category(name=name)
        session.add(category)
        categories[name] = category
    session.flush()
    catalog = []
    for i in range(24):
        category = None if i % 8 == 7 else CATEGORIES[i % len(CATEGORIES)]
        unit = "kg" if category == "Fruit & Veg" and i % 2 else "pcs"
        product = ProductService.create(
            session, name=f"Demo {category or 'misc'} {i + 1}", barcode=f"DEMO{i + 1:04d}",
            price=rng.choice(PRICES), tax=rng.choice(VAT_RATES), unit=unit, stock_quantity=1000,
            category_id=categories[category].id if category else None,
        )
        catalog.append(SimpleNamespace(id=product.id, name=product.name, barcode=product.barcode,
                                       price=product.price, tax=product.tax, unit=product.unit,
                                       category=category or UNCATEGORIZED))
    return catalog


def _create_clients(session: Session):
    return [ClientService.create(session, name=name, country=country, vatNumber=vat,
                                 street="1 Demo Street", zip_code="1000", city="Demo City")
            for name, country, vat in CLIENTS]


def _sale_times(rng: random.Random, day: date, count: int) -> list[datetime]:
    """`count` sorted moments of local `day`, as aware UTC: shop hours, now
    and then one just after midnight or just before the next, where a
    day-boundary bug would show. Never 02:00-03:00, which a DST switch skips."""
    moments = []
    for _ in range(count):
        roll = rng.random()
        if roll < 0.03:
            moment = time(0, 0, rng.randint(1, 59))
        elif roll < 0.06:
            moment = time(23, 59, rng.randint(0, 29))
        else:
            seconds = rng.randint(8 * 3600, 20 * 3600)
            moment = time(seconds // 3600, seconds // 60 % 60, seconds % 60)
        # A naive datetime's astimezone() reads it as local time.
        moments.append(datetime.combine(day, moment).astimezone(UTC))
    return sorted(moments)


def _ring_up(session, rng, catalog, clients, day, when, invoice_chance) -> SaleRecord:
    """One payable ticket saved like the POS does: finalize_sale (or
    finalize_invoice with a client), then update_sale if it was reopened."""
    while True:
        first, final = random_ticket(rng, lambda r: r.choice(catalog), foreign_chance=invoice_chance / 2)
        if _payable(first, False) and _payable(final, final is not first):
            break
    if not final.is_domestic:
        client = rng.choice([c for c in clients if c.country != "BE"])
    elif rng.random() < invoice_chance / 2:
        client = rng.choice([c for c in clients if c.country == "BE"])
    else:
        client = None

    pay = random_payment(rng, first.total, first.is_refund)
    kwargs = dict(payment_method=pay.method, amount_tendered=pay.tendered, payment_breakdown=pay.breakdown)
    if client:
        sale = SalesService.finalize_invoice(session, first, client_id=client.id, **kwargs).sale
    else:
        sale = SalesService.finalize_sale(session, first, **kwargs)
    if final is not first:
        pay = random_payment(rng, final.total, final.is_refund)
        SalesService.update_sale(session, sale.id, final, client_id=client.id if client else None,
                                 payment_method=pay.method, amount_tendered=pay.tendered,
                                 payment_breakdown=pay.breakdown)
    sale.created_at = when
    if sale.invoice:
        # No ERP here: marked sent straight away, or the day's Z report would be refused.
        sale.invoice.issued_at = sale.invoice.sent_at = when
    session.commit()
    return SaleRecord(sale.id, day, when, final, pay.taken,
                      sale.invoice.invoice_number if sale.invoice else None)


def seed_sales(session: Session, rng: random.Random, days: list[date], per_day: int,
               close_z: bool = True, invoice_chance: float = 0.15) -> Seeded:
    """Creates a demo catalog and clients, then `per_day` sales on each of
    `days` (local dates, in order). With close_z, a Z report closes every day
    but the last, timed just after its last sale; the last day stays open.
    invoice_chance: roughly how often a sale is invoiced (half of them to
    foreign clients)."""
    catalog = _create_catalog(session, rng)
    clients = _create_clients(session)
    records = []
    for day in days:
        moments = _sale_times(rng, day, per_day)
        for when in moments:
            records.append(_ring_up(session, rng, catalog, clients, day, when, invoice_chance))
        if close_z and day != days[-1]:
            z_report = XZReportService.close_z_report(session)
            z_report.created_at = z_report.period_end = moments[-1] + timedelta(seconds=20)
            session.commit()
    return Seeded(records, {p.id: p.category for p in catalog})


# ── What the reports should show ─────────────────────────────────────────

def expected_totals(records: list[SaleRecord], category_of: dict[int, str]) -> dict:
    """Totals of these sales, worked out from the carts as rung up and the
    payments as handed over: count, final (incl. VAT), tax, vat {rate:
    {"tax", "total"}}, payments {method: taken}, discounts {"manual",
    "promo"}, mistakes (names of lines voided on reopened sales, sorted)
    and categories {name: amount}."""
    vat = {rate: {"tax": 0.0, "total": 0.0} for rate in VAT_RATES}
    payments: dict[str, float] = {}
    discounts = {"manual": 0.0, "promo": 0.0}
    categories: dict[str, float] = {}
    mistakes = []
    final = tax = 0.0
    for record in records:
        final += record.cart.total
        for line in record.cart.net_lines():
            tax += line.tax
            vat[line.item.tax_rate]["tax"] += line.tax
            vat[line.item.tax_rate]["total"] += line.net
            name = category_of[line.item.product_id]
            categories[name] = categories.get(name, 0.0) + line.net
        for method, amount in record.taken.items():
            payments[method] = payments.get(method, 0.0) + amount
        for entry in record.cart.entries:
            if isinstance(entry, DiscountEntry):
                discounts["promo" if entry.is_promo else "manual"] += entry.amount
            elif isinstance(entry, CartItem) and entry.is_reversal and not record.cart.is_refund:
                mistakes.append(entry.product_name)
    return {
        "count": len(records),
        "final": round(final, 2),
        "tax": round(tax, 2),
        "vat": {rate: {k: round(v, 2) for k, v in amounts.items()} for rate, amounts in vat.items()},
        "payments": {method: round(amount, 2) for method, amount in payments.items()},
        "discounts": {kind: round(amount, 2) for kind, amount in discounts.items()},
        "mistakes": sorted(mistakes),
        "categories": {name: round(amount, 2) for name, amount in categories.items()},
    }
