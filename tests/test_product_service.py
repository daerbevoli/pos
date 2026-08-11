"""Tests for app.core.product_service.ProductService."""
import pytest

from app.core.product_service import ProductService
from app.models.models import Product, Category, StockMovement


def _make_product(session, **overrides):
    data = {"name": "Product A", "price": 1.0}
    data.update(overrides)
    return ProductService.create(session, **data)


# ── CRUD ─────────────────────────────────────────────────────────────────

def test_create_returns_persisted_product(db_session):
    p = _make_product(db_session, name="Milk", price=1.5, barcode="111")
    assert p.id is not None
    assert p.name == "Milk"
    assert p.is_active is True


def test_get_by_id(db_session):
    p = _make_product(db_session)
    assert ProductService.get_by_id(db_session, p.id) is p
    assert ProductService.get_by_id(db_session, 99999) is None


def test_get_by_barcode_only_active(db_session):
    p = _make_product(db_session, barcode="123456")
    assert ProductService.get_by_barcode(db_session, "123456") is p

    ProductService.deactivate(db_session, p.id)
    assert ProductService.get_by_barcode(db_session, "123456") is None


def test_get_all_active_only_default(db_session):
    active = _make_product(db_session, name="Active")
    inactive = _make_product(db_session, name="Inactive")
    ProductService.deactivate(db_session, inactive.id)

    assert ProductService.get_all(db_session) == [active]
    assert {p.id for p in ProductService.get_all(db_session, active_only=False)} == {active.id, inactive.id}


def test_get_all_orders_by_name(db_session):
    _make_product(db_session, name="Zebra")
    _make_product(db_session, name="Apple")
    result = ProductService.get_all(db_session)
    assert [p.name for p in result] == ["Apple", "Zebra"]


def test_search_matches_name_or_barcode_prefix(db_session):
    p1 = _make_product(db_session, name="Cola Can", barcode="500123")
    p2 = _make_product(db_session, name="Other", barcode="Cola-999")
    _make_product(db_session, name="Unrelated", barcode="999999")

    result = ProductService.search(db_session, "Cola")
    assert {p.id for p in result} == {p1.id, p2.id}


def test_search_excludes_inactive(db_session):
    p = _make_product(db_session, name="Hidden")
    ProductService.deactivate(db_session, p.id)
    assert ProductService.search(db_session, "Hidden") == []


def test_search_limits_to_50(db_session):
    for i in range(60):
        _make_product(db_session, name=f"Item{i:03d}", barcode=f"{i:06d}")
    assert len(ProductService.search(db_session, "Item")) == 50


def test_update_modifies_fields(db_session):
    p = _make_product(db_session, name="Old")
    updated = ProductService.update(db_session, p.id, name="New", price=9.99)
    assert updated.name == "New"
    assert updated.price == 9.99


def test_update_nonexistent_returns_none(db_session):
    assert ProductService.update(db_session, 99999, name="X") is None


def test_deactivate_soft_delete(db_session):
    p = _make_product(db_session)
    assert ProductService.deactivate(db_session, p.id) is True
    assert ProductService.get_by_id(db_session, p.id).is_active is False


def test_deactivate_nonexistent_returns_false(db_session):
    assert ProductService.deactivate(db_session, 99999) is False


# ── Stock management ─────────────────────────────────────────────────────

def test_adjust_stock_increases_and_records_movement(db_session):
    p = _make_product(db_session, price=1.0)
    db_session.refresh(p)
    assert p.stock_quantity == 0

    movement = ProductService.adjust_stock(
        db_session, p.id, quantity_change=10, movement_type="purchase", reference="PO-1"
    )

    assert movement is not None
    assert movement.quantity_before == 0
    assert movement.quantity_after == 10
    assert movement.movement_type == "purchase"
    assert movement.reference == "PO-1"

    db_session.refresh(p)
    assert p.stock_quantity == 10


def test_adjust_stock_can_go_negative_for_sales(db_session):
    p = _make_product(db_session, stock_quantity=5)
    ProductService.adjust_stock(db_session, p.id, quantity_change=-8, movement_type="sale")
    db_session.refresh(p)
    assert p.stock_quantity == -3


def test_adjust_stock_nonexistent_product_returns_none(db_session):
    assert ProductService.adjust_stock(db_session, 99999, 1, "purchase") is None


def test_get_low_stock_products(db_session):
    low = _make_product(db_session, name="Low", stock_quantity=1, min_stock_level=5)
    ok = _make_product(db_session, name="OK", stock_quantity=50, min_stock_level=5)

    result = ProductService.get_low_stock_products(db_session)
    assert result == [low]
    assert ok not in result


def test_get_low_stock_excludes_inactive(db_session):
    p = _make_product(db_session, stock_quantity=0, min_stock_level=5)
    ProductService.deactivate(db_session, p.id)
    assert ProductService.get_low_stock_products(db_session) == []


def test_get_stock_movements_ordered_desc_and_limited(db_session):
    from datetime import datetime, timedelta

    p = _make_product(db_session)
    # created_at defaults to datetime.now(), whose resolution can tie across
    # several rapid inserts — pin explicit, strictly increasing timestamps so
    # the ORDER BY created_at DESC being tested isn't at the mercy of that.
    base = datetime(2024, 1, 1)
    for i in range(5):
        movement = ProductService.adjust_stock(db_session, p.id, quantity_change=1, movement_type="purchase", reference=str(i))
        movement.created_at = base + timedelta(seconds=i)
    db_session.commit()

    movements = ProductService.get_stock_movements(db_session, p.id)
    assert len(movements) == 5
    # Most recent first
    assert movements[0].reference == "4"
    assert movements[-1].reference == "0"


def test_get_stock_movements_limit_100(db_session):
    p = _make_product(db_session)
    for i in range(110):
        ProductService.adjust_stock(db_session, p.id, quantity_change=1, movement_type="purchase")
    assert len(ProductService.get_stock_movements(db_session, p.id)) == 100


# ── Categories ───────────────────────────────────────────────────────────

def test_create_category(db_session):
    cat = ProductService.create_category(db_session, "Frozen", description="Cold stuff")
    assert cat.id is not None
    assert cat.name == "Frozen"
    assert cat.description == "Cold stuff"


def test_get_all_categories_ordered_by_name(db_session):
    ProductService.create_category(db_session, "Zebra Cat")
    ProductService.create_category(db_session, "Apple Cat")

    cats = ProductService.get_all_categories(db_session)
    assert [c.name for c in cats] == ["Apple Cat", "Zebra Cat"]
