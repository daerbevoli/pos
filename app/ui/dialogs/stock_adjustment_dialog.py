"""
Stock Adjustment Dialog
Used from the Inventory screen to add/remove/correct stock.
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLabel,
    QDoubleSpinBox, QComboBox, QLineEdit,
    QPushButton, QHBoxLayout
)
from app.models.models import Product


class StockAdjustmentDialog(QDialog):
    def __init__(self, product: Product, parent=None):
        super().__init__(parent)
        self.product = product
        self.setWindowTitle(f"Stock Adjustment — {product.name}")
        self.setMinimumWidth(420)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        current_label = QLabel(f"{self.product.stock_quantity:.2f} {self.product.unit}")
        form.addRow("Current Stock:", current_label)

        self.movement_type = QComboBox()
        self.movement_type.addItems(["purchase", "adjustment", "return", "waste"])
        form.addRow("Reason:", self.movement_type)

        self.quantity = QDoubleSpinBox()
        self.quantity.setMaximum(999999)
        self.quantity.setDecimals(2)
        self.quantity.setValue(1)
        form.addRow("Quantity:", self.quantity)

        self.direction = QComboBox()
        self.direction.addItems(["Add to stock (+)", "Remove from stock (-)"])
        form.addRow("Direction:", self.direction)

        self.notes = QLineEdit()
        self.notes.setPlaceholderText("Optional note (e.g. delivery from supplier)")
        form.addRow("Notes:", self.notes)

        layout.addLayout(form)

        btn_row = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        confirm_btn = QPushButton("Apply")
        confirm_btn.setObjectName("primaryBtn")
        confirm_btn.clicked.connect(self.accept)
        btn_row.addWidget(confirm_btn)
        layout.addLayout(btn_row)

    def get_data(self) -> dict:
        qty = self.quantity.value()
        if self.direction.currentIndex() == 1:
            qty = -qty
        return {
            "quantity_change": qty,
            "movement_type": self.movement_type.currentText(),
            "notes": self.notes.text().strip() or None,
        }
