"""
Shared form-field widgets used by inline/dialog product & article editing.
"""
from PyQt6.QtWidgets import QLabel, QFrame, QHBoxLayout
from PyQt6.QtCore import Qt

from app.constants import FORM_FIELD_HEIGHT, FORM_LABEL_WIDTH, SPACING_XS


class PickerDisplay(QLabel):
    """Focusable read-only label that shows the current value for picker fields."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setObjectName("pickerField")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(FORM_FIELD_HEIGHT)

    def mousePressEvent(self, event):
        self.setFocus()
        super().mousePressEvent(event)


class FieldRow(QFrame):
    """One form row: left label + right input widget. Highlights when active."""

    def __init__(self, label_text: str, widget, parent=None):
        super().__init__(parent)
        self.setObjectName("fieldRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 1, 4, 1)
        layout.setSpacing(SPACING_XS)

        lbl = QLabel(label_text)
        lbl.setObjectName("fieldLabel")
        lbl.setFixedWidth(FORM_LABEL_WIDTH)
        layout.addWidget(lbl)
        layout.addWidget(widget, 1)

    def set_active(self, active: bool):
        self.setProperty("active", active)
        self.style().unpolish(self)
        self.style().polish(self)
