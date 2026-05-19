"""
Product Dialog
Add or edit a product.
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit,
    QPushButton, QHBoxLayout, QComboBox, QDoubleSpinBox, QMessageBox
)
from PyQt6.QtCore import Qt, QEvent

from app.core.database import get_session
from app.core.product_service import ProductService
from app.models.models import Product


class ProductDialog(QDialog):
    def __init__(self, parent=None, product: Product = None):
        super().__init__(parent)
        self.product = product
        self.setWindowTitle("Edit Product" if product else "Add Product")
        self.setMinimumWidth(480)
        self._build_ui()
        if product:
            self._populate(product)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.barcode = QLineEdit()
        self.barcode.setPlaceholderText("Scan or type barcode")
        form.addRow("Barcode:", self.barcode)

        self.name = QLineEdit()
        form.addRow("Name *:", self.name)

        self.price = QDoubleSpinBox()
        self.price.setPrefix("€ ")
        self.price.setMaximum(99999.99)
        self.price.setDecimals(2)
        form.addRow("Selling Price *:", self.price)

        self.tax = QComboBox()
        self.tax.addItems(['0 %', '6 %', '12 %', '21 %'])
        form.addRow("Tax :", self.tax)

        self.stock = QDoubleSpinBox()
        self.stock.setMaximum(999999)
        self.stock.setDecimals(2)
        form.addRow("Stock Quantity:", self.stock)

        self.min_stock = QDoubleSpinBox()
        self.min_stock.setMaximum(999999)
        self.min_stock.setDecimals(2)
        self.min_stock.setValue(5)
        form.addRow("Min Stock Level:", self.min_stock)

        self.unit = QComboBox()
        self.unit.addItems(["pcs", "kg", "g", "liter", "ml", "pack", "box"])
        form.addRow("Unit:", self.unit)

        self.category = QComboBox()
        self.category.addItem("— No Category —", None)
        with get_session() as session:
            cats = ProductService.get_all_categories(session)
            for cat in cats:
                self.category.addItem(cat.name, cat.id)
        form.addRow("Category:", self.category)

        self._fields = [
            self.barcode, self.name, self.price, self.tax,
            self.stock, self.min_stock, self.unit, self.category,
        ]
        for field in self._fields:
            field.installEventFilter(self)

        up_btn = QPushButton("↑")
        down_btn = QPushButton("↓")
        up_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        down_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        up_btn.clicked.connect(lambda: self._navigate(-1))
        down_btn.clicked.connect(lambda: self._navigate(1))

        up_down_col = QVBoxLayout()
        up_down_col.addStretch()
        up_down_col.addWidget(up_btn)
        up_down_col.addWidget(down_btn)
        up_down_col.addStretch()

        form_row = QHBoxLayout()
        form_row.addLayout(form)
        form_row.addLayout(up_down_col)
        layout.addLayout(form_row)

        btn_row = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        save_btn = QPushButton("Save")
        save_btn.setObjectName("primaryBtn")
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Up:
                self._navigate(-1)
                return True
            elif key == Qt.Key.Key_Down:
                self._navigate(1)
                return True
        return super().eventFilter(obj, event)

    def _navigate(self, direction: int):
        focused = self.focusWidget()
        idx = self._fields.index(focused) if focused in self._fields else 0
        self._fields[(idx + direction) % len(self._fields)].setFocus()

    def _populate(self, p: Product):
        self.barcode.setText(p.barcode or "")
        self.name.setText(p.name)
        self.price.setValue(p.price)
        self.stock.setValue(p.stock_quantity)
        self.min_stock.setValue(p.min_stock_level)
        unit_idx = self.unit.findText(p.unit)
        if unit_idx >= 0:
            self.unit.setCurrentIndex(unit_idx)
        if p.category_id:
            cat_idx = self.category.findData(p.category_id)
            if cat_idx >= 0:
                self.category.setCurrentIndex(cat_idx)

    def _save(self):
        if not self.name.text().strip():
            QMessageBox.warning(self, "Validation", "Product name is required.")
            return
        if self.price.value() <= 0:
            QMessageBox.warning(self, "Validation", "Price must be greater than zero.")
            return
        self.accept()

    def get_data(self) -> dict:
        return {
            "barcode": self.barcode.text().strip() or None,
            "name": self.name.text().strip(),
            "price": self.price.value(),
            "tax": self.tax.currentText(),
            "stock_quantity": self.stock.value(),
            "min_stock_level": self.min_stock.value(),
            "unit": self.unit.currentText(),
            "category_id": self.category.currentData(),
        }
