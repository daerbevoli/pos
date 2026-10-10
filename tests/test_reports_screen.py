"""Tests for app.ui.reports_screen.ReportsScreen."""
import pytest
from PyQt6.QtCore import QDate

from app.ui.reports_screen import ReportsScreen
from app.core.report_service import _payment_breakdown, _amount_for_method, _discounts_and_mistakes
from app.core.product_service import ProductService
from app.core.sales_service import Cart, CartItem, DiscountEntry, SalesService
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


class _SnapshotSale:
    def __init__(self, cart, is_refund=False):
        self.cart_snapshot = cart.to_snapshot()
        self.is_refund = is_refund


def _item(name, qty, price=2.0, **kw):
    return CartItem(product_id=1, product_name=name, product_barcode="", unit_price=price, quantity=qty, **kw)


def test_discounts_split_manual_and_promo():
    sale = _SnapshotSale(Cart(entries=[
        _item("A", 1), DiscountEntry(amount=0.5, label="Promo", is_promo=True),
        DiscountEntry(amount=1.0, label="10%"),
    ]))
    discounts, mistakes = _discounts_and_mistakes([sale, sale])
    assert discounts == {"manual": 2.0, "promo": 1.0}
    assert mistakes == []


def test_mistakes_list_reversal_lines_with_voided_amount():
    original = _item("Cola", 3, price=1.5, has_reversal=True)
    reversal = _item("Cola", -3, price=1.5, is_reversal=True)
    sale = _SnapshotSale(Cart(entries=[original, _item("Bread", 1), reversal]))
    _, mistakes = _discounts_and_mistakes([sale])
    assert mistakes == [{"name": "Cola", "quantity": 3, "unit": "pcs", "amount": 4.5}]


def test_refund_lines_are_not_mistakes():
    sale = _SnapshotSale(Cart(entries=[_item("Cola", -2)], is_refund=True))
    _, mistakes = _discounts_and_mistakes([sale])
    assert mistakes == []


def test_reversal_on_reopened_refund_is_not_a_mistake():
    original = _item("Cola", -2, price=1.5, has_reversal=True)
    reversal = _item("Cola", 2, price=1.5, is_reversal=True)
    sale = _SnapshotSale(Cart(entries=[original, reversal], is_refund=True), is_refund=True)
    _, mistakes = _discounts_and_mistakes([sale])
    assert mistakes == []


def test_discounts_and_mistakes_skip_missing_or_bad_snapshot():
    class _Bad:
        cart_snapshot = "not json"
    class _Empty:
        cart_snapshot = None
    assert _discounts_and_mistakes([_Bad(), _Empty()]) == ({"manual": 0.0, "promo": 0.0}, [])


# ── Screen behavior ──────────────────────────────────────────────────────

def test_initial_state_shows_zero_summary(screen):
    assert screen.cr_label.text() == "0.00"
    assert screen.ctrans_label.text() == "0"
    assert screen.sales_table.rowCount() == 0


def test_load_report_populates_summary_and_table(screen):
    with get_session() as session:
        product = _make_product(session, price=10.0, tax=0)
    _finalize_sale(product, quantity=2, payment_method="cash")
    _finalize_sale(product, quantity=1, payment_method="card")

    screen._load_report()

    assert screen.cr_label.text() == "30.00"
    assert screen.ctrans_label.text() == "2"
    assert screen.cc_label.text() == "20.00"
    assert screen.crcr_label.text() == "10.00"
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
        client = ClientService.create(session, name="Acme Corp", vatNumber="BE001", street="1 Main St", zip_code="1000", city="Brussels")
        client_id = client.id
    _finalize_sale(product, client_id=client_id)

    screen._load_report()
    assert screen.sales_table.item(0, 2).text() == "Acme Corp"
    assert screen.sales_table.item(0, 3).text() == "BE001"


def test_load_report_shows_invoiced_client_name_as_issued_even_after_rename(screen):
    """The report must reflect the invoice's own snapshot, not the client's
    current (possibly since-changed) name/VAT — same guarantee as the model."""
    with get_session() as session:
        product = _make_product(session)
    with get_session() as session:
        client = ClientService.create(session, name="Original Name", vatNumber="V-ORIG", street="1 Main St", zip_code="1000", city="Brussels")
        client_id = client.id
    _finalize_sale(product, client_id=client_id)

    with get_session() as session:
        ClientService.update(session, client_id, name="Renamed Later", vatNumber="V-CHANGED")

    screen._load_report()

    assert screen.sales_table.item(0, 2).text() == "Original Name"
    assert screen.sales_table.item(0, 3).text() == "V-ORIG"


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

    # vat_table columns: Rate | Base (excl. tax) | Tax | Total (incl. tax)
    rows = {
        screen.vat_table.item(r, 0).text(): [screen.vat_table.item(r, c).text() for c in (1, 2, 3)]
        for r in range(screen.vat_table.rowCount())
    }
    assert rows["21 %"] == ["10.00", "2.10", "12.10"]
    assert rows["6 %"] == ["10.00", "0.60", "10.60"]


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
    assert screen.categories_table.item(0, 2).text() == "15.00"


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
        client = ClientService.create(session, name="Client", vatNumber="V1", street="1 Main St", zip_code="1000", city="Brussels")
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


def test_confirm_without_a_selected_row_does_not_show_any_sale(screen, qtbot):
    """Pressing OK with nothing clicked in the sales table must navigate
    back to the POS without telling it to show any sale."""
    with get_session() as session:
        product = _make_product(session)
    _finalize_sale(product)
    screen._load_report()
    assert screen.sales_table.currentRow() == -1  # nothing selected after a fresh load

    received = []
    screen.sale_selected.connect(received.append)

    with qtbot.waitSignal(screen.navigate, timeout=1000):
        screen._confirm()

    assert received == []


def test_confirm_with_a_selected_row_shows_that_sale(screen, qtbot):
    """Pressing OK after clicking a row shows exactly that row's sale."""
    with get_session() as session:
        product = _make_product(session, price=10.0)
    older = _finalize_sale(product, quantity=1)
    newer = _finalize_sale(product, quantity=1)
    screen._load_report()

    row_for_newer = next(r for r, sid in screen._sales_row_ids.items() if sid == newer.id)
    screen.sales_table.setCurrentCell(row_for_newer, 0)

    with qtbot.waitSignal(screen.sale_selected, timeout=1000) as blocker:
        screen._confirm()

    assert blocker.args == [newer.id]


def test_display_sale_clears_current_row_after_emitting(screen, qtbot):
    """Once a selected sale has been shown, the selection is consumed —
    pressing OK again without clicking a new row must not re-show it."""
    with get_session() as session:
        product = _make_product(session)
    _finalize_sale(product)
    screen._load_report()

    row = next(iter(screen._sales_row_ids))
    screen.sales_table.setCurrentCell(row, 0)

    with qtbot.waitSignal(screen.sale_selected, timeout=1000):
        screen._display_sale()

    assert screen.sales_table.currentRow() == -1

    received = []
    screen.sale_selected.connect(received.append)
    screen._confirm()
    assert received == []


def test_display_sale_emits_the_row_actual_sale_id(screen, qtbot):
    """sale_selected must carry the double-clicked row's own Sale.id, not
    the row's table position — regression test for a bug where the POS
    side reinterpreted a row index as a position in a different, oldest-
    first, today-only list."""
    with get_session() as session:
        product = _make_product(session, price=10.0)
    older = _finalize_sale(product, quantity=1)
    newer = _finalize_sale(product, quantity=1)

    screen._load_report()
    assert screen.sales_table.rowCount() == 2

    for row, expected_id in screen._sales_row_ids.items():
        screen.sales_table.setCurrentCell(row, 0)
        with qtbot.waitSignal(screen.sale_selected, timeout=1000) as blocker:
            screen._display_sale()
        assert blocker.args == [expected_id]

    assert {older.id, newer.id} == set(screen._sales_row_ids.values())


# ── Z report blocked by unsent invoices ──────────────────────────────────

def _make_invoice():
    # Separate sessions: create() commits, which would expire the product.
    with get_session() as session:
        product = _make_product(session)
    with get_session() as session:
        client = ClientService.create(session, name="Acme", vatNumber="BE0123456749",
                                      street="1 Main St", zip_code="1000", city="Brussels")
        client_id = client.id
    return _finalize_sale(product, client_id=client_id)


def test_close_z_report_refuses_while_an_invoice_is_unsent(patched_db):
    from app.core.report_service import XZReportService
    from app.models.models import Sale, ZReport
    invoice = _make_invoice()

    with get_session() as session:
        with pytest.raises(ValueError, match=invoice.invoice_number):
            XZReportService.close_z_report(session)
    with get_session() as session:
        # Nothing was closed or purged.
        assert session.query(ZReport).count() == 0
        assert session.query(Sale).count() == 1


def test_close_z_report_allowed_once_invoice_is_sent(patched_db):
    from app.core.report_service import XZReportService
    invoice = _make_invoice()
    with get_session() as session:
        SalesService.mark_invoice_sent(session, invoice.sale_id)

    with get_session() as session:
        assert XZReportService.unsent_invoice_numbers(session) == []
        assert XZReportService.close_z_report(session).report_number == "Z-0001"


def test_invoice_orphaned_by_an_earlier_z_report_does_not_block(patched_db):
    """An unsent invoice whose sale is already gone can't be sent from the
    POS anymore — it mustn't block every future Z report forever."""
    from app.core.report_service import XZReportService
    from app.models.models import Invoice
    invoice = _make_invoice()
    with get_session() as session:
        session.get(Invoice, invoice.id).sale_id = None
        session.commit()

    with get_session() as session:
        assert XZReportService.unsent_invoice_numbers(session) == []



def test_close_z_report_stores_discounts_and_mistakes(patched_db):
    """The Z report purges its sales, so discounts/mistakes must be kept on
    the ZReport row itself to be printable."""
    import json
    from app.core.report_service import XZReportService
    with get_session() as session:
        product = _make_product(session, price=2.0)
    with get_session() as session:
        def line(qty, **kw):
            return CartItem(product_id=product.id, product_name="Cola", product_barcode="",
                            unit_price=2.0, quantity=qty, tax_rate=21, **kw)
        cart = Cart(entries=[
            line(2, has_reversal=True), line(1),
            DiscountEntry(amount=0.5, label="10%"), line(-2, is_reversal=True),
        ])
        SalesService.finalize_sale(session, cart, payment_method="cash")

    with get_session() as session:
        z = XZReportService.close_z_report(session)
        assert json.loads(z.discounts) == {"manual": 0.5, "promo": 0.0}
        assert json.loads(z.mistakes) == [{"name": "Cola", "quantity": 2, "unit": "pcs", "amount": 4.0}]

def test_z_report_button_warns_and_skips_confirmation_when_unsent(screen, monkeypatch):
    from app.models.models import ZReport
    from PyQt6.QtWidgets import QMessageBox
    invoice = _make_invoice()
    warnings, questions = [], []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **kw: warnings.append(a)))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **kw: questions.append(a)))

    screen._print_z_report()

    assert len(warnings) == 1 and invoice.invoice_number in warnings[0][2]
    assert questions == []
    with get_session() as session:
        assert session.query(ZReport).count() == 0




def test_x_report_number_matches_the_z_report_that_closes_its_period(patched_db):
    """X reports share their period's number however often they're printed;
    the closing Z report takes that number, and the next period moves on."""
    from app.core.report_service import XZReportService
    with get_session() as session:
        assert XZReportService.generate_x_report(session)["report_number"] == "X-0001"
        assert XZReportService.generate_x_report(session)["report_number"] == "X-0001"
        assert XZReportService.close_z_report(session).report_number == "Z-0001"
    with get_session() as session:
        assert XZReportService.generate_x_report(session)["report_number"] == "X-0002"


# ── Mark invoice sent manually ───────────────────────────────────────────

def _select_sale_row(screen, sale_id):
    screen._load_report()
    row = next(r for r, sid in screen._sales_row_ids.items() if sid == sale_id)
    screen.sales_table.setCurrentCell(row, 0)


def test_mark_sent_confirmed_locks_the_invoice(screen, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    from app.models.models import Invoice
    invoice = _make_invoice()
    _select_sale_row(screen, invoice.sale_id)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)

    screen._mark_invoice_sent()

    with get_session() as session:
        assert session.get(Invoice, invoice.id).sent_at is not None


def test_mark_sent_cancelled_leaves_the_invoice_unsent(screen, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    from app.models.models import Invoice
    invoice = _make_invoice()
    _select_sale_row(screen, invoice.sale_id)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)

    screen._mark_invoice_sent()

    with get_session() as session:
        assert session.get(Invoice, invoice.id).sent_at is None


def test_mark_sent_on_a_plain_sale_does_not_ask(screen, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    with get_session() as session:
        product = _make_product(session)
    sale = _finalize_sale(product)
    _select_sale_row(screen, sale.id)
    overlays, questions = [], []
    monkeypatch.setattr(screen, "_show_overlay", lambda message, **k: overlays.append(message))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: questions.append(a))

    screen._mark_invoice_sent()

    assert overlays == ["Sale is not an invoice."] and questions == []


# ── Invoices view reads the invoices table ───────────────────────────────

def test_invoices_view_still_lists_invoices_after_z_report(screen):
    """A Z report purges sales but keeps invoices (sale_id -> NULL); the
    Invoices view must still show them from their own snapshot."""
    from app.core.report_service import XZReportService
    invoice = _make_invoice()
    with get_session() as session:
        SalesService.mark_invoice_sent(session, invoice.sale_id)
    with get_session() as session:
        XZReportService.close_z_report(session)

    screen._invoices_only()

    assert screen.sales_table.rowCount() == 1
    assert screen.sales_table.item(0, 0).text() == invoice.invoice_number
    assert screen.sales_table.item(0, 2).text() == "Acme"
    assert screen.sales_table.item(0, 4).text() == "1"
    assert screen.sales_table.item(0, 5).text() == "CASH"  # from the invoice's own payment snapshot
    assert screen.ctrans_label.text() == "1"
    assert screen._sales_row_ids == {}


def test_purged_invoice_cannot_be_opened_on_pos(screen, qtbot, monkeypatch):
    from app.core.report_service import XZReportService
    invoice = _make_invoice()
    with get_session() as session:
        SalesService.mark_invoice_sent(session, invoice.sale_id)
    with get_session() as session:
        XZReportService.close_z_report(session)
    screen._invoices_only()
    screen.sales_table.setCurrentCell(0, 0)
    overlays, selected, navigated = [], [], []
    monkeypatch.setattr(screen, "_show_overlay", lambda message, **k: overlays.append(message))
    screen.sale_selected.connect(selected.append)
    screen.navigate.connect(navigated.append)

    screen._confirm()

    assert overlays == ["Z report cleared. View invoice in ERP."] and selected == [] and navigated == []


def test_mark_sent_works_on_invoice_without_sale(screen, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    from app.models.models import Invoice
    invoice = _make_invoice()
    with get_session() as session:
        session.get(Invoice, invoice.id).sale_id = None
        session.commit()
    screen._invoices_only()
    screen.sales_table.setCurrentCell(0, 0)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)

    screen._mark_invoice_sent()

    with get_session() as session:
        assert session.get(Invoice, invoice.id).sent_at is not None


def test_invoices_filter_survives_range_buttons_and_load(screen):
    with get_session() as session:
        product = _make_product(session)
    _finalize_sale(product)
    _make_invoice()

    screen._invoices_only()
    assert screen.invoices_btn.isChecked()
    assert screen.sales_table.rowCount() == 1

    screen._set_range(7)
    assert screen.sales_table.rowCount() == 1
    screen._load_report()
    assert screen.sales_table.rowCount() == 1

    screen._invoices_only()
    assert not screen.invoices_btn.isChecked()
    assert screen.sales_table.rowCount() == 2


def test_invoice_vat_breakdown_survives_z_report(screen):
    from app.core.report_service import XZReportService
    invoice = _make_invoice()  # one 10.00 line at 21%
    with get_session() as session:
        SalesService.mark_invoice_sent(session, invoice.sale_id)
    with get_session() as session:
        XZReportService.close_z_report(session)

    screen._invoices_only()

    rows = {screen.vat_table.item(r, 0).text(): (screen.vat_table.item(r, 1).text(),
            screen.vat_table.item(r, 2).text(), screen.vat_table.item(r, 3).text())
            for r in range(screen.vat_table.rowCount())}
    assert rows["21 %"] == ("8.26", "1.74", "10.00")
    assert rows["6 %"] == ("0.00", "0.00", "0.00")


def test_invoice_vat_breakdown_matches_sale_based_breakdown(patched_db):
    from app.core.report_service import XZReportService, invoice_vat_breakdown
    from app.models.models import Invoice
    invoice = _make_invoice()
    with get_session() as session:
        inv = session.get(Invoice, invoice.id)
        assert invoice_vat_breakdown([inv]) == XZReportService.compute_totals(session, [inv.sale])["vat_breakdown"]


def test_invoice_categories_survive_z_report(screen):
    from app.core.report_service import XZReportService
    from app.models.models import Category
    with get_session() as session:
        category = Category(name="Drinks")
        session.add(category)
        session.commit()
        category_id = category.id
    with get_session() as session:
        product = _make_product(session, name="Cola", category_id=category_id)
    with get_session() as session:
        client = ClientService.create(session, name="Acme", vatNumber="BE0123456749",
                                      street="1 Main St", zip_code="1000", city="Brussels")
        client_id = client.id
    invoice = _finalize_sale(product, quantity=3, client_id=client_id)
    with get_session() as session:
        SalesService.mark_invoice_sent(session, invoice.sale_id)
    with get_session() as session:
        XZReportService.close_z_report(session)

    screen._invoices_only()

    rows = {screen.categories_table.item(r, 0).text(): (screen.categories_table.item(r, 1).text(),
            screen.categories_table.item(r, 2).text())
            for r in range(screen.categories_table.rowCount())}
    assert rows == {"Drinks": ("3", "30.00")}


def test_invoice_category_breakdown_matches_sale_based_breakdown(patched_db):
    from app.core.report_service import XZReportService, invoice_category_breakdown
    from app.models.models import Invoice
    invoice = _make_invoice()
    with get_session() as session:
        inv = session.get(Invoice, invoice.id)
        assert invoice_category_breakdown(session, [inv]) == \
            XZReportService.compute_totals(session, [inv.sale])["category_breakdown"]


def test_invoice_payments_survive_z_report(screen):
    """Cash/card cards in the Invoices view come from each invoice's own
    payment snapshot, so they still add up to revenue after a Z report."""
    from app.core.report_service import XZReportService
    invoice = _make_invoice()  # 10.00, paid cash
    with get_session() as session:
        SalesService.mark_invoice_sent(session, invoice.sale_id)
    with get_session() as session:
        XZReportService.close_z_report(session)

    screen._invoices_only()

    assert screen.cc_label.text() == "10.00"
    assert screen.crcr_label.text() == "0.00"


def test_invoice_payment_breakdown_falls_back_to_sale_for_legacy_invoices(patched_db):
    """Invoices issued before payments were snapshotted onto them read the
    payment off their sale while it exists, and are left out once it's purged."""
    from app.core.report_service import invoice_payment_breakdown
    from app.models.models import Invoice
    invoice = _make_invoice()
    with get_session() as session:
        inv = session.get(Invoice, invoice.id)
        inv.payment_method = None
        inv.payment_breakdown = None
        session.commit()
        assert invoice_payment_breakdown([inv]) == [{"method": "cash", "amount": 10.0}]

        inv.sale_id = None
        session.commit()
        session.refresh(inv)
        assert invoice_payment_breakdown([inv]) == []
