"""
Label Sheet Dialog
Used from the Inventory screen to fill in what goes on the barcode labels
(name, manufacturer, lot number, expiry date, barcode) and pick how many
labels fit on the A4 sheet (a dropdown, empty until chosen) before the PDF is
generated. OK confirms.
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit, QComboBox,
)
from app.core.label_sheet_service import LABEL_LAYOUTS
from app.constants import LABEL_SHEET_DIALOG_WIDTH, LABEL_SHEET_FIELD_HEIGHT
from app.utils.utils import FunctionButton


class LabelSheetDialog(QDialog):
    def __init__(self, name: str, barcode: str, parent=None):
        super().__init__(parent)
        self.labels_per_page = None
        self.setWindowTitle("Print barcodes")
        self.setMinimumWidth(LABEL_SHEET_DIALOG_WIDTH)
        self._build_ui(name, barcode)

    def _build_ui(self, name: str, barcode: str):
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.name = QLineEdit(name)
        self.manufacturer = QLineEdit()
        self.lot_number = QLineEdit()
        self.expiry_date = QLineEdit()
        self.expiry_date.setPlaceholderText("dd/mm/yyyy")
        self.barcode = QLineEdit(barcode)
        for label, field in (
            ("Name:", self.name),
            ("Manufacturer:", self.manufacturer),
            ("Lot number:", self.lot_number),
            ("Expiry date:", self.expiry_date),
            ("Barcode:", self.barcode),
        ):
            field.setMinimumHeight(LABEL_SHEET_FIELD_HEIGHT)
            form.addRow(label, field)

        # No preselection, so OK can't print a sheet nobody chose.
        self.layout_combo = QComboBox()
        self.layout_combo.setPlaceholderText("Choose…")
        for count, (cols, rows) in LABEL_LAYOUTS.items():
            self.layout_combo.addItem(f"{count}  ({cols} × {rows})", count)
        self.layout_combo.setCurrentIndex(-1)
        self.layout_combo.setMinimumHeight(LABEL_SHEET_FIELD_HEIGHT)
        form.addRow("Labels per page:", self.layout_combo)
        layout.addLayout(form)

        self.error_label = QLabel("")
        self.error_label.hide()
        layout.addWidget(self.error_label)
        self.layout_combo.currentIndexChanged.connect(self.error_label.hide)

        btn_row = QHBoxLayout()
        self.cancel_btn = FunctionButton("Cancel", "cancelBtn")
        self.cancel_btn.clicked.connect(self.reject)
        self.ok_btn = FunctionButton("OK", "okBtn")
        self.ok_btn.clicked.connect(self.on_ok)
        btn_row.addWidget(self.cancel_btn, 1)
        btn_row.addWidget(self.ok_btn, 1)
        layout.addLayout(btn_row)

    def _show_error(self, text: str):
        self.error_label.setText(text)
        self.error_label.show()

    def on_ok(self):
        if not self.barcode.text().strip():
            self._show_error("A barcode is required.")
            self.barcode.setFocus()
            return
        count = self.layout_combo.currentData()  # None while the placeholder shows
        if count not in LABEL_LAYOUTS:
            self._show_error("Choose how many labels per page.")
            return
        self.labels_per_page = count
        self.accept()

    def get_data(self) -> dict:
        """Label contents, as keyword arguments for build_label_sheet_pdf()."""
        return {
            "name": self.name.text().strip(),
            "manufacturer": self.manufacturer.text().strip(),
            "lot_number": self.lot_number.text().strip(),
            "expiry_date": self.expiry_date.text().strip(),
            "barcode": self.barcode.text().strip(),
        }
