"""
Tests for app.ui.main_window.MainWindow: screen wiring, V-tab switching,
and cross-screen signal plumbing (client/product selection into POS).
"""
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


def test_store_label_shows_default_store_name(window):
    assert window.store_label.text() == "My Supermarket"


def test_vtab_buttons_created_and_tab_one_checked(window):
    assert len(window._vtab_buttons) == MAX_VTABS
    assert window._vtab_buttons[1].isChecked() is True


def test_switch_vtab_updates_active_tab_and_pos_screen(window):
    window._switch_vtab(3)
    assert window._active_vtab == 3
    assert window.pos_screen._active_tab == 3
    assert window._vtab_buttons[3].isChecked() is True


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
        client = ClientService.create(session, name="Acme", vatNumber="V1", address="1 Main St")
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


def test_settings_saved_signal_refreshes_store_label_and_salesperson(window):
    with get_session() as session:
        from app.core.settings_service import SettingsService
        SettingsService.set(session, "store_name", "Renamed Shop")
        SettingsService.set(session, "cashier_name", "Alice")

    window.settings_screen.settings_saved.emit()

    assert window.store_label.text() == "Renamed Shop"
    assert window.salesperson_label.text() == "Alice"


def test_pos_screen_tab_updated_relabels_vtab_button(window):
    window.pos_screen.tab_updated.emit(1, "12.50")
    assert window._vtab_buttons[1].text() == "V 1\n12.50"


def test_pos_screen_salesperson_changed_updates_label(window):
    window.pos_screen.salesperson_changed.emit("Admin")
    assert window.salesperson_label.text() == "Admin"


def test_update_clock_sets_readable_text(window):
    window._update_clock()
    assert window.clock_label.text() != ""
