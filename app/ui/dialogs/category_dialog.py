from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLineEdit, QLabel, QHBoxLayout, QMessageBox, QPushButton, QGridLayout
)

from app.constants import BUTTON_HEIGHT
from app.utils.utils import FunctionButton


class CategoryDialog(QDialog):

    def __init__(self, parent=None, cat_name: str = "", existing_names=None):
        super().__init__(parent)
        self.setWindowTitle("Category")
        self.setFixedSize(400, 200)

        self._existing = {n.strip().lower() for n in (existing_names or [])}
        self._original = cat_name.strip().lower()
        self.cat_name = ""

        self.line_edit = QLineEdit()
        self.line_edit.setText(cat_name)
        self.line_edit.returnPressed.connect(self.on_ok)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setFixedHeight(BUTTON_HEIGHT)
        self.cancel_btn.clicked.connect(self.on_cancel)

        self.ok_btn = FunctionButton("OK", "okBtn")
        self.ok_btn.setFixedHeight(BUTTON_HEIGHT)
        self.ok_btn.clicked.connect(self.on_ok)

        label = QLabel("Choose name: ")

        layoutV = QVBoxLayout(self)
        layoutH = QHBoxLayout()
        layoutV.addWidget(label)
        layoutV.addLayout(layoutH)

        layout_ok_cancel = QHBoxLayout()
        layoutH.addWidget(self.line_edit)
        layout_ok_cancel.addWidget(self.cancel_btn)
        layout_ok_cancel.addWidget(self.ok_btn)
        layoutV.addLayout(layout_ok_cancel)

    def on_ok(self):
        name = self.line_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Category", "Name cannot be empty.")
            return
        if name.lower() != self._original and name.lower() in self._existing:
            QMessageBox.warning(self, "Category", f"“{name}” already exists.")
            return
        self.cat_name = name
        self.accept()

    def on_cancel(self):
        self.hide()
