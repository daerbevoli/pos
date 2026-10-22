"""
Tests for app.ui.customer_display.CustomerDisplay: the customer-facing copy
of the active POS ticket panel, fed by POSScreen.display_changed.

Covers row mirroring, light/dark (frozen) styling, the running-total vs.
paid footer, header/client mirroring across V-tabs, the clock tick, and
showing/hiding it (Settings button, second monitor).
"""
import pytest
from PyQt6.QtCore import QRect
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QAbstractItemView, QMessageBox

from app.ui.customer_display import CustomerDisplay
from app.ui.main_window import MainWindow
from app.core.client_service import ClientService
from app.core.product_service import ProductService
from app.core.database import get_session


@pytest.fixture(autouse=True)
def _auto_confirm_message_boxes(monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **kw: QMessageBox.StandardButton.Yes))


@pytest.fixture
def window(qtbot, patched_db):
    w = MainWindow()
    qtbot.addWidget(w)
    return w


@pytest.fixture
def pos(window):
    return window.pos_screen


@pytest.fixture
def display(window):
    return window.customer_display


def _add_item(pos, price=2.5, barcode="1234567890123", quantity=None):
    with get_session() as session:
        p = ProductService.create(session, name="Apple", price=price, tax=0,
                                  stock_quantity=100, unit="pcs", barcode=barcode)
        pid = p.id
    if quantity is not None:
        pos.cart_input.setText(str(quantity))
    pos.add_product_by_id(pid)


def _make_client(name="ACME"):
    with get_session() as session:
        return ClientService.create(
            session, name=name, vatNumber="V1", street="1 Main St", zip_code="1000", city="Brussels",
        ).id


def _texts(table, row):
    return [table.item(row, c).text() for c in range(table.columnCount())]


def _is_frozen(display):
    return bool(display.cart_table.property("frozen"))


# ── Row mirroring ────────────────────────────────────────────────────────

def test_rows_match_the_cart_table(pos, display):
    _add_item(pos, price=1.25, quantity=2)
    _add_item(pos, price=3.0, barcode="2234567890123")
    pos.cart_input.setText("10")
    pos._apply_percent_discount()
    pos._show_subtotal()

    assert display.cart_table.rowCount() == pos.cart_table.rowCount() > 0
    for r in range(pos.cart_table.rowCount()):
        assert _texts(display.cart_table, r) == _texts(pos.cart_table, r)
        src, dst = pos.cart_table.item(r, 0), display.cart_table.item(r, 0)
        assert dst.background() == src.background()
        assert dst.font().bold() == src.font().bold()
        assert display.cart_table.rowHeight(r) == pos.cart_table.rowHeight(r)


def test_display_rows_mark_divider_and_payment_rows(pos, display):
    _add_item(pos, price=10.0)
    pos.cart_input.setText("20")
    pos._open_payment("cash")

    rows = pos._display_rows()
    assert any(row["divider"] for row in rows)
    assert rows[-1]["texts"][1] == "Change"
    assert rows[-1]["bold"] is True
    assert rows[-1]["background"] is not None


def test_display_has_no_selection(display):
    assert display.cart_table.selectionMode() == QAbstractItemView.SelectionMode.NoSelection


def test_clearing_the_cart_empties_the_display(pos, display):
    _add_item(pos)
    assert display.cart_table.rowCount() == 1
    pos._clear_cart(override=True)
    assert display.cart_table.rowCount() == 0


# ── Light / dark (frozen) ────────────────────────────────────────────────

def test_fresh_ticket_is_dark(display):
    assert _is_frozen(display) is True


def test_active_ticket_is_light_and_paid_ticket_is_dark(pos, display):
    _add_item(pos)
    assert _is_frozen(display) is False
    for widget in (display.header_widget, display.ticket_title, display.ticket_date, display.ticket_total_lbl):
        assert widget.property("frozen") is False

    pos._open_payment("cash")
    assert _is_frozen(display) is True
    for widget in (display.header_widget, display.ticket_title, display.ticket_date, display.ticket_total_lbl):
        assert widget.property("frozen") is True


# ── Footer ───────────────────────────────────────────────────────────────

def test_open_ticket_shows_running_total(pos, display):
    _add_item(pos, price=1.25, quantity=2)
    assert display.footer_stack.currentIndex() == 0
    assert display.ticket_total_lbl.text() == pos.ticket_total_lbl.text() == "Total  2.50"


def test_partial_payment_shows_remaining(pos, display):
    _add_item(pos, price=10.0)
    pos.cart_input.setText("4")
    pos._open_payment("cash")
    assert display.footer_stack.currentIndex() == 0
    assert display.ticket_total_lbl.text() == "Remaining  6.00"


def test_paid_ticket_shows_total_and_change(pos, display):
    _add_item(pos, price=10.0)
    pos.cart_input.setText("20")
    pos._open_payment("cash")

    assert display.footer_stack.currentIndex() == 1
    assert display.footer_total_lbl.text() == pos.footer_total_lbl.text() == "Total  10.00"
    assert display.footer_change_lbl.text() == pos.footer_change_lbl.text() == "Change  -10.00"


# ── Header / client ──────────────────────────────────────────────────────

def test_header_mirrors_title_and_date(pos, display):
    assert display.ticket_title.text() == pos.ticket_title.text() == "V 1"
    assert display.ticket_date.text() == pos.ticket_date.text() != ""


def test_switching_vtab_mirrors_the_new_tab(window, pos, display):
    _add_item(pos)
    window._switch_vtab(2)
    assert display.ticket_title.text() == "V 2"
    assert display.cart_table.rowCount() == 0
    assert _is_frozen(display) is True

    window._switch_vtab(1)
    assert display.ticket_title.text() == "V 1"
    assert display.cart_table.rowCount() == 1
    assert _is_frozen(display) is False


def test_client_bar_mirrors_invoice_client(pos, display):
    assert display.client_label.isHidden()
    pos.set_client(_make_client(), "ACME")
    assert not display.client_label.isHidden()
    assert display.client_label.text() == "INVOICE - ACME"


def test_display_follows_pos_while_another_screen_is_in_front(window, pos, display):
    """emit_display() must use isHidden(), not isVisible(): the client bar is
    'invisible' whenever Inventory/Settings/... covers the POS screen."""
    pos.set_client(_make_client(), "ACME")
    window._navigate(1)
    pos.emit_display()
    assert display.client_label.text() == "INVOICE - ACME"
    assert not display.client_label.isHidden()


# ── Clock ────────────────────────────────────────────────────────────────

def test_clock_tick_updates_open_ticket(pos, display):
    _add_item(pos)
    pos.ticket_date.setText("01-01-2000 00:00")
    pos._tick_time()
    assert display.ticket_date.text() == pos.ticket_date.text() != "01-01-2000 00:00"


def test_clock_does_not_tick_on_paid_ticket(pos, display):
    _add_item(pos)
    pos._open_payment("cash")
    paid_at = display.ticket_date.text()
    pos.ticket_date.setText("01-01-2000 00:00")  # what a later tick would overwrite
    pos._tick_time()
    assert pos.ticket_date.text() == "01-01-2000 00:00"
    assert display.ticket_date.text() == paid_at


def test_tick_within_the_same_minute_does_not_re_emit(pos, qtbot):
    pos._tick_time(override=True)
    with qtbot.assertNotEmitted(pos.display_changed):
        pos._tick_time(override=True)


# ── Showing / hiding ─────────────────────────────────────────────────────

def test_hidden_on_single_screen(window, display, monkeypatch):
    monkeypatch.setattr(QGuiApplication, "screens", staticmethod(lambda: [window.screen()]))
    window.show()
    assert not display.isVisible()


def test_secondary_screen_skips_the_main_windows_screen(window, monkeypatch):
    other = object()
    monkeypatch.setattr(QGuiApplication, "screens", staticmethod(lambda: [window.screen(), other]))
    assert CustomerDisplay.secondary_screen(window) is other


def test_secondary_screen_is_none_with_one_screen(window, monkeypatch):
    monkeypatch.setattr(QGuiApplication, "screens", staticmethod(lambda: [window.screen()]))
    assert CustomerDisplay.secondary_screen(window) is None


def test_opens_on_second_screen_when_main_window_is_shown(window, display, monkeypatch):
    other = object()
    shown_on = []
    monkeypatch.setattr(CustomerDisplay, "secondary_screen", staticmethod(lambda mw: other))
    monkeypatch.setattr(display, "show_on", shown_on.append)
    window.show()
    assert shown_on == [other]


def test_show_on_takes_the_screens_geometry(display, monkeypatch):
    class FakeScreen:
        def geometry(self):
            return QRect(1024, 0, 800, 600)
    monkeypatch.setattr(display, "showFullScreen", display.show)
    display.show_on(FakeScreen())
    assert display.isVisible()
    assert display.geometry() == QRect(1024, 0, 800, 600)


def test_settings_button_toggles_display(window, display, monkeypatch):
    monkeypatch.setattr(CustomerDisplay, "secondary_screen", staticmethod(lambda mw: None))
    window.settings_screen.btn_customer_display.click()
    assert display.isVisible()
    window.settings_screen.btn_customer_display.click()
    assert not display.isVisible()


def test_display_is_a_separate_window_owned_by_main_window(window, display):
    assert display.isWindow()
    assert display.parent() is window
