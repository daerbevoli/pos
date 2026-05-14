"""
Product Dialog
Add or edit a product.
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit,
    QPushButton, QHBoxLayout, QComboBox, QDoubleSpinBox, QMessageBox
)
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

        layout.addLayout(form)

        btn_row = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        save_btn = QPushButton("Save")
        save_btn.setObjectName("primaryBtn")
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

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
