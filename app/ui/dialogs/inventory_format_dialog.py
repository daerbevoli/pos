"""
Inventory Format Dialog
Picks the output format (PDF or CSV) for the inventory printout, the same way
ClientListingDialog does for the client listing. Nothing is generated here —
on OK the dialog exposes file_format for the caller.
"""
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QComboBox

from app.constants import INVENTORY_FORMAT_DIALOG_WIDTH
from app.utils.utils import FunctionButton

INVENTORY_FORMATS = (("PDF", "pdf"), ("CSV", "csv"))


class InventoryFormatDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Inventory")
        self.setMinimumWidth(INVENTORY_FORMAT_DIALOG_WIDTH)

        # Result of the dialog, read by the caller after exec().
        self.file_format: str | None = None

        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)

        form = QGridLayout()
        form.addWidget(QLabel("Format:"), 0, 0)
        self.format_combo = QComboBox()
        for label, value in INVENTORY_FORMATS:
            self.format_combo.addItem(label, value)
        form.addWidget(self.format_combo, 0, 1)
        form.setColumnStretch(1, 1)
        root.addLayout(form)

        # Heights come from the "QDialog QPushButton" rule in main.qss.
        btn_row = QHBoxLayout()
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        self.ok_btn = FunctionButton("OK", "okBtn")
        self.ok_btn.setDefault(True)
        self.ok_btn.clicked.connect(self.on_ok)
        btn_row.addWidget(self.cancel_btn, 1)
        btn_row.addWidget(self.ok_btn, 1)
        root.addLayout(btn_row)

    def on_ok(self):
        self.file_format = self.format_combo.currentData()
        self.accept()
