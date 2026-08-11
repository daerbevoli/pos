"""Tests for app.ui.reports_screen.ReportsScreen."""
import pytest
from PyQt6.QtCore import QDate

from app.ui.reports_screen import ReportsScreen, _payment_breakdown, _amount_for_method
from app.core.product_service import ProductService
from app.core.sales_service import Cart, CartItem, SalesService
from app.core.client_service import ClientService
from app.core.database import get_session


@pytest.fixture
def screen(qtbot, patched_db):
    s = ReportsScreen()
    qtbot.addWidget(s)
    return s


def _make_product(session, **overrides):
    data = {"name": "Product", "price": 10.0, "tax": 21, "stock_quantity": 100}
    data.update(overrides)
    return ProductService.create(session, **data)


def _finalize_sale(product, quantity=1, payment_method="cash", payment_breakdown=None, client_id=None):
    with get_session() as session:
        cart = Cart(entries=[CartItem(
            product_id=product.id, product_name=product.name, product_barcode=product.barcode or "",
            unit_price=product.price, quantity=quantity, tax_rate=product.tax,
        )])
        if client_id:
            return SalesService.finalize_invoice(
                session, cart, payment_method=payment_method, client_id=client_id,
                payment_breakdown=payment_breakdown,
            )
        return SalesService.finalize_sale(
            session, cart, payment_method=payment_method, payment_breakdown=payment_breakdown,
        )


# ── Helper functions ─────────────────────────────────────────────────────

class _FakeSale:
    def __init__(self, payment_breakdown=None, payment_method="cash", final_amount=0.0):
        self.payment_breakdown = payment_breakdown
        self.payment_method = payment_method
        self.final_amount = final_amount


def test_payment_breakdown_parses_json():
    import json
    sale = _FakeSale(payment_breakdown=json.dumps([{"method": "cash", "amount": 5.0}]))
    assert _payment_breakdown(sale) == [{"method": "cash", "amount": 5.0}]


def test_payment_breakdown_falls_back_for_legacy_sales():
    sale = _FakeSale(payment_breakdown=None, payment_method="card", final_amount=15.0)
    assert _payment_breakdown(sale) == [{"method": "card", "amount": 15.0}]


def test_payment_breakdown_falls_back_on_bad_json():
    sale = _FakeSale(payment_breakdown="not json", payment_method="cash", final_amount=10.0)
    assert _payment_breakdown(sale) == [{"method": "cash", "amount": 10.0}]


def test_amount_for_method_sums_matching_legs():
    import json
    sale = _FakeSale(payment_breakdown=json.dumps([
        {"method": "cash", "amount": 5.0}, {"method": "card", "amount": 3.0}, {"method": "cash", "amount": 2.0},
    ]))
    assert _amount_for_method(sale, "cash") == 7.0
    assert _amount_for_method(sale, "card") == 3.0


# ── Screen behavior ──────────────────────────────────────────────────────

def test_initial_state_shows_zero_summary(screen):
    assert screen.card_revenue._value_label.text() == "€0.00"
    assert screen.card_transactions._value_label.text() == "0"
    assert screen.sales_table.rowCount() == 0


def test_load_report_populates_summary_and_table(screen):
    with get_session() as session:
        product = _make_product(session, price=10.0, tax=0)
    _finalize_sale(product, quantity=2, payment_method="cash")
    _finalize_sale(product, quantity=1, payment_method="card")

    screen._load_report()

    assert screen.card_revenue._value_label.text() == "€30.00"
    assert screen.card_transactions._value_label.text() == "2"
    assert screen.card_cash._value_label.text() == "€20.00"
    assert screen.card_card._value_label.text() == "€10.00"
    assert screen.sales_table.rowCount() == 2


def test_load_report_shows_slash_for_non_invoice_client(screen):
    with get_session() as session:
        product = _make_product(session)
    _finalize_sale(product)
    screen._load_report()
    assert screen.sales_table.item(0, 2).text() == "/"


def test_load_report_shows_client_name_for_invoices(screen):
    with get_session() as session:
        product = _make_product(session)
    with get_session() as session:
        client = ClientService.create(session, name="Acme Corp", vatNumber="BE001")
        client_id = client.id
    _finalize_sale(product, client_id=client_id)

    screen._load_report()
    assert screen.sales_table.item(0, 2).text() == "Acme Corp"
    assert screen.sales_table.item(0, 3).text() == "BE001"


def test_vat_breakdown_by_rate(screen):
    # Each product is created in its own session block: ProductService.create()
    # commits (expire_on_commit=True), which would expire an earlier object
    # still attached to the same session — refetch pattern used everywhere else.
    with get_session() as session:
        p21 = _make_product(session, name="P21", price=12.1, tax=21)  # 10 base, 2.1 tax
    with get_session() as session:
        p6 = _make_product(session, name="P6", price=10.6, tax=6)     # 10 base, 0.6 tax
    _finalize_sale(p21, quantity=1)
    _finalize_sale(p6, quantity=1)

    screen._load_report()

    base_21, tax_21, total_21 = screen._vat_labels[21]
    assert total_21.text() == "€12.10"
    assert tax_21.text() == "€2.10"

    base_6, tax_6, total_6 = screen._vat_labels[6]
    assert total_6.text() == "€10.60"


def test_category_breakdown(screen):
    # "Custom Drinks" (not one of the seeded default category names) to
    # avoid colliding with the categories the patched_db fixture seeds.
    with get_session() as session:
        cat = ProductService.create_category(session, "Custom Drinks")
        product = _make_product(session, category_id=cat.id, price=5.0, tax=0)
    _finalize_sale(product, quantity=3)

    screen._load_report()

    assert screen.categories_table.rowCount() == 1
    assert screen.categories_table.item(0, 0).text() == "Custom Drinks"
    assert screen.categories_table.item(0, 1).text() == "3"
    assert screen.categories_table.item(0, 2).text() == "€15.00"


def test_category_breakdown_uncategorized(screen):
    with get_session() as session:
        product = _make_product(session, category_id=None)
    _finalize_sale(product)
    screen._load_report()
    assert screen.categories_table.item(0, 0).text() == "Uncategorized"


def test_invoices_only_filters_out_regular_sales(screen):
    with get_session() as session:
        product = _make_product(session)
    with get_session() as session:
        client = ClientService.create(session, name="Client", vatNumber="V1")
        client_id = client.id
    _finalize_sale(product)  # regular sale
    _finalize_sale(product, client_id=client_id)  # invoice

    screen._invoices_only()

    assert screen.invoices_only is True
    assert screen.sales_table.rowCount() == 1


def test_invoices_only_toggle_back(screen):
    with get_session() as session:
        product = _make_product(session)
    _finalize_sale(product)

    screen._invoices_only()
    assert screen.sales_table.rowCount() == 0
    screen._invoices_only()
    assert screen.invoices_only is False
    assert screen.sales_table.rowCount() == 1


def test_set_range_updates_dates(screen):
    screen._set_range(7)
    assert screen.date_from.date() == QDate.currentDate().addDays(-7)
    assert screen.date_to.date() == QDate.currentDate()


def test_confirm_emits_navigate_signal(screen, qtbot):
    with qtbot.waitSignal(screen.navigate, timeout=1000) as blocker:
        screen._confirm()
    assert blocker.args == [0]


def test_mixed_payment_method_displayed_as_cash_plus_card(screen):
    with get_session() as session:
        product = _make_product(session)
    _finalize_sale(product, payment_method="mixed",
                    payment_breakdown=[{"method": "cash", "amount": 5.0}, {"method": "card", "amount": 5.0}])

    screen._load_report()
    assert screen.sales_table.item(0, 5).text() == "CASH+CARD"
