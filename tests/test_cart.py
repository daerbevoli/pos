"""
Tests for the Cart/CartItem/DiscountEntry/PaymentEntry/SubtotalMarker
dataclasses in app.core.sales_service, and the _calc_tax helper.
"""
import json

import pytest

from app.core.sales_service import (
    Cart, CartItem, DiscountEntry, PaymentEntry, SubtotalMarker, calc_tax,
)


class _FakeProduct:
    def __init__(self, id, name="Item", barcode="123", price=1.0, unit="pcs", tax=21, is_open_price=False, promo=None):
        self.id = id
        self.name = name
        self.barcode = barcode
        self.price = price
        self.unit = unit
        self.tax = tax
        self.is_open_price = is_open_price
        self._promo = promo

    @property
    def active_promo_item(self):
        """Mirrors Product.active_promo_item. The fake _FakePromo doubles
        as its own PromoItem here (it has discount_type/discount_value and
        a self-referential .promo), which is enough for Cart.add_product."""
        if self._promo and self._promo.is_active:
            return self._promo
        return None


class _FakePromo:
    def __init__(self, name="Promo", discount_type="percent", discount_value=10.0, is_active=True):
        self.name = name
        self.discount_type = discount_type
        self.discount_value = discount_value
        self.is_active = is_active
        self.promo = self  # so promo_item.promo.name resolves, like the real PromoItem.promo relationship


# ── CartItem.line_total ──────────────────────────────────────────────────

def test_cart_item_line_total_basic():
    item = CartItem(product_id=1, product_name="A", product_barcode="1", unit_price=2.5, quantity=3)
    assert item.line_total == 7.5


def test_cart_item_line_total_with_discount():
    item = CartItem(product_id=1, product_name="A", product_barcode="1", unit_price=2.5, quantity=3, discount=1.0)
    assert item.line_total == 6.5


def test_cart_item_line_total_none_quantity_is_zero():
    item = CartItem(product_id=1, product_name="A", product_barcode="1", unit_price=2.5, quantity=None)
    assert item.line_total == 0.0


def test_cart_item_line_total_rounds_to_2dp():
    item = CartItem(product_id=1, product_name="A", product_barcode="1", unit_price=0.1, quantity=3)
    assert item.line_total == 0.3


# ── CartItem.promo_discount ──────────────────────────────────────────────

def test_promo_discount_percent():
    """promo_discount is no longer folded into line_total — it's
    materialized as its own DiscountEntry by sync_promo_discounts(), so the
    item's own line_total stays the full, undiscounted price."""
    item = CartItem(product_id=1, product_name="A", product_barcode="1", unit_price=10.0, quantity=2,
                     promo_type="percent", promo_value=15.0)
    assert item.promo_discount == 3.0
    assert item.line_total == 20.0


def test_promo_discount_fixed():
    item = CartItem(product_id=1, product_name="A", product_barcode="1", unit_price=10.0, quantity=2,
                     promo_type="fixed", promo_value=1.5)
    assert item.promo_discount == 3.0
    assert item.line_total == 20.0


def test_promo_discount_fixed_never_exceeds_line_total():
    item = CartItem(product_id=1, product_name="A", product_barcode="1", unit_price=1.0, quantity=1,
                     promo_type="fixed", promo_value=99.0)
    assert item.promo_discount == 1.0
    assert item.line_total == 1.0


def test_promo_discount_fixed_reversal_line_is_sign_aware():
    """A reversal line (negative quantity) with the same promo fields copied
    onto it must produce a negative discount capped at the same magnitude,
    so its DiscountEntry exactly undoes the original line's."""
    item = CartItem(product_id=1, product_name="A", product_barcode="1", unit_price=1.0, quantity=-1,
                     promo_type="fixed", promo_value=99.0)
    assert item.promo_discount == -1.0


def test_promo_discount_percent_reversal_line_is_negative():
    item = CartItem(product_id=1, product_name="A", product_barcode="1", unit_price=10.0, quantity=-2,
                     promo_type="percent", promo_value=15.0)
    assert item.promo_discount == -3.0


def test_promo_discount_none_when_no_promo():
    item = CartItem(product_id=1, product_name="A", product_barcode="1", unit_price=10.0, quantity=2)
    assert item.promo_discount == 0.0


def test_promo_discount_zero_for_pending_item():
    """A pending weight item has no quantity yet, so the promo can't be
    priced until the amount is filled in — same as line_total."""
    item = CartItem(product_id=1, product_name="A", product_barcode="1", unit_price=10.0, quantity=None,
                     promo_type="percent", promo_value=15.0)
    assert item.promo_discount == 0.0


def test_promo_discount_recomputes_after_pending_quantity_is_filled_in():
    """Regression guard: promo terms are set once at add_product() time, but
    the discount itself must stay live off quantity so a pending weight item
    still gets priced correctly once its amount is entered."""
    item = CartItem(product_id=1, product_name="A", product_barcode="1", unit_price=10.0, quantity=None,
                     promo_type="percent", promo_value=15.0)
    item.quantity = 2
    assert item.promo_discount == 3.0
    assert item.line_total == 20.0


# ── DiscountEntry ─────────────────────────────────────────────────────────

def test_discount_entry_line_total_is_negative():
    d = DiscountEntry(amount=5.0, label="5.00")
    assert d.line_total == -5.0


def test_discount_entry_line_total_rounds_to_2dp():
    d = DiscountEntry(amount=1.999, label="x")
    assert d.line_total == -2.0


# ── Cart aggregate properties ───────────────────────────────────────────

def test_cart_subtotal_sums_items_and_discounts_only():
    cart = Cart(entries=[
        CartItem(product_id=1, product_name="A", product_barcode="1", unit_price=10.0, quantity=1),
        DiscountEntry(amount=2.0, label="2"),
        PaymentEntry(method="cash", amount=100.0),
        SubtotalMarker(),
    ])
    assert cart.subtotal == 8.0


def test_cart_total_equals_subtotal():
    cart = Cart(entries=[CartItem(product_id=1, product_name="A", product_barcode="1", unit_price=3.0, quantity=2)])
    assert cart.total == cart.subtotal == 6.0


def test_cart_paid_total_sums_payment_entries():
    cart = Cart(entries=[
        PaymentEntry(method="cash", amount=10.0),
        PaymentEntry(method="card", amount=5.5),
    ])
    assert cart.paid_total == 15.5


def test_cart_remaining_due():
    cart = Cart(entries=[
        CartItem(product_id=1, product_name="A", product_barcode="1", unit_price=20.0, quantity=1),
        PaymentEntry(method="cash", amount=5.0),
    ])
    assert cart.remaining_due == 15.0


def test_cart_item_count_ignores_pending_items():
    cart = Cart(entries=[
        CartItem(product_id=1, product_name="A", product_barcode="1", unit_price=1.0, quantity=3),
        CartItem(product_id=2, product_name="B", product_barcode="2", unit_price=1.0, quantity=None),
    ])
    assert cart.item_count == 3


def test_empty_cart_properties():
    cart = Cart()
    assert cart.subtotal == 0.0
    assert cart.total == 0.0
    assert cart.paid_total == 0.0
    assert cart.remaining_due == 0.0
    assert cart.item_count == 0


# ── Cart.add_product merging ─────────────────────────────────────────────

def test_add_product_creates_new_entry():
    cart = Cart()
    product = _FakeProduct(id=1, name="Apple", price=0.5)
    cart.add_product(product, quantity=2)

    assert len(cart.entries) == 1
    entry = cart.entries[0]
    assert isinstance(entry, CartItem)
    assert entry.product_id == 1
    assert entry.quantity == 2
    assert entry.unit_price == 0.5
    assert entry.tax_rate == 21
    assert entry.base_tax_rate == 21
    assert entry.base_unit_price == 0.5


def test_add_product_open_price_starts_pending():
    """An open-price product (price is always 0.0 on the product itself)
    is added as a pending line, like a weight item awaiting its quantity —
    except it's unit_price that's missing, not quantity."""
    cart = Cart()
    product = _FakeProduct(id=1, name="Loose Snacks", price=0.0, is_open_price=True)
    cart.add_product(product, quantity=1)

    entry = cart.entries[0]
    assert entry.is_open_price is True
    assert entry.unit_price == 0.0
    assert entry.pending is True
    assert entry.line_total == 0.0

    entry.unit_price = 3.25
    assert entry.pending is False
    assert entry.line_total == 3.25


def test_add_product_same_product_creates_separate_rows():
    """add_product() always appends a new CartItem — scanning the same
    product again does not merge into the earlier line's quantity."""
    cart = Cart()
    product = _FakeProduct(id=1, price=1.0)
    cart.add_product(product, quantity=2)
    cart.add_product(product, quantity=3)

    items = [e for e in cart.entries if isinstance(e, CartItem)]
    assert len(items) == 2
    assert items[0].quantity == 2
    assert items[1].quantity == 3


def test_add_product_does_not_merge_across_subtotal_marker():
    cart = Cart()
    product = _FakeProduct(id=1, price=1.0)
    cart.add_product(product, quantity=2)
    cart.add_subtotal()
    cart.add_product(product, quantity=3)

    items = [e for e in cart.entries if isinstance(e, CartItem)]
    assert len(items) == 2
    assert items[0].quantity == 2
    assert items[1].quantity == 3


def test_add_product_pending_item_always_gets_own_row():
    cart = Cart()
    product = _FakeProduct(id=1, unit="kg", price=2.0)
    cart.add_product(product, quantity=None)
    cart.add_product(product, quantity=None)

    items = [e for e in cart.entries if isinstance(e, CartItem)]
    assert len(items) == 2
    assert all(i.quantity is None for i in items)


def test_add_product_creates_new_row_regardless_of_items_between():
    """Rescanning a product further back in the cart (with other items,
    pending or not, in between) still gets its own new row rather than
    merging into the earlier line."""
    cart = Cart()
    p1 = _FakeProduct(id=1, price=1.0)
    p2 = _FakeProduct(id=2, unit="kg", price=2.0)
    cart.add_product(p1, quantity=2)
    cart.add_product(p2, quantity=None)
    cart.add_product(p1, quantity=1)

    items = [e for e in cart.entries if isinstance(e, CartItem)]
    assert len(items) == 3
    p1_entries = [i for i in items if i.product_id == 1]
    assert [i.quantity for i in p1_entries] == [2, 1]


def test_add_product_different_products_do_not_merge():
    cart = Cart()
    p1 = _FakeProduct(id=1, price=1.0)
    p2 = _FakeProduct(id=2, price=2.0)
    cart.add_product(p1, quantity=1)
    cart.add_product(p2, quantity=1)

    assert len(cart.entries) == 2


def test_add_product_copies_active_promo_onto_the_line():
    """add_product() copies the promo terms onto the CartItem AND — via
    sync_promo_discounts() — materializes a labeled DiscountEntry right
    after it, same as a manual discount."""
    cart = Cart()
    promo = _FakePromo(name="New Year Promo", discount_type="percent", discount_value=15.0)
    product = _FakeProduct(id=1, name="Apple", price=10.0, promo=promo)
    cart.add_product(product, quantity=2)

    assert len(cart.entries) == 2
    entry, discount = cart.entries
    assert entry.promo_name == "New Year Promo"
    assert entry.promo_type == "percent"
    assert entry.promo_value == 15.0
    assert entry.promo_discount == 3.0
    assert entry.line_total == 20.0  # full price — the promo is the separate line below

    assert isinstance(discount, DiscountEntry)
    assert discount.is_promo is True
    assert discount.label == "New Year Promo"
    assert discount.amount == 3.0
    assert discount.line_total == -3.0

    assert cart.subtotal == 17.0  # 20.0 gross - 3.0 promo


def test_add_product_ignores_inactive_promo():
    cart = Cart()
    promo = _FakePromo(is_active=False)
    product = _FakeProduct(id=1, price=10.0, promo=promo)
    cart.add_product(product, quantity=1)

    assert len(cart.entries) == 1  # no DiscountEntry synthesized
    entry = cart.entries[0]
    assert entry.promo_name is None
    assert entry.promo_discount == 0.0


def test_add_product_no_promo_leaves_fields_unset():
    cart = Cart()
    product = _FakeProduct(id=1, price=10.0)
    cart.add_product(product, quantity=1)

    entry = cart.entries[0]
    assert entry.promo_name is None
    assert entry.promo_type is None
    assert entry.promo_value == 0.0


# ── Cart.sync_promo_discounts ────────────────────────────────────────────

def test_sync_promo_discounts_scales_with_quantity_after_pending_fill_in():
    """The exact scenario asked for: a promo'd weight item starts pending
    (quantity unknown, so no discount yet), then once the amount is typed
    in and sync_promo_discounts() is called, the DiscountEntry appears
    with the correctly scaled amount."""
    cart = Cart()
    promo = _FakePromo(name="New Year Promo", discount_type="percent", discount_value=15.0)
    product = _FakeProduct(id=1, unit="kg", price=10.0, promo=promo)
    cart.add_product(product, quantity=None)

    assert len(cart.entries) == 1  # pending — no discount amount to show yet

    cart.entries[0].quantity = 2
    cart.sync_promo_discounts()

    assert len(cart.entries) == 2
    item, discount = cart.entries
    assert discount.amount == 3.0

    # Bump the quantity again — the discount must scale up with it.
    item.quantity = 4
    cart.sync_promo_discounts()
    assert len(cart.entries) == 2
    assert cart.entries[1].amount == 6.0


def test_sync_promo_discounts_does_not_duplicate_on_repeated_calls():
    cart = Cart()
    promo = _FakePromo(discount_type="percent", discount_value=10.0)
    product = _FakeProduct(id=1, price=10.0, promo=promo)
    cart.add_product(product, quantity=1)  # add_product() already syncs once

    cart.sync_promo_discounts()
    cart.sync_promo_discounts()

    discounts = [e for e in cart.entries if isinstance(e, DiscountEntry)]
    assert len(discounts) == 1


def test_sync_promo_discounts_leaves_manual_discounts_alone():
    cart = Cart()
    promo = _FakePromo(discount_type="percent", discount_value=10.0)
    product = _FakeProduct(id=1, price=10.0, promo=promo)
    cart.add_product(product, quantity=1)
    cart.entries.append(DiscountEntry(amount=1.0, label="Loyalty card"))

    cart.sync_promo_discounts()

    manual = [e for e in cart.entries if isinstance(e, DiscountEntry) and not e.is_promo]
    promo_driven = [e for e in cart.entries if isinstance(e, DiscountEntry) and e.is_promo]
    assert len(manual) == 1 and manual[0].label == "Loyalty card"
    assert len(promo_driven) == 1


def test_remove_item_drops_its_promo_discount_too():
    cart = Cart()
    promo = _FakePromo(discount_type="percent", discount_value=10.0)
    product = _FakeProduct(id=1, price=10.0, promo=promo)
    cart.add_product(product, quantity=1)
    assert len(cart.entries) == 2

    cart.remove_item(1)

    assert cart.entries == []


def test_sync_promo_discounts_scales_with_quantity_stepper():
    """Mirrors pos_screen.py's +/- quantity stepper: quantity is mutated
    directly on the existing CartItem (not through a pending fill-in),
    followed by sync_promo_discounts()."""
    cart = Cart()
    promo = _FakePromo(discount_type="percent", discount_value=10.0)
    product = _FakeProduct(id=1, price=10.0, promo=promo)
    cart.add_product(product, quantity=1)
    assert cart.entries[1].amount == 1.0

    cart.entries[0].quantity += 1
    cart.sync_promo_discounts()
    assert cart.entries[1].amount == 2.0

    cart.entries[0].quantity -= 1
    cart.sync_promo_discounts()
    assert cart.entries[1].amount == 1.0


def test_sync_promo_discounts_drops_entry_for_a_reversed_line():
    """Mirrors pos_screen.py's reversal flow on a reopened ticket: the
    original line is flagged has_reversal and a negative-quantity reversal
    line (without promo fields — it doesn't need its own) is appended.
    The original's promo discount line should disappear rather than get an
    offsetting entry next to it."""
    cart = Cart()
    promo = _FakePromo(discount_type="percent", discount_value=10.0)
    product = _FakeProduct(id=1, price=10.0, promo=promo)
    cart.add_product(product, quantity=2)
    original = cart.entries[0]
    assert len([e for e in cart.entries if isinstance(e, DiscountEntry)]) == 1

    original.has_reversal = True
    cart.entries.append(CartItem(
        product_id=original.product_id, product_name=original.product_name,
        product_barcode=original.product_barcode, unit_price=original.unit_price,
        quantity=-original.quantity, unit=original.unit, is_reversal=True, reversal_of=original,
    ))
    cart.sync_promo_discounts()

    assert [type(e).__name__ for e in cart.entries] == ["CartItem", "CartItem"]
    assert cart.subtotal == 0.0  # gross fully cancels, no leftover discount


# ── Subtotal markers ─────────────────────────────────────────────────────

def test_add_subtotal_appends_marker():
    cart = Cart()
    cart.add_subtotal()
    assert len(cart.entries) == 1
    assert isinstance(cart.entries[0], SubtotalMarker)


def test_clear_subtotals_removes_only_markers():
    cart = Cart()
    product = _FakeProduct(id=1, price=1.0)
    cart.add_product(product, quantity=1)
    cart.add_subtotal()
    cart.add_product(product, quantity=1)

    cart.clear_subtotals()

    assert all(not isinstance(e, SubtotalMarker) for e in cart.entries)
    assert len(cart.entries) == 2


# ── remove_item / clear ──────────────────────────────────────────────────

def test_remove_item_removes_first_match():
    cart = Cart()
    p1 = _FakeProduct(id=1, price=1.0)
    p2 = _FakeProduct(id=2, price=2.0)
    cart.add_product(p1, quantity=1)
    cart.add_product(p2, quantity=1)

    cart.remove_item(1)

    assert len(cart.entries) == 1
    assert cart.entries[0].product_id == 2


def test_remove_item_missing_product_is_noop():
    cart = Cart()
    product = _FakeProduct(id=1, price=1.0)
    cart.add_product(product, quantity=1)
    cart.remove_item(999)
    assert len(cart.entries) == 1


def test_clear_empties_all_entries():
    cart = Cart()
    product = _FakeProduct(id=1, price=1.0)
    cart.add_product(product, quantity=1)
    cart.add_subtotal()
    cart.clear()
    assert cart.entries == []


# ── retax_for_client ─────────────────────────────────────────────────────

def test_retax_for_client_zeroes_rate_and_nets_price_for_non_domestic():
    cart = Cart()
    cart.add_product(_FakeProduct(id=1, price=12.10, tax=21), quantity=1)
    cart.add_product(_FakeProduct(id=2, price=1.06, tax=6), quantity=1)

    cart.retax_for_client(is_domestic=False)

    assert [e.tax_rate for e in cart.entries] == [0, 0]
    assert [e.base_tax_rate for e in cart.entries] == [21, 6]
    assert [e.unit_price for e in cart.entries] == [10.0, 1.0]
    assert [e.base_unit_price for e in cart.entries] == [12.10, 1.06]


def test_retax_for_client_restores_base_rate_and_price_for_domestic():
    cart = Cart()
    cart.add_product(_FakeProduct(id=1, price=12.10, tax=21), quantity=1)
    cart.retax_for_client(is_domestic=False)
    assert cart.entries[0].tax_rate == 0
    assert cart.entries[0].unit_price == 10.0

    cart.retax_for_client(is_domestic=True)
    assert cart.entries[0].tax_rate == 21
    assert cart.entries[0].unit_price == 12.10


def test_retax_for_client_zero_rate_item_price_is_unaffected():
    cart = Cart()
    cart.add_product(_FakeProduct(id=1, price=5.0, tax=0), quantity=1)
    cart.retax_for_client(is_domestic=False)
    assert cart.entries[0].unit_price == 5.0


def test_retax_for_client_ignores_non_item_entries():
    cart = Cart()
    cart.add_product(_FakeProduct(id=1, price=1.0, tax=21), quantity=1)
    cart.add_subtotal()

    cart.retax_for_client(is_domestic=False)  # should not raise on SubtotalMarker

    assert cart.entries[0].tax_rate == 0
    assert isinstance(cart.entries[1], SubtotalMarker)


def test_add_product_after_non_domestic_client_already_set_nets_price():
    """Items scanned *after* a foreign client is already attached should
    come in already netted, not just ones present at the time of the
    client change."""
    cart = Cart(is_domestic=False)
    cart.add_product(_FakeProduct(id=1, price=12.10, tax=21), quantity=1)

    entry = cart.entries[0]
    assert entry.tax_rate == 0
    assert entry.unit_price == 10.0
    assert entry.base_tax_rate == 21
    assert entry.base_unit_price == 12.10


def test_set_open_price_applies_current_client_vat_treatment():
    cart = Cart(is_domestic=False)
    product = _FakeProduct(id=1, name="Loose Snacks", price=0.0, tax=21, is_open_price=True)
    cart.add_product(product, quantity=1)
    entry = cart.entries[0]

    cart.set_open_price(entry, 12.10)

    assert entry.base_unit_price == 12.10
    assert entry.unit_price == 10.0


# ── Snapshot round-trip ───────────────────────────────────────────────────

def test_snapshot_round_trip_preserves_all_entry_types():
    cart = Cart(entries=[
        CartItem(
            product_id=1, product_name="Bread", product_barcode="111",
            unit_price=2.5, quantity=2, unit="pcs", tax_rate=0, base_tax_rate=6,
            base_unit_price=2.65, discount=0.5, is_reversal=False, has_reversal=True,
            promo_name="New Year Promo", promo_type="percent", promo_value=15.0,
        ),
        DiscountEntry(amount=1.0, label="1.00"),
        DiscountEntry(amount=0.375, label="New Year Promo", is_promo=True),
        SubtotalMarker(),
    ])

    snapshot = cart.to_snapshot()
    assert isinstance(snapshot, str)
    restored = Cart.from_snapshot(snapshot)

    assert len(restored.entries) == 4
    item = restored.entries[0]
    assert isinstance(item, CartItem)
    assert item.product_id == 1
    assert item.product_name == "Bread"
    assert item.unit_price == 2.5
    assert item.quantity == 2
    assert item.tax_rate == 0
    assert item.base_tax_rate == 6
    assert item.base_unit_price == 2.65
    assert item.discount == 0.5
    assert item.has_reversal is True
    assert item.promo_name == "New Year Promo"
    assert item.promo_type == "percent"
    assert item.promo_value == 15.0

    discount = restored.entries[1]
    assert isinstance(discount, DiscountEntry)
    assert discount.amount == 1.0
    assert discount.label == "1.00"
    assert discount.is_promo is False

    promo_discount = restored.entries[2]
    assert isinstance(promo_discount, DiscountEntry)
    assert promo_discount.amount == 0.375
    assert promo_discount.label == "New Year Promo"
    assert promo_discount.is_promo is True

    assert isinstance(restored.entries[3], SubtotalMarker)


def test_snapshot_round_trip_preserves_pending_quantity():
    cart = Cart(entries=[
        CartItem(product_id=1, product_name="Cheese", product_barcode="222", unit_price=5.0, quantity=None, unit="kg"),
    ])
    restored = Cart.from_snapshot(cart.to_snapshot())
    assert restored.entries[0].quantity is None


def test_from_snapshot_empty_string_returns_empty_cart():
    assert Cart.from_snapshot("").entries == []


def test_from_snapshot_defaults_missing_optional_fields():
    raw = json.dumps([{
        "type": "item", "product_id": 1, "product_name": "X",
        "product_barcode": "1", "unit_price": 1.0, "quantity": 1,
    }])
    restored = Cart.from_snapshot(raw)
    item = restored.entries[0]
    assert item.unit == "pcs"
    assert item.tax_rate == 0
    assert item.base_tax_rate == 0
    assert item.base_unit_price == 1.0
    assert item.discount == 0.0
    assert item.is_reversal is False
    assert item.has_reversal is False


def test_from_snapshot_missing_base_tax_rate_falls_back_to_tax_rate():
    """Sale snapshots saved before base_tax_rate existed should still
    round-trip without losing the item's real VAT rate."""
    raw = json.dumps([{
        "type": "item", "product_id": 1, "product_name": "X",
        "product_barcode": "1", "unit_price": 1.0, "quantity": 1,
        "tax_rate": 21,
    }])
    restored = Cart.from_snapshot(raw)
    assert restored.entries[0].tax_rate == 21
    assert restored.entries[0].base_tax_rate == 21


def test_from_snapshot_missing_base_unit_price_falls_back_to_unit_price():
    """Sale snapshots saved before base_unit_price existed should still
    round-trip without losing the item's real (domestic) price."""
    raw = json.dumps([{
        "type": "item", "product_id": 1, "product_name": "X",
        "product_barcode": "1", "unit_price": 12.10, "quantity": 1,
    }])
    restored = Cart.from_snapshot(raw)
    assert restored.entries[0].unit_price == 12.10
    assert restored.entries[0].base_unit_price == 12.10


# ── _calc_tax ─────────────────────────────────────────────────────────────

def test_calc_tax_zero_rate_returns_zero():
    assert calc_tax(100.0, 0) == 0.0


def test_calc_tax_extracts_vat_from_tax_inclusive_total():
    # 121 incl. 21% VAT -> 21 tax, 100 base
    assert calc_tax(121.0, 21) == 21.0


def test_calc_tax_rounds_to_2dp():
    result = calc_tax(10.0, 6)
    assert result == round(result, 2)
