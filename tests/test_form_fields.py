"""Tests for app.ui.widgets.form_fields: PickerDisplay and FieldRow."""
from PyQt6.QtCore import Qt, QEvent, QPointF
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QLineEdit

from app.ui.widgets.form_fields import PickerDisplay, FieldRow


def test_picker_display_defaults(qtbot):
    picker = PickerDisplay("kg")
    qtbot.addWidget(picker)

    assert picker.text() == "kg"
    assert picker.objectName() == "pickerField"
    assert picker.focusPolicy() == Qt.FocusPolicy.StrongFocus


def test_picker_display_mouse_press_takes_focus(qtbot):
    picker = PickerDisplay("kg")
    qtbot.addWidget(picker)
    picker.show()

    event = QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(picker.rect().center()),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    picker.mousePressEvent(event)

    assert picker.hasFocus() or picker.focusWidget() is picker


def test_field_row_lays_out_label_and_widget(qtbot):
    widget = QLineEdit()
    row = FieldRow("Name", widget)
    qtbot.addWidget(row)

    assert row.objectName() == "fieldRow"
    assert row.layout().count() == 2


def test_field_row_set_active_updates_property(qtbot):
    widget = QLineEdit()
    row = FieldRow("Name", widget)
    qtbot.addWidget(row)

    row.set_active(True)
    assert row.property("active") is True

    row.set_active(False)
    assert row.property("active") is False
