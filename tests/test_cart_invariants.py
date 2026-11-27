"""
Agreement checks between every place a ticket's money is worked out: the
till total, the per-line amounts saved on the sale (Cart.net_lines), and
the invoice lines sent to the ERP (invoice_lines).

Besides hand-written cases, random tickets are built (tools/sales_factory.py)
from a seeded random.Random (reproducible: a failure names its seed) out of the same
steps a cashier can take — items, promos, item/subtotal discounts, a
non-Belgian client, refund mode, then reopening the sale to reverse or
remove lines.

Tests marked xfail(strict=True) pin bugs that are known and not fixed yet;
once fixed they XPASS, which fails the run as a reminder to drop the mark.
"""
import random
from types import SimpleNamespace

import pytest

from app.core.sale.cart import Cart, CartItem, DiscountEntry, SubtotalMarker
from app.constants.vat import VAT_RATES
from app.core.sale.sales_service import invoice_lines
from tools.sales_factory import PRICES, fake_promo, random_ticket

SEEDS = range(500)


def _product(pid, price, tax=21, unit="pcs", promo=None):
    return SimpleNamespace(
        id=pid, name=f"P{pid}", barcode=str(pid), price=price, tax=tax, unit=unit,
        is_open_price=False, active_promo_item=promo,
    )


def _random_ticket(seed: int) -> Cart:
    """A ticket as finally paid (see tools/sales_factory.random_ticket), from
    made-up products with a random price, VAT rate and unit."""
    rng = random.Random(seed)
    next_pid = iter(range(1, 1000))

    def pick_product(rng):
        unit = "kg" if rng.random() < 0.2 else "pcs"
        return _product(next(next_pid), rng.choice(PRICES), rng.choice(VAT_RATES), unit)

    return random_ticket(rng, pick_product)[1]


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
        (1.4151, 10.0, 3.82),
    ]
    assert round(sum(l.line_total_excl_tax for l in lines), 2) == 11.46


def test_two_subtotal_discounts_stack_exactly_with_rounding_on_the_lines():
    """3 broccoli at 1.50 + 15 kg carrot at 0.99 = 19.35, subtotal, 10% off
    twice: the second comes off what's left (1.94 then 1.74, 19% not 20%).
    Each discount's shares sum to it exactly; the cent rounding shows only
    in the per-line % (18.8889 / 19.0572 instead of 19.00)."""
    cart = Cart()
    cart.add_product(_product(1, 1.5, tax=6), quantity=3)
    cart.add_product(_product(2, 0.99, tax=6, unit="kg"), quantity=15)
    cart.add_subtotal()
    first = cart.apply_percent_discount(10)
    second = cart.apply_percent_discount(10)

    assert (first.amount, [a.amount for a in first.allocations]) == (1.94, [0.45, 1.49])
    assert (second.amount, [a.amount for a in second.allocations]) == (1.74, [0.40, 1.34])
    assert cart.total == 15.67
    assert round(sum(_nets(cart)), 2) == cart.total

    lines = invoice_lines(_invoice_for(cart))
    assert [(l.discount_percent, l.line_total_excl_tax) for l in lines] == [(18.8889, 3.44), (19.0572, 11.34)]


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
        cart.add_product(_product(1, 12.1, tax=21, promo=fake_promo("percent", 20)))

    assert foreign.total == round(domestic.total / 1.21, 2)


def test_fixed_promo_for_foreign_client_is_the_domestic_price_net_of_vat():
    domestic, foreign = Cart(), Cart()
    foreign.retax_for_client(False)
    for cart in (domestic, foreign):
        cart.add_product(_product(1, 12.1, tax=21, promo=fake_promo("fixed", 2.0)))

    assert foreign.total == round(domestic.total / 1.21, 2)


def test_fixed_promo_for_foreign_client_within_a_cent_per_unit_for_every_price_and_rate():
    """Price and promo are each netted of VAT and rounded on their own, so
    the line can be a cent per unit off domestic / (1 + rate) — never more."""
    for price in PRICES:
        for rate in VAT_RATES:
            for value in (0.1, 0.5, 2.0):
                for quantity in (1, 3):
                    domestic, foreign = Cart(), Cart()
                    foreign.retax_for_client(False)
                    for cart in (domestic, foreign):
                        cart.add_product(_product(1, price, tax=rate, promo=fake_promo("fixed", value)),
                                         quantity=quantity)
                    expected = domestic.total / (1 + rate / 100)
                    assert abs(foreign.total - expected) <= 0.01 * quantity + 0.005, (
                        f"{quantity} x {price} @{rate}%, {value} off: {foreign.total} vs {expected:.3f}")


@pytest.mark.parametrize("kind, value, expected", [("percent", 20, 8.0), ("fixed", 2.0, 8.35)])
def test_attaching_a_foreign_client_after_ringing_up_reprices_the_promo(kind, value, expected):
    """The usual order: items first, Client button after. The promo line
    must follow the line's new price, same as when the client came first."""
    after, before = Cart(), Cart()
    after.add_product(_product(1, 12.1, tax=21, promo=fake_promo(kind, value)))
    after.retax_for_client(False)
    before.retax_for_client(False)
    before.add_product(_product(1, 12.1, tax=21, promo=fake_promo(kind, value)))

    assert after.total == before.total == expected
    assert _nets(after) == _nets(before)


def test_switching_back_to_a_domestic_client_restores_the_promo():
    cart = Cart()
    cart.add_product(_product(1, 12.1, tax=21, promo=fake_promo("percent", 20)))
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


def test_snapshot_discount_without_allocations_is_dropped():
    """No "allocations" key: nothing says which items it came off, so it
    goes rather than leaving the total and the line nets disagreeing."""
    old = ('[{"type": "item", "product_id": 1, "product_name": "A", "product_barcode": "1",'
           ' "unit_price": 10.0, "quantity": 1, "tax_rate": 21, "base_tax_rate": 21, "base_unit_price": 10.0},'
           ' {"type": "discount", "amount": 1.5, "label": "MANUAL DISCOUNT 1.50"}]')

    cart = Cart.from_snapshot(old)

    assert not any(isinstance(e, DiscountEntry) for e in cart.entries)
    assert _nets(cart) == [10.0] and cart.total == 10.0


def test_snapshot_discount_whose_allocations_dont_add_up_is_dropped():
    cart = Cart()
    cart.add_product(_product(1, 10.0))
    cart.apply_amount_discount(1.0)
    snapshot = cart.to_snapshot().replace('"allocations": [[0, 1.0]]', '"allocations": [[0, 7.0]]')

    reloaded = Cart.from_snapshot(snapshot)

    assert _nets(reloaded) == [10.0] and reloaded.total == 10.0


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


def test_a_discount_on_a_reversed_line_cant_be_removed():
    """Its share was given back by a VOID row; removing it would leave the
    VOID paying back a discount that's gone (an empty ticket at 1.00)."""
    cart = Cart()
    cart.add_product(_product(1, 10.0))
    discount = cart.apply_percent_discount(10)
    cart.entries[0].locked = True
    cart.reverse(cart.entries[0])

    assert cart.remove_entry(discount) is None
    assert cart.total == 0.0


def test_a_subtotal_whose_discount_covers_a_reversed_line_cant_be_removed():
    cart = Cart()
    cart.add_product(_product(1, 10.0))
    cart.add_product(_product(2, 10.0))
    cart.add_subtotal()
    cart.apply_amount_discount(4.0)
    cart.entries[0].locked = True
    cart.reverse(cart.entries[0])
    marker = next(e for e in cart.entries if isinstance(e, SubtotalMarker))

    assert cart.remove_entry(marker) is None
    assert cart.total == 8.0


def test_removing_the_reversal_frees_its_discount_again():
    cart = Cart()
    cart.add_product(_product(1, 10.0))
    discount = cart.apply_percent_discount(10)
    cart.entries[0].locked = True
    reversal = cart.reverse(cart.entries[0])

    assert cart.remove_entry(reversal) == "removed"
    assert cart.remove_entry(discount) == "removed"
    assert cart.total == 10.0
