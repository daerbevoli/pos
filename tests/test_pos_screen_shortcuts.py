"""
Tests for the POS bottom-grid shortcut wiring in app.ui.pos_screen.POSScreen
(its ShortcutGrid, app.ui.widgets.shortcut_grid):
selector buttons populated from the DB, tapping one fills the product slots,
tapping a filled slot adds to the cart.
"""
import pytest

from app.ui.pos_screen import POSScreen
from app.core.database import get_session
from app.core.inventory.product_service import ProductService
from app.core.sale.cart import CartItem


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
    assert all(not b.isEnabled() for b in screen.shortcut_grid.shortcut_buttons)
    assert all(not b.isEnabled() for b in screen.shortcut_grid.slot_buttons)
    assert screen.shortcut_grid._slot_product_ids == [None] * screen.shortcut_grid.SLOT_COUNT


def test_reload_shortcuts_populates_selector_buttons(screen):
    p = _make_products(["A", "B"])
    _shortcut("Lunch", [p["A"]])
    _shortcut("Drinks", [p["B"]])

    screen.reload_shortcuts()

    # get_all_shortcuts orders by name.
    assert screen.shortcut_grid.shortcut_buttons[0].text() == "Drinks"
    assert screen.shortcut_grid.shortcut_buttons[0].isEnabled()
    assert screen.shortcut_grid.shortcut_buttons[1].text() == "Lunch"
    assert not screen.shortcut_grid.shortcut_buttons[2].isEnabled()


def test_pressing_shortcut_fills_slots_in_order(screen):
    p = _make_products(["Cola", "Water", "Juice"])
    _shortcut("Drinks", [p["Juice"], p["Cola"], p["Water"]])
    screen.reload_shortcuts()

    screen.shortcut_grid._on_shortcut_pressed(0)

    assert screen.shortcut_grid._slot_product_ids[:3] == [p["Juice"], p["Cola"], p["Water"]]
    assert screen.shortcut_grid._slot_product_ids[3] is None
    assert screen.shortcut_grid.slot_buttons[0].isEnabled()
    assert "Cola" in screen.shortcut_grid.slot_buttons[1].text()
    assert screen.shortcut_grid.active_shortcut_id is not None
    assert screen.shortcut_grid.shortcut_buttons[0].property("active") is True


def test_switching_shortcut_clears_previous_slots(screen):
    p = _make_products(["A", "B", "C"])
    _shortcut("One", [p["A"], p["B"]])
    _shortcut("Two", [p["C"]])
    screen.reload_shortcuts()

    screen.shortcut_grid._on_shortcut_pressed(0)
    screen.shortcut_grid._on_shortcut_pressed(1)

    assert screen.shortcut_grid._slot_product_ids[0] == p["C"]
    assert screen.shortcut_grid._slot_product_ids[1] is None
    assert not screen.shortcut_grid.slot_buttons[1].isEnabled()
    assert screen.shortcut_grid.shortcut_buttons[0].property("active") is False
    assert screen.shortcut_grid.shortcut_buttons[1].property("active") is True


def test_inactive_products_are_skipped(screen):
    p = _make_products(["Live", "Dead"])
    with get_session() as session:
        ProductService.deactivate(session, p["Dead"])
    _shortcut("Mixed", [p["Dead"], p["Live"]])
    screen.reload_shortcuts()

    screen.shortcut_grid._on_shortcut_pressed(0)

    assert screen.shortcut_grid._slot_product_ids[0] == p["Live"]
    assert screen.shortcut_grid._slot_product_ids[1] is None


def test_tapping_filled_slot_adds_product_to_cart(screen):
    p = _make_products(["Cola"])
    _shortcut("Drinks", [p["Cola"]])
    screen.reload_shortcuts()
    screen.shortcut_grid._on_shortcut_pressed(0)

    screen.shortcut_grid.slot_buttons[0].click()

    items = [e for e in screen.cart.entries if isinstance(e, CartItem)]
    assert len(items) == 1
    assert items[0].product_id == p["Cola"]


def test_tapping_empty_slot_is_noop(screen):
    screen.shortcut_grid._on_slot_pressed(0)
    assert not any(isinstance(e, CartItem) for e in screen.cart.entries)


def test_deleted_shortcut_clears_active_selection_on_reload(screen):
    p = _make_products(["A"])
    sc_id = _shortcut("Temp", [p["A"]])
    screen.reload_shortcuts()
    screen.shortcut_grid._on_shortcut_pressed(0)
    assert screen.shortcut_grid.active_shortcut_id == sc_id

    with get_session() as session:
        ProductService.delete_shortcut(session, sc_id)
    screen.reload_shortcuts()

    assert screen.shortcut_grid.active_shortcut_id is None
    assert screen.shortcut_grid._slot_product_ids == [None] * screen.shortcut_grid.SLOT_COUNT
    assert not screen.shortcut_grid.shortcut_buttons[0].isEnabled()


def test_selected_shortcut_is_per_vtab(screen):
    p = _make_products(["A", "B"])
    one = _shortcut("One", [p["A"]])
    two = _shortcut("Two", [p["B"]])
    screen.reload_shortcuts()
    screen.shortcut_grid._on_shortcut_pressed(0)  # "One" on V1

    screen.set_active_tab(2)
    assert screen.shortcut_grid.active_shortcut_id is None
    assert screen.shortcut_grid._slot_product_ids == [None] * screen.shortcut_grid.SLOT_COUNT

    screen.shortcut_grid._on_shortcut_pressed(1)  # "Two" on V2
    screen.set_active_tab(1)
    assert screen.shortcut_grid.active_shortcut_id == one
    assert screen.shortcut_grid._slot_product_ids[0] == p["A"]

    screen.set_active_tab(2)
    assert screen.shortcut_grid.active_shortcut_id == two
    assert screen.shortcut_grid._slot_product_ids[0] == p["B"]


def test_shortcut_deleted_while_on_other_tab_is_dropped(screen):
    p = _make_products(["A"])
    sc_id = _shortcut("Temp", [p["A"]])
    screen.reload_shortcuts()
    screen.shortcut_grid._on_shortcut_pressed(0)
    screen.set_active_tab(2)

    with get_session() as session:
        ProductService.delete_shortcut(session, sc_id)
    screen.reload_shortcuts()
    screen.set_active_tab(1)

    assert screen.shortcut_grid.active_shortcut_id is None
    assert screen.shortcut_grid._slot_product_ids == [None] * screen.shortcut_grid.SLOT_COUNT


def test_more_shortcuts_than_buttons_pages_through_them(screen):
    grid = screen.shortcut_grid
    cap = len(grid.shortcut_buttons)
    p = _make_products(["X"])
    names = [f"S{i:02d}" for i in range(cap + 5)]  # 2 pages of cap - 1
    for n in names:
        _shortcut(n, [p["X"]])
    screen.reload_shortcuts()

    assert [b.text() for b in grid.shortcut_buttons[:-1]] == names[: cap - 1]
    assert grid.shortcut_buttons[-1].text() == "More ▸"

    grid._on_shortcut_pressed(cap - 1)
    assert [b.text() for b in grid.shortcut_buttons[:6]] == names[cap - 1:]
    assert not grid.shortcut_buttons[6].isEnabled()
    assert grid.shortcut_buttons[-1].text() == "◂ Back"

    grid._on_shortcut_pressed(0)  # opens the shortcut on this page, not page 1's
    with get_session() as session:
        assert grid.active_shortcut_id == ProductService.get_all_shortcuts(session)[cap - 1].id
    assert grid.shortcut_buttons[0].property("active") is True

    grid._on_shortcut_pressed(cap - 1)  # back to the first page
    assert grid.shortcut_buttons[0].text() == names[0]
    assert grid.shortcut_buttons[0].property("active") is False


def test_more_products_than_slots_pages_through_them(screen):
    grid = screen.shortcut_grid
    cap = grid.SLOT_COUNT
    p = _make_products([f"P{i:02d}" for i in range(cap + 3)])
    ids = list(p.values())
    _shortcut("Big", ids)
    screen.reload_shortcuts()
    grid._on_shortcut_pressed(0)

    assert grid._slot_product_ids[: cap - 1] == ids[: cap - 1]
    assert grid.slot_buttons[-1].text() == "More ▸"

    grid._on_slot_pressed(cap - 1)
    assert grid._slot_product_ids[:4] == ids[cap - 1:]
    assert grid.slot_buttons[-1].text() == "◂ Back"
    assert screen.cart.entries == []  # paging adds nothing to the cart

    screen.reload_shortcuts()  # e.g. a price change keeps the page
    assert grid._slot_product_ids[0] == ids[cap - 1]

    grid._on_slot_pressed(cap - 1)
    assert grid._slot_product_ids[0] == ids[0]
