"""
Tests for app.ui.main_window.MainWindow: screen wiring, V-tab switching,
and cross-screen signal plumbing (client/product selection into POS).
"""
import logging

import pytest

from app.ui.main_window import MainWindow, MAX_VTABS
from app.core.product_service import ProductService
from app.core.client_service import ClientService
from app.core.database import get_session


@pytest.fixture
def window(qtbot, patched_db):
    w = MainWindow()
    qtbot.addWidget(w)
    return w


def test_construction_wires_all_screens(window):
    assert window.stack.count() == 5
    assert window.stack.currentIndex() == 0  # POS screen first


def test_clock_box_sits_in_the_vtab_bar_after_the_tabs(window):
    tab_bar = window._vtab_buttons[1].parentWidget()
    assert window.clock_label.parentWidget().parentWidget() is tab_bar
    assert window.salesperson_label.parentWidget() is window.clock_label.parentWidget()
    assert window.error_badge.parentWidget() is tab_bar


def test_vtab_buttons_created_and_tab_one_checked(window):
    assert len(window._vtab_buttons) == MAX_VTABS
    assert window._vtab_buttons[1].isChecked() is True


def test_switch_vtab_updates_active_tab_and_pos_screen(window):
    window._switch_vtab(3)
    assert window._active_vtab == 3
    assert window.pos_screen._active_tab == 3
    assert window._vtab_buttons[3].isChecked() is True


def test_overlay_covers_whole_window_including_vtab_bar(window):
    window.pos_screen.overlay.show_message("msg")
    overlay = window.pos_screen.overlay
    assert overlay.parentWidget() is window
    assert overlay.geometry() == window.rect()
    tab_btn = window._vtab_buttons[2]
    centre = tab_btn.mapTo(window, tab_btn.rect().center())
    assert window.childAt(centre) in (overlay, overlay.card, overlay.message_label)


def test_switch_to_same_tab_is_noop(window):
    window._switch_vtab(1)
    assert window._active_vtab == 1


def test_navigate_switches_stack_screen(window):
    window._navigate(2)  # client screen
    assert window.stack.currentIndex() == 2


def test_navigate_back_to_pos_activates_current_vtab(window):
    window._switch_vtab(2)
    window._navigate(1)  # go to inventory
    window._navigate(0)  # back to POS
    assert window.stack.currentIndex() == 0
    assert window.pos_screen._active_tab == 2


def test_client_screen_navigate_signal_switches_stack(window):
    window.client_screen.navigate.emit(0)
    assert window.stack.currentIndex() == 0


def test_inventory_screen_navigate_signal_switches_stack(window):
    window.inventory_screen.navigate.emit(0)
    assert window.stack.currentIndex() == 0


def test_reports_screen_navigate_signal_switches_stack(window):
    window.reports_screen.navigate.emit(0)
    assert window.stack.currentIndex() == 0


def test_selected_client_signal_sets_pos_screen_client(window):
    with get_session() as session:
        client = ClientService.create(
            session, name="Acme", vatNumber="V1", street="1 Main St", zip_code="1000", city="Brussels",
        )
        client_id = client.id

    window.client_screen.selected_client.emit(client_id, "Acme")

    assert window.pos_screen.client_id == client_id
    assert window.pos_screen.is_invoice is True


def test_selected_product_signal_adds_to_pos_cart(window):
    with get_session() as session:
        product = ProductService.create(session, name="Widget", price=2.0, stock_quantity=10)
        product_id = product.id

    window.inventory_screen.selected_product.emit(product_id)

    assert len(window.pos_screen.cart.entries) == 1
    assert window.pos_screen.cart.entries[0].product_id == product_id


def test_settings_saved_signal_refreshes_salesperson(window):
    with get_session() as session:
        from app.core.settings_service import SettingsService
        SettingsService.set(session, "cashier_name", "Alice")

    window.settings_screen.settings_saved.emit()

    assert window.salesperson_label.text() == "Alice"


def test_pos_screen_tab_updated_relabels_vtab_button(window):
    window.pos_screen.tab_updated.emit(1, "12.50")
    assert window._vtab_buttons[1].text() == "V 1\n12.50"


def test_settings_screen_salesperson_changed_updates_label(window):
    window.settings_screen.salesperson_changed.emit("Admin")
    assert window.salesperson_label.text() == "Admin"


def test_update_clock_sets_readable_text(window):
    window._update_clock()
    assert window.clock_label.text() != ""


def test_rf_cn_mode_shows_suffix_next_to_salesperson(window):
    window.settings_screen.salesperson_changed.emit("Admin")
    window.pos_screen.rf_cn_mode_changed.emit(True)
    assert window.salesperson_label.text() == "Admin (RF / CN)"
    window.pos_screen.rf_cn_mode_changed.emit(False)
    assert window.salesperson_label.text() == "Admin"


def test_settings_admin_button_enables_admin_on_pos(window):
    window.settings_screen._admin()
    assert window.pos_screen.isAdmin is True
    assert window.salesperson_label.text() == "Admin"


def test_settings_rf_cn_button_toggles_pos_mode_and_returns_to_pos(window):
    window._navigate(3)
    window.settings_screen._admin()
    window.settings_screen._rf_cn()
    assert window.stack.currentIndex() == 0
    assert window._active_vtab == 1
    assert window.pos_screen.cart.is_refund is True


def _ring_up_item(window, barcode):
    with get_session() as session:
        p = ProductService.create(session, name="Item", price=5.0, tax=0, stock_quantity=100, unit="pcs", barcode=barcode)
        pid = p.id
    window.pos_screen.add_product_by_id(pid)


def test_rf_cn_with_open_ticket_switches_to_free_vtab(window):
    _ring_up_item(window, "rfmw1")
    window.settings_screen._admin()
    window.settings_screen._rf_cn()

    assert window._active_vtab == 2
    assert window.pos_screen.cart.is_refund is True
    window._switch_vtab(1)
    assert window.pos_screen.cart.is_refund is False
    assert len(window.pos_screen.cart.entries) == 1


def test_rf_cn_with_every_vtab_open_shows_overlay(window):
    for i in range(1, MAX_VTABS + 1):
        window._switch_vtab(i)
        _ring_up_item(window, f"rfmw{i}0")
    window.settings_screen._admin()
    window.settings_screen._rf_cn()

    assert window._active_vtab == MAX_VTABS
    assert window.pos_screen.cart.is_refund is False
    assert not window.pos_screen.overlay.isHidden()


def test_error_badge_opens_logs_and_acknowledges(window):
    window.error_badge._on_record("ERROR printer failed", logging.ERROR)
    window.error_badge.click()
    assert window.stack.currentWidget() is window.settings_screen
    assert window.settings_screen.tabs.currentWidget() is window.settings_screen.log_panel
    assert not window.error_badge.active and window.error_badge.count == 0
