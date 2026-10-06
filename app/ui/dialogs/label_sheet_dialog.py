"""
Label Sheet Dialog
Used from the Inventory screen to fill in what goes on the barcode labels
(name, manufacturer, lot number, expiry date, barcode) and pick how many
labels fit on the A4 sheet before the PDF is generated.
"""
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QGridLayout, QFormLayout, QLabel, QLineEdit
from app.core.label_sheet_service import LABEL_LAYOUTS
from app.constants import DIALOG_BUTTON_HEIGHT, LABEL_SHEET_DIALOG_WIDTH, LABEL_SHEET_FIELD_HEIGHT, SPACING_XS
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
        layout.addLayout(form)

        self.error_label = QLabel("")
        self.error_label.hide()
        layout.addWidget(self.error_label)

        layout.addWidget(QLabel("Labels per page:"))
        grid = QGridLayout()
        grid.setSpacing(SPACING_XS)
        for i, count in enumerate(LABEL_LAYOUTS):
            cols, rows = LABEL_LAYOUTS[count]
            btn = FunctionButton(f"{count}\n({cols} × {rows})", "secFunc")
            btn.setMinimumHeight(DIALOG_BUTTON_HEIGHT)
            btn.clicked.connect(lambda _, n=count: self._choose(n))
            grid.addWidget(btn, i // 2, i % 2)
        layout.addLayout(grid)

        cancel_btn = FunctionButton("Cancel", "cancelBtn")
        cancel_btn.setMinimumHeight(DIALOG_BUTTON_HEIGHT)
        cancel_btn.clicked.connect(self.reject)
        layout.addWidget(cancel_btn)

    def _choose(self, count: int):
        if not self.barcode.text().strip():
            self.error_label.setText("A barcode is required.")
            self.error_label.show()
            self.barcode.setFocus()
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
