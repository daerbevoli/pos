"""
Client Listing Dialog
Picks the date range and output format (PDF or CSV) for the client listing.
Nothing is generated here — on OK the dialog exposes start_date/end_date/
file_format for the caller to pass to ClientListingService.
"""
from datetime import date

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QDateEdit, QComboBox, QMessageBox,
)
from PyQt6.QtCore import QDate

from app.constants import DIALOG_BUTTON_HEIGHT
from app.utils.utils import FunctionButton

LISTING_FORMATS = (("PDF", "pdf"), ("CSV", "csv"))


class ClientListingDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Client Listing")

        # Result of the dialog, read by the caller after exec().
        self.start_date: date | None = None
        self.end_date: date | None = None
        self.file_format = "pdf"

        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)

        form = QGridLayout()
        today = QDate.currentDate()

        form.addWidget(QLabel("Start date:"), 0, 0)
        self.start_edit = QDateEdit(QDate(today.year(), 1, 1))
        self.start_edit.setCalendarPopup(True)
        self.start_edit.setDisplayFormat("dd-MM-yyyy")
        form.addWidget(self.start_edit, 0, 1)

        form.addWidget(QLabel("End date:"), 1, 0)
        self.end_edit = QDateEdit(today)
        self.end_edit.setCalendarPopup(True)
        self.end_edit.setDisplayFormat("dd-MM-yyyy")
        form.addWidget(self.end_edit, 1, 1)

        form.addWidget(QLabel("Format:"), 2, 0)
        self.format_combo = QComboBox()
        for label, value in LISTING_FORMATS:
            self.format_combo.addItem(label, value)
        form.addWidget(self.format_combo, 2, 1)

        root.addLayout(form)

        btn_row = QHBoxLayout()
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setFixedHeight(DIALOG_BUTTON_HEIGHT)
        self.cancel_btn.clicked.connect(self.reject)
        self.ok_btn = FunctionButton("OK", "okBtn")
        self.ok_btn.setFixedHeight(DIALOG_BUTTON_HEIGHT)
        self.ok_btn.clicked.connect(self.on_ok)
        btn_row.addStretch()
        btn_row.addWidget(self.cancel_btn)
        btn_row.addWidget(self.ok_btn)
        root.addLayout(btn_row)

    def on_ok(self):
        start = self.start_edit.date().toPyDate()
        end = self.end_edit.date().toPyDate()
        if start > end:
            QMessageBox.warning(self, "Client Listing", "Start date must be on or before the end date.")
            return
        self.start_date = start
        self.end_date = end
        self.file_format = self.format_combo.currentData()
        self.accept()
