"""
Tests for the small standalone dialogs: NumpadDialog and FileDialog.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QPushButton

from app.ui.dialogs.numpad_dialog import NumpadDialog
from app.ui.dialogs.file_dialog import FileDialog


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
