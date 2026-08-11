"""
Tests for the small standalone dialogs: NumpadDialog, PaymentDialog,
StockAdjustmentDialog, FileDialog.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QPushButton

from app.ui.dialogs.numpad_dialog import NumpadDialog
from app.ui.dialogs.payment_dialog import PaymentDialog
from app.ui.dialogs.stock_adjustment_dialog import StockAdjustmentDialog
from app.ui.dialogs.file_dialog import FileDialog
from app.core.sales_service import Cart, CartItem


# ── NumpadDialog ─────────────────────────────────────────────────────────

def test_numpad_dialog_initial_value(qtbot):
    dlg = NumpadDialog(initial="5.00")
    qtbot.addWidget(dlg)
    assert dlg.display.text() == "5.00"


def test_numpad_dialog_press_appends_digits(qtbot):
    dlg = NumpadDialog()
    qtbot.addWidget(dlg)
    dlg._press("1")
    dlg._press("2")
    assert dlg.display.text() == "12"


def test_numpad_dialog_only_one_decimal_point(qtbot):
    dlg = NumpadDialog()
    qtbot.addWidget(dlg)
    dlg._press("1")
    dlg._press(".")
    dlg._press("5")
    dlg._press(".")
    assert dlg.display.text() == "1.5"


def test_numpad_dialog_backspace_removes_last_char(qtbot):
    dlg = NumpadDialog(initial="123")
    qtbot.addWidget(dlg)
    dlg._press("⌫")
    assert dlg.display.text() == "12"


def test_numpad_dialog_confirm_sets_value_and_accepts(qtbot):
    dlg = NumpadDialog(initial="42")
    qtbot.addWidget(dlg)
    dlg._confirm()
    assert dlg.value == "42"
    assert dlg.result() == QDialog.DialogCode.Accepted


def test_numpad_dialog_enter_key_confirms(qtbot):
    dlg = NumpadDialog(initial="9")
    qtbot.addWidget(dlg)

    from PyQt6.QtGui import QKeyEvent
    from PyQt6.QtCore import QEvent
    dlg.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier))

    assert dlg.value == "9"
    assert dlg.result() == QDialog.DialogCode.Accepted


def test_numpad_dialog_cancel_rejects(qtbot):
    dlg = NumpadDialog()
    qtbot.addWidget(dlg)
    cancel_btn = next(b for b in dlg.findChildren(QPushButton) if b.text() == "Cancel")
    cancel_btn.click()
    assert dlg.result() == QDialog.DialogCode.Rejected


# ── PaymentDialog ────────────────────────────────────────────────────────

def _cart_with_total(total: float) -> Cart:
    return Cart(entries=[
        CartItem(product_id=1, product_name="X", product_barcode="1", unit_price=total, quantity=1)
    ])


def test_payment_dialog_cash_defaults_to_exact_amount(qtbot):
    cart = _cart_with_total(15.0)
    dlg = PaymentDialog(cart, "cash", "€")
    qtbot.addWidget(dlg)
    assert dlg.tendered_input.text() == "15.00"
    assert dlg.change_label.text() == "Change: €0.00"


def test_payment_dialog_cash_shows_change_for_overpayment(qtbot):
    cart = _cart_with_total(10.0)
    dlg = PaymentDialog(cart, "cash", "€")
    qtbot.addWidget(dlg)
    dlg.tendered_input.setText("20.00")
    assert dlg.change_label.text() == "Change: €10.00"


def test_payment_dialog_cash_shows_insufficient_warning(qtbot):
    cart = _cart_with_total(10.0)
    dlg = PaymentDialog(cart, "cash", "€")
    qtbot.addWidget(dlg)
    dlg.tendered_input.setText("5.00")
    assert "Insufficient" in dlg.change_label.text()
    assert "5.00" in dlg.change_label.text()


def test_payment_dialog_cash_invalid_input_shows_dash(qtbot):
    cart = _cart_with_total(10.0)
    dlg = PaymentDialog(cart, "cash", "€")
    qtbot.addWidget(dlg)
    dlg.tendered_input.setText("abc")
    assert dlg.change_label.text() == "Change: —"


def test_payment_dialog_quick_cash_button_sets_amount(qtbot):
    cart = _cart_with_total(10.0)
    dlg = PaymentDialog(cart, "cash", "€")
    qtbot.addWidget(dlg)
    dlg._set_tendered(20)
    assert dlg.tendered_input.text() == "20.00"


def test_payment_dialog_confirm_blocks_underpayment(qtbot):
    cart = _cart_with_total(10.0)
    dlg = PaymentDialog(cart, "cash", "€")
    qtbot.addWidget(dlg)
    dlg.tendered_input.setText("5.00")
    dlg._confirm()
    assert dlg.result() != QDialog.DialogCode.Accepted


def test_payment_dialog_confirm_accepts_exact_or_over_payment(qtbot):
    cart = _cart_with_total(10.0)
    dlg = PaymentDialog(cart, "cash", "€")
    qtbot.addWidget(dlg)
    dlg.tendered_input.setText("10.00")
    dlg._confirm()
    assert dlg.result() == QDialog.DialogCode.Accepted
    assert dlg.amount_tendered == 10.0


def test_payment_dialog_confirm_invalid_text_does_not_accept(qtbot):
    cart = _cart_with_total(10.0)
    dlg = PaymentDialog(cart, "cash", "€")
    qtbot.addWidget(dlg)
    dlg.tendered_input.setText("not a number")
    dlg._confirm()
    assert dlg.result() != QDialog.DialogCode.Accepted


def test_payment_dialog_card_method_has_no_tendered_input(qtbot):
    cart = _cart_with_total(10.0)
    dlg = PaymentDialog(cart, "card", "€")
    qtbot.addWidget(dlg)
    assert not hasattr(dlg, "tendered_input")


def test_payment_dialog_card_confirm_always_accepts(qtbot):
    cart = _cart_with_total(10.0)
    dlg = PaymentDialog(cart, "card", "€")
    qtbot.addWidget(dlg)
    dlg._confirm()
    assert dlg.result() == QDialog.DialogCode.Accepted


# ── StockAdjustmentDialog ────────────────────────────────────────────────

class _FakeProduct:
    def __init__(self):
        self.name = "Widget"
        self.stock_quantity = 10.0
        self.unit = "pcs"


def test_stock_adjustment_dialog_positive_direction(qtbot):
    dlg = StockAdjustmentDialog(_FakeProduct())
    qtbot.addWidget(dlg)
    dlg.quantity.setValue(5)
    dlg.direction.setCurrentIndex(0)  # Add to stock (+)
    dlg.movement_type.setCurrentText("purchase")

    data = dlg.get_data()
    assert data["quantity_change"] == 5
    assert data["movement_type"] == "purchase"
    assert data["notes"] is None


def test_stock_adjustment_dialog_negative_direction(qtbot):
    dlg = StockAdjustmentDialog(_FakeProduct())
    qtbot.addWidget(dlg)
    dlg.quantity.setValue(3)
    dlg.direction.setCurrentIndex(1)  # Remove from stock (-)

    data = dlg.get_data()
    assert data["quantity_change"] == -3


def test_stock_adjustment_dialog_notes_stripped(qtbot):
    dlg = StockAdjustmentDialog(_FakeProduct())
    qtbot.addWidget(dlg)
    dlg.notes.setText("   delivery from ACME   ")

    data = dlg.get_data()
    assert data["notes"] == "delivery from ACME"


def test_stock_adjustment_dialog_title_includes_product_name(qtbot):
    dlg = StockAdjustmentDialog(_FakeProduct())
    qtbot.addWidget(dlg)
    assert "Widget" in dlg.windowTitle()


# ── FileDialog ───────────────────────────────────────────────────────────

def test_file_dialog_on_ok_rejects_nonexistent_path(qtbot):
    dlg = FileDialog()
    qtbot.addWidget(dlg)
    dlg.line_edit.setText("Z:\\does\\not\\exist.csv")
    dlg.on_ok()
    assert dlg.path is None
    assert dlg.result() != QDialog.DialogCode.Accepted


def test_file_dialog_on_ok_accepts_existing_file(qtbot, tmp_path):
    f = tmp_path / "clients.csv"
    f.write_text("name,vat\n")

    dlg = FileDialog()
    qtbot.addWidget(dlg)
    dlg.line_edit.setText(str(f))
    dlg.on_ok()

    assert dlg.path == str(f)
    assert dlg.result() == QDialog.DialogCode.Accepted
