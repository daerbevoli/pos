"""
Tests for the POS bottom-grid shortcut wiring in app.ui.pos_screen.POSScreen:
selector buttons populated from the DB, tapping one fills the product slots,
tapping a filled slot adds to the cart.
"""
import pytest

from app.ui.pos_screen import POSScreen
from app.core.database import get_session
from app.core.product_service import ProductService
from app.core.sales_service import CartItem


@pytest.fixture
def screen(qtbot, patched_db):
    s = POSScreen()
    qtbot.addWidget(s)
    return s


def _make_products(names):
    with get_session() as session:
        return {n: ProductService.create(session, name=n, price=2.5, tax=21).id for n in names}


def _shortcut(name, product_ids):
    with get_session() as session:
        sc = ProductService.create_shortcut(session, name)
        ProductService.set_shortcut_items(session, sc.id, product_ids)
        return sc.id


def test_no_shortcuts_leaves_selectors_disabled_and_slots_empty(screen):
    assert all(not b.isEnabled() for b in screen.shortcut_buttons)
    assert all(not b.isEnabled() for b in screen.slot_buttons)
    assert screen._slot_product_ids == [None] * screen.SLOT_COUNT


def test_reload_shortcuts_populates_selector_buttons(screen):
    p = _make_products(["A", "B"])
    _shortcut("Lunch", [p["A"]])
    _shortcut("Drinks", [p["B"]])

    screen.reload_shortcuts()

    # get_all_shortcuts orders by name.
    assert screen.shortcut_buttons[0].text() == "Drinks"
    assert screen.shortcut_buttons[0].isEnabled()
    assert screen.shortcut_buttons[1].text() == "Lunch"
    assert not screen.shortcut_buttons[2].isEnabled()


def test_pressing_shortcut_fills_slots_in_order(screen):
    p = _make_products(["Cola", "Water", "Juice"])
    _shortcut("Drinks", [p["Juice"], p["Cola"], p["Water"]])
    screen.reload_shortcuts()

    screen._on_shortcut_pressed(0)

    assert screen._slot_product_ids[:3] == [p["Juice"], p["Cola"], p["Water"]]
    assert screen._slot_product_ids[3] is None
    assert screen.slot_buttons[0].isEnabled()
    assert "Cola" in screen.slot_buttons[1].text()
    assert screen._active_shortcut_id is not None
    assert screen.shortcut_buttons[0].property("active") is True


def test_switching_shortcut_clears_previous_slots(screen):
    p = _make_products(["A", "B", "C"])
    _shortcut("One", [p["A"], p["B"]])
    _shortcut("Two", [p["C"]])
    screen.reload_shortcuts()

    screen._on_shortcut_pressed(0)
    screen._on_shortcut_pressed(1)

    assert screen._slot_product_ids[0] == p["C"]
    assert screen._slot_product_ids[1] is None
    assert not screen.slot_buttons[1].isEnabled()
    assert screen.shortcut_buttons[0].property("active") is False
    assert screen.shortcut_buttons[1].property("active") is True


def test_inactive_products_are_skipped(screen):
    p = _make_products(["Live", "Dead"])
    with get_session() as session:
        ProductService.deactivate(session, p["Dead"])
    _shortcut("Mixed", [p["Dead"], p["Live"]])
    screen.reload_shortcuts()

    screen._on_shortcut_pressed(0)

    assert screen._slot_product_ids[0] == p["Live"]
    assert screen._slot_product_ids[1] is None


def test_tapping_filled_slot_adds_product_to_cart(screen):
    p = _make_products(["Cola"])
    _shortcut("Drinks", [p["Cola"]])
    screen.reload_shortcuts()
    screen._on_shortcut_pressed(0)

    screen.slot_buttons[0].click()

    items = [e for e in screen.cart.entries if isinstance(e, CartItem)]
    assert len(items) == 1
    assert items[0].product_id == p["Cola"]


def test_tapping_empty_slot_is_noop(screen):
    screen._on_slot_pressed(0)
    assert not any(isinstance(e, CartItem) for e in screen.cart.entries)


def test_deleted_shortcut_clears_active_selection_on_reload(screen):
    p = _make_products(["A"])
    sc_id = _shortcut("Temp", [p["A"]])
    screen.reload_shortcuts()
    screen._on_shortcut_pressed(0)
    assert screen._active_shortcut_id == sc_id

    with get_session() as session:
        ProductService.delete_shortcut(session, sc_id)
    screen.reload_shortcuts()

    assert screen._active_shortcut_id is None
    assert screen._slot_product_ids == [None] * screen.SLOT_COUNT
    assert not screen.shortcut_buttons[0].isEnabled()
