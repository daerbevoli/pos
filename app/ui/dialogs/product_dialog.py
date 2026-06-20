"""
Product Dialog
Add or edit a product.
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLineEdit, QPushButton, QLabel, QDoubleSpinBox,
    QFrame, QMessageBox
)
from PyQt6.QtCore import Qt, QEvent

from app.core.database import get_session
from app.core.product_service import ProductService
from app.models.models import Product


class PickerDisplay(QLabel):
    """Focusable read-only label that shows the current value for picker fields."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setObjectName("pickerField")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(38)

    def mousePressEvent(self, event):
        self.setFocus()
        super().mousePressEvent(event)


class FieldRow(QFrame):
    """One form row: left label + right input widget. Highlights when active."""

    def __init__(self, label_text: str, widget, parent=None):
        super().__init__(parent)
        self.setObjectName("fieldRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(12)

        lbl = QLabel(label_text)
        lbl.setObjectName("fieldLabel")
        lbl.setFixedWidth(150)
        layout.addWidget(lbl)
        layout.addWidget(widget, 1)

    def set_active(self, active: bool):
        self.setProperty("active", active)
        self.style().unpolish(self)
        self.style().polish(self)


class ProductDialog(QDialog):
    def __init__(self, parent=None, product: Product = None):
        super().__init__(parent)
        self.product = product
        self.setWindowTitle("Edit Product" if product else "Add Product")
        self.setMinimumHeight(900)
        self.setMinimumWidth(1000)

        # Picker state
        self._tax_val = "0"
        self._unit_val = "pcs"
        self._category_id = None
        self._category_name = "— No Category —"
        self._categories: list[tuple[str, int]] = []

        self._active_row: FieldRow | None = None
        self._active_picker: str | None = None

        self._load_categories()
        self._build_ui()
        self._apply_styles()

        if product:
            self._populate(product)

    # ── Setup ─────────────────────────────────────────────────────────────────

    def _load_categories(self):
        with get_session() as session:
            cats = ProductService.get_all_categories(session)
            self._categories = [(c.name, c.id) for c in cats]

    def _build_ui(self):
        main = QVBoxLayout(self)
        main.setSpacing(4)
        main.setContentsMargins(0, 0, 0, 8)

        # ── Input widgets ──────────────────────────────────────────────
        self.barcode = QLineEdit()
        self.barcode.setPlaceholderText("Scan or type barcode")
        self.barcode.setMinimumHeight(38)

        self.name = QLineEdit()
        self.name.setMinimumHeight(38)

        self.price = QDoubleSpinBox()
        self.price.setPrefix("€ ")
        self.price.setMaximum(99999.99)
        self.price.setDecimals(2)
        self.price.setMinimumHeight(38)

        self.tax_display = PickerDisplay(f"{self._tax_val} %")

        self.stock = QDoubleSpinBox()
        self.stock.setMaximum(999999)
        self.stock.setDecimals(2)
        self.stock.setMinimumHeight(38)

        self.min_stock = QDoubleSpinBox()
        self.min_stock.setMaximum(999999)
        self.min_stock.setDecimals(2)
        self.min_stock.setValue(5)
        self.min_stock.setMinimumHeight(38)

        self.unit_display = PickerDisplay(self._unit_val)
        self.category_display = PickerDisplay(self._category_name)

        rows_spec = [
            ("Barcode",          self.barcode,          None),
            ("Name *",           self.name,             None),
            ("Selling Price *",  self.price,            None),
            ("Tax",              self.tax_display,      "tax"),
            ("Stock Quantity",   self.stock,            None),
            ("Min Stock Level",  self.min_stock,        None),
            ("Unit",             self.unit_display,     "unit"),
            ("Category",         self.category_display, "category"),
        ]

        self._fields = []
        self._row_map: dict = {}
        self._picker_map: dict = {}

        form_frame = QFrame()
        form_frame.setObjectName("formArea")
        form_layout = QVBoxLayout(form_frame)
        form_layout.setSpacing(2)
        form_layout.setContentsMargins(8, 8, 8, 4)

        for label_text, widget, picker_key in rows_spec:
            row = FieldRow(label_text, widget)
            form_layout.addWidget(row)
            self._fields.append(widget)
            self._row_map[widget] = row
            if picker_key:
                self._picker_map[widget] = picker_key
            widget.installEventFilter(self)

        main.addWidget(form_frame)

        # ── Nav buttons ────────────────────────────────────────────────
        nav_row = QHBoxLayout()
        nav_row.setContentsMargins(8, 0, 8, 0)
        up_btn = QPushButton("↑")
        down_btn = QPushButton("↓")
        for btn in (up_btn, down_btn):
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setFixedWidth(56)
            btn.setFixedHeight(32)
        up_btn.clicked.connect(lambda: self._navigate(-1))
        down_btn.clicked.connect(lambda: self._navigate(1))
        nav_row.addStretch()
        nav_row.addWidget(up_btn)
        nav_row.addWidget(down_btn)
        main.addLayout(nav_row)

        # ── Picker panel ───────────────────────────────────────────────
        self._picker_frame = QFrame()
        self._picker_frame.setObjectName("pickerPanel")
        self._picker_frame.setMinimumHeight(130)
        picker_vbox = QVBoxLayout(self._picker_frame)
        picker_vbox.setContentsMargins(10, 8, 10, 8)
        picker_vbox.setSpacing(6)

        self._picker_title = QLabel("")
        self._picker_title.setObjectName("pickerTitle")
        picker_vbox.addWidget(self._picker_title)

        self._picker_grid = QGridLayout()
        self._picker_grid.setSpacing(6)
        picker_vbox.addLayout(self._picker_grid)
        picker_vbox.addStretch()

        main.addWidget(self._picker_frame)

        # ── Save / Cancel ──────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(8, 4, 8, 4)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setMinimumHeight(40)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        save_btn = QPushButton("Save")
        save_btn.setObjectName("primaryBtn")
        save_btn.setMinimumHeight(40)
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)

        main.addLayout(btn_row)

    def _apply_styles(self):
        self.setStyleSheet("""

        """)

    # ── Event filter (focus tracking + keyboard nav) ───────────────────────

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.FocusIn:
            if self._active_row:
                self._active_row.set_active(False)
            row = self._row_map.get(obj)
            if row:
                self._active_row = row
                row.set_active(True)
            self._refresh_picker(self._picker_map.get(obj))

        elif event.type() == QEvent.Type.KeyPress:
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

    # ── Picker panel ───────────────────────────────────────────────────────

    def _refresh_picker(self, picker_key: str | None):
        self._active_picker = picker_key

        while self._picker_grid.count():
            item = self._picker_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if picker_key is None:
            self._picker_title.setText("")
            return

        titles = {"tax": "Tax Rate", "unit": "Unit", "category": "Category"}
        self._picker_title.setText(titles[picker_key])

        if picker_key == "tax":
            options = [("0 %", "0"), ("6 %", "6"), ("12 %", "12"), ("21 %", "21")]
            current = self._tax_val
            cols = 4
        elif picker_key == "unit":
            options = [(v, v) for v in ["pcs", "kg", "g", "liter", "ml", "pack", "box"]]
            current = self._unit_val
            cols = 4
        else:  # category
            options = [("— None —", None)] + [(name, cid) for name, cid in self._categories]
            current = self._category_id
            cols = 3

        for i, (label, value) in enumerate(options):
            btn = QPushButton(label)
            btn.setObjectName("pickerBtn")
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setProperty("selected", value == current)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.clicked.connect(lambda _, v=value, l=label: self._pick(v, l))
            self._picker_grid.addWidget(btn, i // cols, i % cols)

    def _pick(self, value, label: str):
        if self._active_picker == "tax":
            self._tax_val = value
            self.tax_display.setText(f"{value} %")
        elif self._active_picker == "unit":
            self._unit_val = value
            self.unit_display.setText(value)
        elif self._active_picker == "category":
            self._category_id = value
            self._category_name = label
            self.category_display.setText(label)
        self._refresh_picker(self._active_picker)

    # ── Populate / save ────────────────────────────────────────────────────

    def _populate(self, p: Product):
        self.barcode.setText(p.barcode or "")
        self.name.setText(p.name)
        self.price.setValue(p.price)
        self.stock.setValue(p.stock_quantity)
        self.min_stock.setValue(p.min_stock_level)

        self._tax_val = str(p.tax)
        self.tax_display.setText(f"{p.tax} %")

        self._unit_val = p.unit
        self.unit_display.setText(p.unit)

        self._category_id = p.category_id
        if p.category_id:
            for name, cid in self._categories:
                if cid == p.category_id:
                    self._category_name = name
                    break
        self.category_display.setText(self._category_name)

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
            "tax": int(self._tax_val),
            "stock_quantity": self.stock.value(),
            "min_stock_level": self.min_stock.value(),
            "unit": self._unit_val,
            "category_id": self._category_id,
        }
