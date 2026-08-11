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
    def __init__(self, id, name="Item", barcode="123", price=1.0, unit="pcs", tax=21):
        self.id = id
        self.name = name
        self.barcode = barcode
        self.price = price
        self.unit = unit
        self.tax = tax


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


# ── Snapshot round-trip ───────────────────────────────────────────────────

def test_snapshot_round_trip_preserves_all_entry_types():
    cart = Cart(entries=[
        CartItem(
            product_id=1, product_name="Bread", product_barcode="111",
            unit_price=2.5, quantity=2, unit="pcs", tax_rate=6,
            discount=0.5, is_reversal=False, has_reversal=True,
        ),
        DiscountEntry(amount=1.0, label="1.00"),
        SubtotalMarker(),
    ])

    snapshot = cart.to_snapshot()
    assert isinstance(snapshot, str)
    restored = Cart.from_snapshot(snapshot)

    assert len(restored.entries) == 3
    item = restored.entries[0]
    assert isinstance(item, CartItem)
    assert item.product_id == 1
    assert item.product_name == "Bread"
    assert item.unit_price == 2.5
    assert item.quantity == 2
    assert item.tax_rate == 6
    assert item.discount == 0.5
    assert item.has_reversal is True

    discount = restored.entries[1]
    assert isinstance(discount, DiscountEntry)
    assert discount.amount == 1.0
    assert discount.label == "1.00"

    assert isinstance(restored.entries[2], SubtotalMarker)


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
    assert item.discount == 0.0
    assert item.is_reversal is False
    assert item.has_reversal is False


# ── _calc_tax ─────────────────────────────────────────────────────────────

def test_calc_tax_zero_rate_returns_zero():
    assert calc_tax(100.0, 0) == 0.0


def test_calc_tax_extracts_vat_from_tax_inclusive_total():
    # 121 incl. 21% VAT -> 21 tax, 100 base
    assert calc_tax(121.0, 21) == 21.0


def test_calc_tax_rounds_to_2dp():
    result = calc_tax(10.0, 6)
    assert result == round(result, 2)
