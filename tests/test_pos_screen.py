"""
Tests for app.ui.pos_screen.POSScreen: the core checkout/cart feature.

Covers scanning/adding items (incl. pending weight items), discounts,
subtotal sections, payment (full/partial/mixed/invoice), freeze/unfreeze,
ticket reopen + reversal lines, tab-state persistence, and sale browsing.
"""
import pytest
from PyQt6.QtWidgets import QMessageBox

from app.ui.pos_screen import POSScreen
from app.core.product_service import ProductService
from app.core.client_service import ClientService
from app.core.sales_service import CartItem, DiscountEntry, PaymentEntry, SubtotalMarker, SalesService
from app.core.database import get_session
from app.models.models import Sale


@pytest.fixture(autouse=True)
def _auto_confirm_message_boxes(monkeypatch):
    """_clear_cart() and friends pop a real QMessageBox.question() unless
    called with override=True; default every test to "Yes" so accidental
    calls don't hang, while still letting individual tests override this."""
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **kw: QMessageBox.StandardButton.Yes))


@pytest.fixture
def screen(qtbot, patched_db):
    s = POSScreen()
    qtbot.addWidget(s)
    return s


def _make_product(session, **overrides):
    data = {"name": "Item", "price": 5.0, "tax": 0, "stock_quantity": 100, "unit": "pcs"}
    data.update(overrides)
    return ProductService.create(session, **data)


def _add_product(**overrides):
    with get_session() as session:
        p = _make_product(session, **overrides)
        return p.id, p.barcode, p.unit


def _scan(screen, text):
    screen.combined_input.setText(text)
    screen._on_barcode_enter()


def _selected_entry(screen):
    idx = screen._get_selected_entry_index()
    return screen.cart.entries[idx] if idx is not None else None


# ── Construction ─────────────────────────────────────────────────────────

def test_initial_state_is_a_clean_finished_ticket(screen):
    assert screen.cart.entries == []
    assert screen.sale_finished is True
    assert screen.is_invoice is False
    assert screen.currency == "€"


# ── Scanning / adding items ──────────────────────────────────────────────

def test_scan_known_barcode_adds_item(screen):
    pid, barcode, _ = _add_product(barcode="1234567890123", price=2.5)
    _scan(screen, barcode)

    assert len(screen.cart.entries) == 1
    item = screen.cart.entries[0]
    assert item.product_id == pid
    assert item.quantity == 1
    assert item.unit_price == 2.5
    assert screen.combined_input.text() == ""


def test_scan_unknown_barcode_shows_overlay(screen):
    _scan(screen, "0000000000000")
    assert not screen.overlay.isHidden()
    assert screen.cart.entries == []


def test_scan_typing_unfreezes_a_finished_ticket(screen):
    assert screen.sale_finished is True
    pid, barcode, _ = _add_product(barcode="111")
    _scan(screen, barcode)
    assert screen.sale_finished is False


def test_scan_with_quantity_prefix(screen):
    pid, barcode, _ = _add_product(barcode="1234567890123")
    _scan(screen, f"3{barcode}")
    assert screen.cart.entries[0].quantity == 3


def test_scan_weight_unit_without_quantity_creates_pending_item(screen):
    pid, barcode, unit = _add_product(barcode="222", unit="kg", price=3.0)
    _scan(screen, barcode)

    item = screen.cart.entries[0]
    assert item.quantity is None
    assert item.unit == "kg"


def test_scan_weight_unit_with_typed_quantity_is_not_pending(screen):
    # Quantity-prefix parsing only kicks in for realistic 13/14-digit
    # barcodes (see _resolve_scan's docstring) — a short test barcode
    # wouldn't trigger it.
    pid, barcode, unit = _add_product(barcode="3330000000000", unit="kg")
    _scan(screen, f"2{barcode}")
    assert screen.cart.entries[0].quantity == 2


def test_entering_amount_resolves_pending_item(screen):
    pid, barcode, unit = _add_product(barcode="444", unit="kg", price=2.0)
    _scan(screen, barcode)
    assert screen._selected_pending_item() is not None

    screen.combined_input.setText("1.5")
    screen._on_barcode_enter()

    assert screen.cart.entries[0].quantity == 1.5
    assert screen._selected_pending_item() is None


def test_pending_item_blocks_long_scan_attempt(screen):
    pid, barcode, unit = _add_product(barcode="555", unit="kg")
    _scan(screen, barcode)

    _scan(screen, "9999999999999")  # looks like a barcode scan, > 6 chars

    assert screen.cart.entries[0].quantity is None  # still pending
    assert not screen.overlay.isHidden()


def test_add_product_by_id_from_inventory_navigation(screen):
    pid, barcode, unit = _add_product(name="Direct Add", price=4.0)
    screen.add_product_by_id(pid)

    assert len(screen.cart.entries) == 1
    assert screen.cart.entries[0].product_id == pid


def test_add_product_by_id_with_typed_quantity(screen):
    pid, barcode, unit = _add_product()
    screen.combined_input.setText("5")
    screen.add_product_by_id(pid)
    assert screen.cart.entries[0].quantity == 5


# ── Increase / decrease / remove ─────────────────────────────────────────

def test_increase_and_decrease_selected_item(screen):
    pid, barcode, _ = _add_product(barcode="666")
    _scan(screen, barcode)

    screen._increase_product()
    assert screen.cart.entries[0].quantity == 2

    screen._decrease_product()
    assert screen.cart.entries[0].quantity == 1


def test_decrease_stops_at_one(screen):
    pid, barcode, _ = _add_product(barcode="777")
    _scan(screen, barcode)
    screen._decrease_product()
    assert screen.cart.entries[0].quantity == 1


def test_increase_decrease_ignored_for_weight_units(screen):
    pid, barcode, _ = _add_product(barcode="8880000000000", unit="kg")
    _scan(screen, f"2{barcode}")
    screen._increase_product()
    assert screen.cart.entries[0].quantity == 2


def test_remove_selected_backspaces_input_text_first(screen):
    screen.combined_input.setText("123")
    screen._remove_selected()
    assert screen.combined_input.text() == "12"


def test_remove_selected_removes_cart_item_without_prior_sale(screen):
    pid, barcode, _ = _add_product(barcode="999")
    _scan(screen, barcode)
    assert len(screen.cart.entries) == 1

    screen._remove_selected()
    assert screen.cart.entries == []


def test_remove_selected_on_finished_ticket_is_noop(screen):
    screen._remove_selected()  # sale_finished True, nothing to do
    assert screen.cart.entries == []


# ── Discounts ─────────────────────────────────────────────────────────────

def test_percent_discount_applies_to_last_item(screen):
    pid, barcode, _ = _add_product(barcode="d1", price=10.0)
    _scan(screen, barcode)  # line_total = 10.0

    screen.combined_input.setText("10")
    screen._apply_percent_discount()

    discounts = [e for e in screen.cart.entries if isinstance(e, DiscountEntry)]
    assert len(discounts) == 1
    assert discounts[0].amount == 1.0
    assert discounts[0].label == "10%"


def test_amount_discount_capped_at_base(screen):
    pid, barcode, _ = _add_product(barcode="d2", price=10.0)
    _scan(screen, barcode)

    screen.combined_input.setText("999")
    screen._apply_amount_discount()

    discount = next(e for e in screen.cart.entries if isinstance(e, DiscountEntry))
    assert discount.amount == 10.0


def test_discount_without_amount_shows_overlay(screen):
    pid, barcode, _ = _add_product(barcode="d3")
    _scan(screen, barcode)
    screen.combined_input.setText("")
    screen._apply_percent_discount()
    assert not screen.overlay.isHidden()
    assert not any(isinstance(e, DiscountEntry) for e in screen.cart.entries)


def test_discount_on_empty_cart_shows_overlay(screen):
    screen._unfreeze_ticket()
    screen.combined_input.setText("10")
    screen._apply_percent_discount()
    assert not screen.overlay.isHidden()


def test_section_discount_applies_after_subtotal(screen):
    p1, b1, _ = _add_product(barcode="s1", price=10.0)
    p2, b2, _ = _add_product(barcode="s2", price=5.0)
    _scan(screen, b1)
    _scan(screen, b2)
    screen._show_subtotal()  # section total = 15.0

    screen.combined_input.setText("10")
    screen._apply_amount_discount()

    discount = next(e for e in screen.cart.entries if isinstance(e, DiscountEntry))
    assert discount.amount == 10.0


# ── Subtotal sections ─────────────────────────────────────────────────────

def test_show_subtotal_inserts_marker(screen):
    pid, barcode, _ = _add_product(barcode="sub1")
    _scan(screen, barcode)
    screen._show_subtotal()
    assert any(isinstance(e, SubtotalMarker) for e in screen.cart.entries)


def test_show_subtotal_on_empty_section_is_noop(screen):
    screen._unfreeze_ticket()
    screen._show_subtotal()
    assert screen.cart.entries == []


# ── Payment: guards ──────────────────────────────────────────────────────

def test_payment_on_finished_ticket_shows_no_sale_overlay(screen):
    screen._open_payment("cash")
    assert not screen.overlay.isHidden()


def test_payment_with_empty_cart_shows_overlay(screen):
    screen._unfreeze_ticket()
    screen._open_payment("cash")
    assert not screen.overlay.isHidden()


def test_payment_with_pending_item_blocked(screen):
    pid, barcode, unit = _add_product(barcode="pend1", unit="kg")
    _scan(screen, barcode)
    screen._open_payment("cash")
    assert not screen.overlay.isHidden()


# ── Payment: full settlement ─────────────────────────────────────────────

def test_full_cash_payment_finalizes_sale(screen):
    pid, barcode, _ = _add_product(barcode="pay1", price=10.0)
    _scan(screen, barcode)

    screen._open_payment("cash")

    assert screen.sale_finished is True
    assert screen._current_sale_id is not None
    with get_session() as session:
        sale = session.query(Sale).filter_by(id=screen._current_sale_id).first()
    assert sale.status == "completed"
    assert sale.final_amount == 10.0
    assert sale.payment_method == "cash"


def test_full_payment_with_overpayment_shows_change(screen):
    pid, barcode, _ = _add_product(barcode="pay2", price=10.0)
    _scan(screen, barcode)

    screen.combined_input.setText("20")
    screen._open_payment("cash")

    assert screen._frozen_change == 10.0
    assert "Change" in screen.footer_change_lbl.text()


def test_payment_deducts_stock(screen):
    pid, barcode, _ = _add_product(barcode="pay3", price=1.0, stock_quantity=50)
    _scan(screen, barcode)
    screen._open_payment("cash")

    with get_session() as session:
        product = ProductService.get_by_id(session, pid)
    assert product.stock_quantity == 49


def test_underpayment_creates_partial_payment_entry(screen):
    pid, barcode, _ = _add_product(barcode="pay4", price=20.0)
    _scan(screen, barcode)

    screen.combined_input.setText("5")
    screen._open_payment("cash")

    assert screen.sale_finished is False
    payments = [e for e in screen.cart.entries if isinstance(e, PaymentEntry)]
    assert len(payments) == 1
    assert payments[0].amount == 5.0
    assert screen.cart.remaining_due == 15.0


def test_second_partial_payment_merges_same_method(screen):
    pid, barcode, _ = _add_product(barcode="pay5", price=20.0)
    _scan(screen, barcode)
    screen.combined_input.setText("5")
    screen._open_payment("cash")

    screen.combined_input.setText("5")
    screen._open_payment("cash")

    payments = [e for e in screen.cart.entries if isinstance(e, PaymentEntry)]
    assert len(payments) == 1
    assert payments[0].amount == 10.0


def test_mixed_payment_completes_sale_with_mixed_method(screen):
    pid, barcode, _ = _add_product(barcode="pay6", price=20.0)
    _scan(screen, barcode)

    screen.combined_input.setText("5")
    screen._open_payment("cash")  # partial cash

    screen.combined_input.setText("15")
    screen._open_payment("card")  # rest via card -> settles

    assert screen.sale_finished is True
    with get_session() as session:
        sale = session.query(Sale).filter_by(id=screen._current_sale_id).first()
    assert sale.payment_method == "mixed"
    breakdown = {leg["method"]: leg["amount"] for leg in screen._frozen_breakdown}
    assert breakdown == {"cash": 5.0, "card": 15.0}


def test_payment_guard_blocks_cart_mutation_mid_payment(screen):
    pid, barcode, _ = _add_product(barcode="pay7", price=20.0)
    _scan(screen, barcode)
    screen.combined_input.setText("5")
    screen._open_payment("cash")  # partial payment outstanding

    screen._increase_product()  # should be blocked
    assert screen.cart.entries[0].quantity == 1
    assert not screen.overlay.isHidden()


def test_payment_zero_amount_shows_overlay(screen):
    pid, barcode, _ = _add_product(barcode="pay8", price=10.0)
    _scan(screen, barcode)
    screen.combined_input.setText("0")
    screen._open_payment("cash")
    assert not screen.overlay.isHidden()
    assert screen.sale_finished is False  # never settled


# ── Invoices ─────────────────────────────────────────────────────────────

def test_set_client_marks_invoice_and_shows_label(screen):
    with get_session() as session:
        client = ClientService.create(session, name="Acme", vatNumber="V1")
        client_id = client.id

    screen.set_client(client_id, "Acme")

    assert screen.is_invoice is True
    assert screen.client_id == client_id
    assert not screen.client_label.isHidden()
    assert "Acme" in screen.client_label.text()


def test_invoice_payment_creates_invoice_record(screen):
    with get_session() as session:
        client = ClientService.create(session, name="Acme", vatNumber="V1")
        client_id = client.id
    pid, barcode, _ = _add_product(barcode="inv1", price=8.0)

    screen.set_client(client_id, "Acme")
    _scan(screen, barcode)
    screen._open_payment("cash")

    with get_session() as session:
        sale = session.query(Sale).filter_by(id=screen._current_sale_id).first()
        assert sale.invoice is not None
        assert sale.invoice.client_id == client_id


# ── Freeze / unfreeze / clear ─────────────────────────────────────────────

def test_clear_cart_override_resets_everything(screen):
    pid, barcode, _ = _add_product(barcode="clr1")
    _scan(screen, barcode)
    screen.set_client(1, "Someone")

    screen._clear_cart(override=True)

    assert screen.cart.entries == []
    assert screen.sale_finished is True
    assert screen.is_invoice is False
    assert screen.client_id is None
    assert screen.client_label.isHidden()


def test_clear_cart_noop_when_nothing_active(screen):
    screen._clear_cart(override=False)
    assert screen.cart.entries == []


def test_unfreeze_ticket_clears_previous_cart(screen):
    pid, barcode, _ = _add_product(barcode="uf1", price=5.0)
    _scan(screen, barcode)
    screen._open_payment("cash")  # freeze via full payment
    assert screen.sale_finished is True

    screen._unfreeze_ticket()

    assert screen.sale_finished is False
    assert screen.cart.entries == []
    assert screen._current_sale_id is None


# ── Reopen ticket + reversal lines ───────────────────────────────────────

def test_reopen_ticket_restores_snapshot_without_clearing(screen):
    pid, barcode, _ = _add_product(barcode="reopen1", price=5.0)
    _scan(screen, barcode)
    screen._open_payment("cash")
    sale_id = screen._current_sale_id

    screen._reopen_ticket()

    assert screen.sale_finished is False
    assert screen._current_sale_id == sale_id
    assert len(screen.cart.entries) == 1
    assert screen.cart.entries[0].product_id == pid


def test_reopen_ticket_noop_when_not_finished(screen):
    pid, barcode, _ = _add_product(barcode="reopen2")
    _scan(screen, barcode)  # unfreezes -> sale_finished False
    screen._reopen_ticket()  # should be a no-op
    assert screen._current_sale_id is None


def test_reopen_ticket_blocked_once_invoiced(screen):
    """An issued invoice must stay immutable — reopening the sale it came
    from (to overwrite its line items via update_sale) has to be refused."""
    with get_session() as session:
        client = ClientService.create(session, name="Acme", vatNumber="V1")
        client_id = client.id
    pid, barcode, _ = _add_product(barcode="reopen3", price=5.0)

    screen.set_client(client_id, "Acme")
    _scan(screen, barcode)
    screen._open_payment("cash")
    sale_id = screen._current_sale_id
    assert screen.sale_finished is True

    screen._reopen_ticket()

    assert screen.sale_finished is True  # still frozen — reopen was refused
    assert screen._current_sale_id == sale_id
    assert not screen.overlay.isHidden()
    with get_session() as session:
        sale = session.query(Sale).filter_by(id=sale_id).first()
        assert sale.invoice is not None
        assert sale.status == "completed"  # untouched by the refused reopen


def test_removing_item_after_reopen_appends_reversal_line(screen):
    pid, barcode, _ = _add_product(barcode="rev1", price=5.0, stock_quantity=50)
    _scan(screen, barcode)
    screen._open_payment("cash")
    screen._reopen_ticket()

    original_row = screen._row_to_entry.index(0)
    screen.cart_table.selectRow(original_row)
    screen._remove_selected()

    assert len(screen.cart.entries) == 2
    original = screen.cart.entries[0]
    reversal = screen.cart.entries[1]
    assert original.has_reversal is True
    assert reversal.is_reversal is True
    assert reversal.quantity == -1


def test_reversal_capped_at_one_per_line(screen):
    pid, barcode, _ = _add_product(barcode="rev2", price=5.0, stock_quantity=50)
    _scan(screen, barcode)
    screen._open_payment("cash")
    screen._reopen_ticket()

    original_idx = 0
    screen.cart_table.selectRow(screen._row_to_entry.index(original_idx))
    screen._remove_selected()  # first reversal — ok
    assert len(screen.cart.entries) == 2

    # Select the (now capped) original again and try to reverse it a second time.
    screen.cart_table.selectRow(screen._row_to_entry.index(original_idx))
    screen._remove_selected()

    assert len(screen.cart.entries) == 2  # blocked — no second reversal appended


def test_removing_the_reversal_line_uncaps_the_original(screen):
    pid, barcode, _ = _add_product(barcode="rev3", price=5.0, stock_quantity=50)
    _scan(screen, barcode)
    screen._open_payment("cash")
    screen._reopen_ticket()

    screen.cart_table.selectRow(screen._row_to_entry.index(0))
    screen._remove_selected()  # creates reversal at index 1
    assert screen.cart.entries[0].has_reversal is True

    reversal_idx = 1
    screen.cart_table.selectRow(screen._row_to_entry.index(reversal_idx))
    screen._remove_selected()  # removes the reversal line itself

    assert len(screen.cart.entries) == 1
    assert screen.cart.entries[0].has_reversal is False


def test_repaying_a_reopened_ticket_overwrites_the_same_sale(screen):
    pid, barcode, _ = _add_product(barcode="rev4", price=5.0, stock_quantity=50)
    _scan(screen, barcode)
    screen._open_payment("cash")
    sale_id = screen._current_sale_id

    screen._reopen_ticket()
    screen._increase_product()  # quantity 1 -> 2, total now 10.0
    screen._open_payment("cash")

    assert screen._current_sale_id == sale_id
    with get_session() as session:
        assert session.query(Sale).filter_by(status="completed").count() == 1
        sale = session.query(Sale).filter_by(id=sale_id).first()
    assert sale.final_amount == 10.0


# ── Tab state persistence ────────────────────────────────────────────────

def test_switching_tabs_preserves_independent_carts(screen):
    pid, barcode, _ = _add_product(barcode="tab1", price=5.0)
    _scan(screen, barcode)
    assert len(screen.cart.entries) == 1

    screen.set_active_tab(2)
    assert screen.cart.entries == []  # fresh tab 2 cart

    pid2, barcode2, _ = _add_product(barcode="tab2", price=3.0)
    _scan(screen, barcode2)

    screen.set_active_tab(1)
    assert len(screen.cart.entries) == 1
    assert screen.cart.entries[0].product_barcode == "tab1"

    screen.set_active_tab(2)
    assert len(screen.cart.entries) == 1
    assert screen.cart.entries[0].product_barcode == "tab2"


def test_switching_to_same_tab_is_noop(screen):
    pid, barcode, _ = _add_product(barcode="tab3")
    _scan(screen, barcode)
    screen.set_active_tab(1)  # already active
    assert len(screen.cart.entries) == 1


# ── Sale browsing (previous/next) ────────────────────────────────────────

def test_previous_sale_with_no_sales_shows_overlay(screen):
    screen._previous_sale()
    assert not screen.overlay.isHidden()


def test_next_sale_when_on_latest_shows_overlay(screen):
    pid, barcode, _ = _add_product(barcode="nav1", price=5.0)
    _scan(screen, barcode)
    screen._open_payment("cash")  # first sale of the (fresh) day

    screen._next_sale()
    assert not screen.overlay.isHidden()


def test_previous_sale_loads_earlier_sale(screen):
    pid, barcode, _ = _add_product(barcode="nav2", price=5.0)
    _scan(screen, barcode)
    screen._open_payment("cash")
    first_sale_id = screen._current_sale_id

    screen._clear_cart(override=True)
    pid2, barcode2, _ = _add_product(barcode="nav3", price=7.0)
    _scan(screen, barcode2)
    screen._open_payment("cash")

    screen._previous_sale()

    assert screen._current_sale_id == first_sale_id
    assert screen.cart.entries[0].product_barcode == "nav2"


def test_browsing_blocked_while_sale_active(screen):
    pid, barcode, _ = _add_product(barcode="nav4", price=5.0)
    _scan(screen, barcode)  # active, unfinished sale

    screen._previous_sale()
    assert not screen.overlay.isHidden()


# ── Admin / navigation gating ─────────────────────────────────────────────

def test_admin_grants_admin_flag_and_emits_salesperson(screen, qtbot):
    with qtbot.waitSignal(screen.salesperson_changed, timeout=1000) as blocker:
        screen._admin()
    assert screen.isAdmin is True
    assert blocker.args == ["Admin"]


def test_reports_navigation_blocked_without_admin(screen):
    screen._emit_signal(4)
    assert not screen.overlay.isHidden()


def test_reports_navigation_allowed_for_admin(screen, qtbot):
    screen.isAdmin = True
    with qtbot.waitSignal(screen.navigate, timeout=1000) as blocker:
        screen._emit_signal(4)
    assert blocker.args == [4]


def test_articles_navigation_always_allowed(screen, qtbot):
    with qtbot.waitSignal(screen.navigate, timeout=1000) as blocker:
        screen._emit_signal(1)
    assert blocker.args == [1]
