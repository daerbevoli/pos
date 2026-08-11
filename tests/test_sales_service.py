"""Tests for app.core.sales_service.SalesService business logic."""
import json
from datetime import date, timedelta

import pytest

from app.core.product_service import ProductService
from app.core.sales_service import Cart, CartItem, SalesService
from app.models.models import Sale, SaleItem, Invoice


def _make_product(session, **overrides):
    data = {"name": "Product", "price": 10.0, "stock_quantity": 100, "tax": 21}
    data.update(overrides)
    return ProductService.create(session, **data)


def _cart_with(*items):
    return Cart(entries=list(items))


def _item_for(product, quantity=1, discount=0.0):
    return CartItem(
        product_id=product.id,
        product_name=product.name,
        product_barcode=product.barcode or "",
        unit_price=product.price,
        quantity=quantity,
        tax_rate=product.tax,
        discount=discount,
    )


# ── finalize_sale ────────────────────────────────────────────────────────

def test_finalize_sale_empty_cart_raises(db_session):
    with pytest.raises(ValueError):
        SalesService.finalize_sale(db_session, Cart())


def test_finalize_sale_creates_sale_and_items(db_session):
    product = _make_product(db_session, price=10.0, tax=21, stock_quantity=50)
    cart = _cart_with(_item_for(product, quantity=2))

    sale = SalesService.finalize_sale(db_session, cart, payment_method="cash", amount_tendered=25.0)

    assert sale.id is not None
    assert sale.status == "completed"
    assert sale.total_amount == 20.0
    assert sale.final_amount == 20.0
    assert sale.change_given == 5.0
    assert len(sale.items) == 1
    assert sale.items[0].product_id == product.id
    assert sale.items[0].quantity == 2


def test_finalize_sale_deducts_stock(db_session):
    product = _make_product(db_session, stock_quantity=50)
    cart = _cart_with(_item_for(product, quantity=3))

    SalesService.finalize_sale(db_session, cart)

    db_session.refresh(product)
    assert product.stock_quantity == 47


def test_finalize_sale_sale_number_format_and_sequence(db_session):
    product = _make_product(db_session)
    today_str = date.today().strftime("%Y%m%d")

    sale1 = SalesService.finalize_sale(db_session, _cart_with(_item_for(product, quantity=1)))
    sale2 = SalesService.finalize_sale(db_session, _cart_with(_item_for(product, quantity=1)))

    assert sale1.sale_number == f"S-{today_str}-0001"
    assert sale2.sale_number == f"S-{today_str}-0002"


def test_finalize_sale_computes_total_tax(db_session):
    product = _make_product(db_session, price=12.1, tax=21)  # 12.1 incl 21% -> 2.1 tax, 10 base
    cart = _cart_with(_item_for(product, quantity=1))

    sale = SalesService.finalize_sale(db_session, cart)

    assert sale.tax_amount == pytest.approx(2.1, abs=0.01)


def test_finalize_sale_stores_snapshot_and_payment_breakdown(db_session):
    product = _make_product(db_session)
    cart = _cart_with(_item_for(product, quantity=1))
    breakdown = [{"method": "cash", "amount": 10.0}]

    sale = SalesService.finalize_sale(db_session, cart, payment_breakdown=breakdown)

    assert json.loads(sale.cart_snapshot)[0]["product_id"] == product.id
    assert json.loads(sale.payment_breakdown) == breakdown


def test_finalize_sale_change_only_for_cash_or_card_with_amount(db_session):
    product = _make_product(db_session)
    cart = _cart_with(_item_for(product, quantity=1))

    sale = SalesService.finalize_sale(db_session, cart, payment_method="cash", amount_tendered=None)
    assert sale.change_given is None


def test_finalize_sale_defaults_do_not_crash_regression(db_session):
    """Regression: finalize_sale(session, cart) with every other argument at
    its default (payment_method='cash', amount_tendered=None) used to raise
    TypeError from `amount_tendered - cart.total` due to an operator
    precedence bug (`method == "cash" or method == "card" and tendered is
    not None` binds as `cash or (card and tendered)`, so plain "cash" always
    tried the subtraction). Must not crash, and change must stay unset."""
    product = _make_product(db_session)
    sale = SalesService.finalize_sale(db_session, _cart_with(_item_for(product, quantity=1)))
    assert sale.change_given is None


# ── update_sale ──────────────────────────────────────────────────────────

def test_update_sale_replaces_items_and_reconciles_stock(db_session):
    product = _make_product(db_session, stock_quantity=100)
    other = _make_product(db_session, name="Other", stock_quantity=100)

    sale = SalesService.finalize_sale(db_session, _cart_with(_item_for(product, quantity=5)))
    db_session.refresh(product)
    assert product.stock_quantity == 95

    new_cart = _cart_with(_item_for(other, quantity=2))
    updated = SalesService.update_sale(db_session, sale.id, new_cart)

    db_session.refresh(product)
    db_session.refresh(other)
    assert product.stock_quantity == 100  # restored
    assert other.stock_quantity == 98  # newly deducted

    assert updated.id == sale.id
    assert len(updated.items) == 1
    assert updated.items[0].product_id == other.id


def test_update_sale_preserves_identity_fields(db_session):
    product = _make_product(db_session)
    sale = SalesService.finalize_sale(db_session, _cart_with(_item_for(product, quantity=1)))
    original_number = sale.sale_number
    original_created_at = sale.created_at

    updated = SalesService.update_sale(db_session, sale.id, _cart_with(_item_for(product, quantity=2)))

    assert updated.id == sale.id
    assert updated.sale_number == original_number
    assert updated.created_at == original_created_at


def test_update_sale_empty_cart_raises(db_session):
    product = _make_product(db_session)
    sale = SalesService.finalize_sale(db_session, _cart_with(_item_for(product, quantity=1)))
    with pytest.raises(ValueError):
        SalesService.update_sale(db_session, sale.id, Cart())


def test_update_sale_missing_sale_raises(db_session):
    product = _make_product(db_session)
    with pytest.raises(ValueError):
        SalesService.update_sale(db_session, 99999, _cart_with(_item_for(product, quantity=1)))


# ── void_sale ────────────────────────────────────────────────────────────

def test_void_sale_restores_stock_and_marks_voided(db_session):
    product = _make_product(db_session, stock_quantity=50)
    sale = SalesService.finalize_sale(db_session, _cart_with(_item_for(product, quantity=5)))
    db_session.refresh(product)
    assert product.stock_quantity == 45

    result = SalesService.void_sale(db_session, sale.id, notes="customer changed mind")

    assert result is True
    db_session.refresh(product)
    assert product.stock_quantity == 50
    db_session.refresh(sale)
    assert sale.status == "voided"
    assert "customer changed mind" in sale.notes


def test_void_sale_nonexistent_returns_false(db_session):
    assert SalesService.void_sale(db_session, 99999) is False


def test_void_sale_cannot_void_twice(db_session):
    product = _make_product(db_session)
    sale = SalesService.finalize_sale(db_session, _cart_with(_item_for(product, quantity=1)))
    assert SalesService.void_sale(db_session, sale.id) is True
    assert SalesService.void_sale(db_session, sale.id) is False


# ── finalize_invoice ─────────────────────────────────────────────────────

def test_finalize_invoice_creates_sale_and_invoice(db_session):
    from app.core.client_service import ClientService
    client = ClientService.create(db_session, name="Client", vatNumber="V1")
    product = _make_product(db_session, stock_quantity=10)

    invoice = SalesService.finalize_invoice(
        db_session, _cart_with(_item_for(product, quantity=2)), client_id=client.id
    )

    assert invoice.id is not None
    assert invoice.client_id == client.id
    assert invoice.invoice_number.startswith("I-")
    assert invoice.sale.status == "completed"
    assert len(invoice.sale.items) == 1

    db_session.refresh(product)
    assert product.stock_quantity == 8


def test_finalize_invoice_empty_cart_raises(db_session):
    with pytest.raises(ValueError):
        SalesService.finalize_invoice(db_session, Cart())


def test_finalize_invoice_number_mirrors_sale_number(db_session):
    product = _make_product(db_session)
    invoice = SalesService.finalize_invoice(db_session, _cart_with(_item_for(product, quantity=1)))
    assert invoice.invoice_number == invoice.sale.sale_number.replace("S-", "I-", 1)


def test_finalize_invoice_snapshots_client_and_amounts(db_session):
    from app.core.client_service import ClientService
    client = ClientService.create(db_session, name="Acme Corp", vatNumber="BE001", address="1 Main St")
    product = _make_product(db_session, price=12.1, tax=21)  # 10 base, 2.1 tax

    invoice = SalesService.finalize_invoice(
        db_session, _cart_with(_item_for(product, quantity=1)), client_id=client.id
    )

    assert invoice.client_name == "Acme Corp"
    assert invoice.client_vat_number == "BE001"
    assert invoice.client_address == "1 Main St"
    assert invoice.total_amount == invoice.sale.total_amount
    assert invoice.tax_amount == pytest.approx(2.1, abs=0.01)
    assert invoice.final_amount == 12.1
    assert invoice.issued_at is not None

    snapshot = json.loads(invoice.line_items_snapshot)
    assert snapshot[0]["product_id"] == product.id
    assert snapshot[0]["quantity"] == 1


def test_finalize_invoice_without_client_leaves_snapshot_fields_none(db_session):
    product = _make_product(db_session)
    invoice = SalesService.finalize_invoice(db_session, _cart_with(_item_for(product, quantity=1)))

    assert invoice.client_id is None
    assert invoice.client_name is None
    assert invoice.client_vat_number is None
    assert invoice.client_address is None
    # Amount/line-item snapshot is independent of whether there's a client.
    assert invoice.final_amount == invoice.sale.final_amount


def test_finalize_invoice_snapshot_survives_later_client_edits(db_session):
    from app.core.client_service import ClientService
    client = ClientService.create(db_session, name="Original Name", vatNumber="V-ORIG")
    product = _make_product(db_session)

    invoice = SalesService.finalize_invoice(
        db_session, _cart_with(_item_for(product, quantity=1)), client_id=client.id
    )

    ClientService.update(db_session, client.id, name="Renamed Later", vatNumber="V-CHANGED")
    db_session.refresh(invoice)

    assert invoice.client_name == "Original Name"
    assert invoice.client_vat_number == "V-ORIG"


# ── Reports / queries ────────────────────────────────────────────────────

def test_get_sales_for_date_filters_by_date_and_status(db_session):
    product = _make_product(db_session)
    sale = SalesService.finalize_sale(db_session, _cart_with(_item_for(product, quantity=1)))
    voided = SalesService.finalize_sale(db_session, _cart_with(_item_for(product, quantity=1)))
    SalesService.void_sale(db_session, voided.id)

    result = SalesService.get_sales_for_date(db_session, date.today())

    assert [s.id for s in result] == [sale.id]


def test_get_sales_for_date_empty_for_other_dates(db_session):
    product = _make_product(db_session)
    SalesService.finalize_sale(db_session, _cart_with(_item_for(product, quantity=1)))

    result = SalesService.get_sales_for_date(db_session, date.today() - timedelta(days=1))
    assert result == []


def test_get_daily_summary_aggregates_correctly(db_session):
    product = _make_product(db_session, price=10.0, tax=0)

    SalesService.finalize_sale(db_session, _cart_with(_item_for(product, quantity=1)), payment_method="cash")
    SalesService.finalize_sale(db_session, _cart_with(_item_for(product, quantity=2)), payment_method="card")

    summary = SalesService.get_daily_summary(db_session, date.today())

    assert summary["total_transactions"] == 2
    assert summary["total_revenue"] == 30.0
    assert summary["average_transaction"] == 15.0
    assert summary["cash_sales"] == 10.0
    assert summary["card_sales"] == 20.0


def test_get_daily_summary_no_sales_avoids_division_by_zero(db_session):
    summary = SalesService.get_daily_summary(db_session, date.today())
    assert summary["total_transactions"] == 0
    assert summary["average_transaction"] == 0


def test_get_sales_range_includes_boundaries_and_excludes_outside(db_session):
    product = _make_product(db_session)
    sale = SalesService.finalize_sale(db_session, _cart_with(_item_for(product, quantity=1)))

    today = date.today()
    result = SalesService.get_sales_range(db_session, today, today)
    assert [s.id for s in result] == [sale.id]

    result_future = SalesService.get_sales_range(db_session, today + timedelta(days=1), today + timedelta(days=2))
    assert result_future == []


def test_get_sales_range_excludes_voided(db_session):
    product = _make_product(db_session)
    sale = SalesService.finalize_sale(db_session, _cart_with(_item_for(product, quantity=1)))
    SalesService.void_sale(db_session, sale.id)

    today = date.today()
    result = SalesService.get_sales_range(db_session, today, today)
    assert result == []
