"""
Agreement checks between every place a ticket's money is worked out: the
till total, the per-line amounts saved on the sale (Cart.net_lines), and
the invoice lines sent to the ERP (invoice_lines).

Besides hand-written cases, random tickets are built from a seeded
random.Random (reproducible: a failure names its seed) out of the same
steps a cashier can take — items, promos, item/subtotal discounts, a
non-Belgian client, refund mode, then reopening the sale to reverse or
remove lines.

Tests marked xfail(strict=True) pin bugs that are known and not fixed yet;
once fixed they XPASS, which fails the run as a reminder to drop the mark.
"""
import random
from types import SimpleNamespace

import pytest

from app.core.cart import Cart, CartItem, DiscountEntry, SubtotalMarker
from app.core.sales_service import invoice_lines

SEEDS = range(500)

PRICES = (0.99, 1.5, 2.49, 3.2, 10.0, 12.1, 19.99)
TAX_RATES = (0, 6, 12, 21)


def _product(pid, price, tax=21, unit="pcs", promo=None):
    return SimpleNamespace(
        id=pid, name=f"P{pid}", barcode=str(pid), price=price, tax=tax, unit=unit,
        is_open_price=False, active_promo_item=promo,
    )


def _promo(discount_type, value):
    """Stands in for a PromoItem: Cart.add_product reads .promo.name,
    .discount_type and .discount_value."""
    return SimpleNamespace(promo=SimpleNamespace(name="PROMO"), discount_type=discount_type,
                           discount_value=value)


def _random_ticket(seed: int) -> Cart:
    """A ticket built the way a cashier could: rung up, optionally saved and
    reopened (via its snapshot, like the POS does), then edited."""
    rng = random.Random(seed)
    next_pid = iter(range(1, 1000))

    def add_item():
        promo = None
        roll = rng.random()
        if roll < 0.2:
            promo = _promo("percent", rng.choice((10, 25, 50)))
        elif roll < 0.3:
            promo = _promo("fixed", 0.5)
        unit = "kg" if rng.random() < 0.2 else "pcs"
        quantity = rng.choice((0.25, 0.5, 1.2, 2.0)) if unit == "kg" else rng.randint(1, 4)
        cart.add_product(
            _product(next(next_pid), rng.choice(PRICES), rng.choice(TAX_RATES), unit, promo),
            quantity=quantity,
        )

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
    if rng.random() < 0.3:
        cart.retax_for_client(False)
    cart.is_refund = rng.random() < 0.15

    add_item()
    for _ in range(rng.randint(0, 7)):
        random_step()
    if cart.is_domestic and rng.random() < 0.15:
        cart.retax_for_client(False)  # Client pressed after ringing items up

    if rng.random() < 0.6:
        # Saved, then reopened: lines come back from the snapshot, locked.
        is_domestic, is_refund = cart.is_domestic, cart.is_refund
        cart = Cart.from_snapshot(cart.to_snapshot())
        cart.is_domestic, cart.is_refund = is_domestic, is_refund
        for entry in cart.entries:
            if isinstance(entry, CartItem):
                entry.locked = True
        for _ in range(rng.randint(1, 5)):
            roll = rng.random()
            reversible = [e for e in cart.entries if isinstance(e, CartItem) and e.locked
                          and not e.is_reversal and not e.has_reversal]
            removable = [e for e in cart.entries if isinstance(e, CartItem) and not e.locked]
            if roll < 0.45 and reversible:
                cart.reverse(rng.choice(reversible))
            elif roll < 0.6 and removable:
                cart.remove_entry(rng.choice(removable))
            else:
                random_step()
    return cart


def _describe(cart: Cart) -> str:
    rows = []
    for e in cart.entries:
        if isinstance(e, CartItem):
            flags = "".join(f" [{f}]" for f in ("is_reversal", "has_reversal", "locked") if getattr(e, f))
            rows.append(f"  item {e.product_name} {e.quantity} x {e.unit_price} @{e.tax_rate}%{flags}")
        elif isinstance(e, DiscountEntry):
            rows.append(f"  discount {e.amount} {e.label!r}{' [promo]' if e.is_promo else ''}")
        elif isinstance(e, SubtotalMarker):
            rows.append("  subtotal")
    return "\n".join(rows)


def _invoice_for(cart: Cart):
    return SimpleNamespace(line_items_snapshot=cart.to_snapshot())


# ── Hand-written cases ───────────────────────────────────────────────────

def test_stacked_item_and_subtotal_discounts_on_invoice():
    """Food 10.00 with 10% off, 3 broccoli at 1.50, subtotal, 10% off — the
    invoice Odoo produced for it: Food at 19% off (both discounts stacked),
    broccoli at 10%, 11.46 excl. + 0.69 VAT = 12.15, the till's total."""
    cart = Cart()
    cart.add_product(_product(1, 10.0, tax=6))
    assert cart.apply_percent_discount(10) is not None
    cart.add_product(_product(2, 1.5, tax=6), quantity=3)
    cart.add_subtotal()
    assert cart.apply_percent_discount(10) is not None

    lines = invoice_lines(_invoice_for(cart))

    assert cart.total == 12.15
    assert [(l.unit_price_excl_tax, l.discount_percent, l.line_total_excl_tax) for l in lines] == [
        (9.434, 19.0, 7.64),
        (1.415, 10.0, 3.82),
    ]
    assert round(sum(l.line_total_excl_tax for l in lines), 2) == 11.46


def test_reversing_a_discounted_line_also_voids_its_discount():
    cart = Cart()
    cart.add_product(_product(1, 10.0))
    cart.add_product(_product(2, 5.0))
    assert cart.apply_amount_discount(1.0) is not None  # on the 5.00 line
    cart.reverse(cart.entries[1])

    assert cart.total == 10.0


def test_invoice_matches_till_after_reversing_a_line_of_a_discounted_section():
    cart = Cart()
    cart.add_product(_product(1, 10.0))
    cart.add_product(_product(2, 5.0))
    cart.add_subtotal()
    assert cart.apply_percent_discount(10) is not None  # 1.50 over both lines
    cart.reverse(cart.entries[1])

    lines = invoice_lines(_invoice_for(cart))
    till_excl = round(sum(line.net_excl for line in cart.net_lines()), 2)

    assert round(sum(l.line_total_excl_tax for l in lines), 2) == till_excl


def test_percent_promo_for_foreign_client_is_the_domestic_price_net_of_vat():
    domestic, foreign = Cart(), Cart()
    foreign.retax_for_client(False)
    for cart in (domestic, foreign):
        cart.add_product(_product(1, 12.1, tax=21, promo=_promo("percent", 20)))

    assert foreign.total == round(domestic.total / 1.21, 2)


def test_fixed_promo_for_foreign_client_is_the_domestic_price_net_of_vat():
    domestic, foreign = Cart(), Cart()
    foreign.retax_for_client(False)
    for cart in (domestic, foreign):
        cart.add_product(_product(1, 12.1, tax=21, promo=_promo("fixed", 2.0)))

    assert foreign.total == round(domestic.total / 1.21, 2)


def test_fixed_promo_for_foreign_client_within_a_cent_per_unit_for_every_price_and_rate():
    """Price and promo are each netted of VAT and rounded on their own, so
    the line can be a cent per unit off domestic / (1 + rate) — never more."""
    for price in PRICES:
        for rate in TAX_RATES:
            for value in (0.1, 0.5, 2.0):
                for quantity in (1, 3):
                    domestic, foreign = Cart(), Cart()
                    foreign.retax_for_client(False)
                    for cart in (domestic, foreign):
                        cart.add_product(_product(1, price, tax=rate, promo=_promo("fixed", value)),
                                         quantity=quantity)
                    expected = domestic.total / (1 + rate / 100)
                    assert abs(foreign.total - expected) <= 0.01 * quantity + 0.005, (
                        f"{quantity} x {price} @{rate}%, {value} off: {foreign.total} vs {expected:.3f}")


@pytest.mark.parametrize("kind, value, expected", [("percent", 20, 8.0), ("fixed", 2.0, 8.35)])
def test_attaching_a_foreign_client_after_ringing_up_reprices_the_promo(kind, value, expected):
    """The usual order: items first, Client button after. The promo line
    must follow the line's new price, same as when the client came first."""
    after, before = Cart(), Cart()
    after.add_product(_product(1, 12.1, tax=21, promo=_promo(kind, value)))
    after.retax_for_client(False)
    before.retax_for_client(False)
    before.add_product(_product(1, 12.1, tax=21, promo=_promo(kind, value)))

    assert after.total == before.total == expected
    assert _nets(after) == _nets(before)


def test_switching_back_to_a_domestic_client_restores_the_promo():
    cart = Cart()
    cart.add_product(_product(1, 12.1, tax=21, promo=_promo("percent", 20)))
    cart.retax_for_client(False)
    cart.retax_for_client(True)

    assert cart.total == 9.68


def _nets(cart: Cart) -> list[float]:
    return [line.net for line in cart.net_lines()]


def test_manual_percent_discount_stays_that_percent_when_a_foreign_client_is_attached():
    cart = Cart()
    cart.add_product(_product(1, 12.10, tax=21))
    cart.apply_percent_discount(10)

    cart.retax_for_client(False)

    assert cart.entries[0].line_total == 10.0
    assert cart.entries[1].amount == 1.0  # 10% of the net price, not 1.21
    assert cart.total == 9.0


def test_manual_amount_discount_comes_off_net_of_vat_like_its_price():
    cart = Cart()
    cart.add_product(_product(1, 12.10, tax=21))
    cart.apply_amount_discount(2.42)

    cart.retax_for_client(False)
    assert cart.entries[1].amount == 2.0
    assert cart.entries[1].label == "MANUAL DISCOUNT 2.00"

    cart.retax_for_client(True)
    assert cart.entries[1].amount == 2.42
    assert cart.total == 9.68


def test_removing_a_line_updates_the_amount_in_a_section_discount_label():
    cart = Cart()
    a, b = _product(1, 10.0), _product(2, 10.0)
    cart.add_product(a)
    cart.add_product(b)
    cart.add_subtotal()
    discount = cart.apply_amount_discount(4.0)

    cart.remove_entry(cart.entries[0])

    assert discount.amount == 2.0
    assert discount.label == "MANUAL DISCOUNT 2.00"


def test_removing_a_line_takes_its_share_off_the_section_discount():
    """The discount stays on the lines it was given for — it doesn't slide
    onto whatever line ends up before it."""
    cart = Cart()
    cart.add_product(_product(1, 10.0))
    cart.add_product(_product(2, 5.0))
    cart.add_subtotal()
    discount = cart.apply_percent_discount(10)  # 1.00 + 0.50
    cart.add_product(_product(3, 2.0))

    assert cart.remove_entry(cart.entries[1]) == "removed"

    assert discount.amount == 1.0
    assert _nets(cart) == [9.0, 2.0]
    assert cart.total == 11.0


def test_removing_the_only_line_of_a_discount_removes_the_discount():
    cart = Cart()
    cart.add_product(_product(1, 10.0))
    cart.add_product(_product(2, 5.0))
    cart.apply_amount_discount(1.0)

    cart.remove_entry(cart.entries[1])

    assert not any(isinstance(e, DiscountEntry) for e in cart.entries)
    assert cart.total == 10.0


def test_reversal_gives_back_only_the_reversed_lines_share():
    cart = Cart()
    cart.add_product(_product(1, 10.0))
    cart.add_product(_product(2, 5.0))
    cart.add_subtotal()
    cart.apply_percent_discount(10)  # 1.00 off line 1, 0.50 off line 2

    reversal = cart.reverse(cart.entries[1])

    void = cart.entries[-1]
    assert (void.label, void.amount, void.is_void) == ("VOID MANUAL DISCOUNT 10%", -0.5, True)
    assert void.allocations[0].item is reversal
    assert cart.total == 9.0  # line 1 with its own 10% still off


def test_removing_a_void_discount_row_removes_its_reversal():
    """The VOID row belongs to its reversal, the way a promo row belongs to
    its item — deleting it alone would take the discount back twice."""
    cart = Cart()
    cart.add_product(_product(1, 10.0))
    cart.apply_amount_discount(1.0)
    original = cart.entries[0]
    original.locked = True
    cart.remove_entry(original)  # reversed

    assert cart.remove_entry(cart.entries[-1]) == "removed"

    assert not original.has_reversal
    assert [type(e) for e in cart.entries] == [CartItem, DiscountEntry]
    assert cart.total == 9.0


def test_a_locked_line_is_reversed_once_only():
    cart = Cart()
    cart.add_product(_product(1, 10.0))
    cart.entries[0].locked = True

    assert cart.remove_entry(cart.entries[0]) == "reversed"
    assert cart.remove_entry(cart.entries[0]) is None
    assert len(cart.entries) == 2


def test_reversal_and_voided_lines_take_no_discount():
    cart = Cart()
    cart.add_product(_product(1, 10.0))
    cart.reverse(cart.entries[0])

    assert cart.discount_base() is None
    assert cart.apply_percent_discount(10) is None


def test_allocations_survive_a_snapshot_round_trip():
    cart = Cart()
    cart.add_product(_product(1, 10.0))
    cart.add_product(_product(2, 5.0))
    cart.add_subtotal()
    cart.apply_percent_discount(10)
    cart.reverse(cart.entries[1])

    reloaded = Cart.from_snapshot(cart.to_snapshot())

    assert _nets(reloaded) == _nets(cart) == [9.0, 4.5, -4.5]
    assert all(e.allocations for e in reloaded.entries if isinstance(e, DiscountEntry))


def test_snapshot_from_before_allocations_loads_as_it_was_charged():
    """No "allocations" key: aimed by position, then pinned, so reversing
    a line of the reopened sale gives back exactly its share."""
    old = ('[{"type": "item", "product_id": 1, "product_name": "A", "product_barcode": "1",'
           ' "unit_price": 10.0, "quantity": 1, "tax_rate": 21},'
           ' {"type": "item", "product_id": 2, "product_name": "B", "product_barcode": "2",'
           ' "unit_price": 5.0, "quantity": 1, "tax_rate": 21},'
           ' {"type": "subtotal"},'
           ' {"type": "discount", "amount": 1.5, "label": "MANUAL DISCOUNT 10%"}]')

    cart = Cart.from_snapshot(old)
    assert _nets(cart) == [9.0, 4.5]

    cart.reverse(cart.entries[1])
    assert cart.total == 9.0


def test_snapshot_with_allocations_that_dont_add_up_falls_back_to_position():
    cart = Cart()
    cart.add_product(_product(1, 10.0))
    cart.apply_amount_discount(1.0)
    snapshot = cart.to_snapshot().replace('"allocations": [[0, 1.0]]', '"allocations": [[0, 7.0]]')

    assert _nets(Cart.from_snapshot(snapshot)) == [9.0]


# ── Random tickets ───────────────────────────────────────────────────────

def test_net_lines_add_up_to_the_till_total():
    for seed in SEEDS:
        cart = _random_ticket(seed)
        nets = round(sum(line.net for line in cart.net_lines()), 2)
        assert nets == cart.total, f"seed {seed}: lines {nets} != total {cart.total}\n{_describe(cart)}"


def test_net_lines_are_consistent():
    """gross - discount == net, and net == tax + net_excl, on every line."""
    for seed in SEEDS:
        cart = _random_ticket(seed)
        for line in cart.net_lines():
            assert round(line.gross - line.discount, 2) == line.net, f"seed {seed}\n{_describe(cart)}"
            assert round(line.tax + line.net_excl, 2) == line.net, f"seed {seed}\n{_describe(cart)}"


def test_promo_lines_match_their_items():
    """Every promo line is its item's current promo amount, whatever was
    done since (client attached, line reversed, reopened...)."""
    for seed in SEEDS:
        cart = _random_ticket(seed)
        for entry in cart.entries:
            if isinstance(entry, DiscountEntry) and entry.is_promo:
                item = entry.allocations[0].item
                assert entry.amount == item.discount_amount, f"seed {seed}\n{_describe(cart)}"


def test_snapshot_round_trip_keeps_every_line_amount():
    """What's saved on the sale/invoice reloads to exactly what was charged."""
    for seed in SEEDS:
        cart = _random_ticket(seed)
        reloaded = Cart.from_snapshot(cart.to_snapshot())
        assert _nets(reloaded) == _nets(cart), f"seed {seed}\n{_describe(cart)}"
        assert reloaded.total == cart.total, f"seed {seed}\n{_describe(cart)}"


def test_a_reversed_line_and_its_reversal_net_to_zero():
    for seed in SEEDS:
        cart = _random_ticket(seed)
        net = {id(line.item): line.net for line in cart.net_lines()}
        for item in (e for e in cart.entries if isinstance(e, CartItem) and e.is_reversal):
            pair = round(net[id(item)] + net[id(item.reversal_of)], 2)
            assert pair == 0, f"seed {seed}: {item.product_name} nets to {pair}\n{_describe(cart)}"


def test_invoice_lines_add_up_to_the_till_total():
    """Compared excl. VAT, as sent: VAT is then added by the ERP itself."""
    for seed in SEEDS:
        cart = _random_ticket(seed)
        invoice_excl = round(sum(l.line_total_excl_tax for l in invoice_lines(_invoice_for(cart))), 2)
        till_excl = round(sum(line.net_excl for line in cart.net_lines()), 2)
        assert invoice_excl == till_excl, (
            f"seed {seed}: invoice {invoice_excl} != till {till_excl} (excl. VAT)\n{_describe(cart)}")
