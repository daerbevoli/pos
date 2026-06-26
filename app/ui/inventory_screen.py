"""
Inventory Screen
Table list of products on top; selecting a row opens an "Artikel
selecteren"-style detail panel below, with a field list on the left and a
function-key grid on the right (New/Modify/Delete article, Price label,
Shelf label, Pre-pack, Print shelf, Search by barcode/key, OK/Cancel).
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QLabel,
    QHeaderView, QMessageBox, QComboBox, QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal

from app.core.database import get_session
from app.core.product_service import ProductService
from app.ui.dialogs.product_dialog import ProductDialog
from app.ui.dialogs.stock_adjustment_dialog import StockAdjustmentDialog


class DetailFunctionButton(QPushButton):
    """A function key in the article-detail panel's right-hand grid."""
    def __init__(self, label: str, role: str = "secFunc"):
        super().__init__(label)
        self.setObjectName(role)
        self.setMinimumHeight(50)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)


class ArticleDetailPanel(QFrame):
    """
    "Detail view for a single product:
    a field list on the left, a function-key grid on the right.
    Hidden until a row is selected in the table above it.
    """
    def __init__(self, parent_screen):
        super().__init__(parent_screen)
        self.parent_screen = parent_screen
        self.current_product_id = None
        self.setObjectName("articleDetailPanel")
        self._build_ui()

    def _build_ui(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        # ── Left: field list ────────────────────────────────────────────
        field_frame = QFrame()
        field_frame.setObjectName("articleFieldFrame")
        field_col = QVBoxLayout(field_frame)
        field_col.setSpacing(10)

        title = QLabel("Select article")
        title.setObjectName("articleDetailTitle")
        field_col.addWidget(title)

        self.field_labels = {}
        field_names = [
            ("name", "Name:"),
            ("department", "Department:"),
            ("unit", "Unit:"),
            ("price", "Price:"),
            ("barcode", "Barcode:"),
            ("active", "Active:"),
            ("stock", "Stock:")
        ]
        for key, caption in field_names:
            row = QHBoxLayout()
            cap_label = QLabel(caption)
            cap_label.setObjectName("articleFieldCaption")
            cap_label.setFixedWidth(120)
            value_label = QLabel("—")
            value_label.setObjectName("articleFieldValue")
            row.addWidget(cap_label)
            row.addWidget(value_label, stretch=1)
            field_col.addLayout(row)
            self.field_labels[key] = value_label

        field_col.addStretch()
        outer.addWidget(field_frame, stretch=3)

        # ── Right: function-key grid ────────────────────────────────────
        grid = QGridLayout()
        grid.setSpacing(4)

        self.btn_new = DetailFunctionButton("New\narticle", "newArticleBtn")
        self.btn_modify = DetailFunctionButton("Modify\narticle", "secFunc")
        self.btn_delete = DetailFunctionButton("Delete\narticle", "deleteArticleBtn")
        self.btn_error = DetailFunctionButton("Error", "errorBtn")

        self.btn_print_label = DetailFunctionButton("Print\nlabel", "secFunc")
        self.btn_cancel = DetailFunctionButton("Cancel", "cancelBtn")

        self.btn_search_barcode = DetailFunctionButton("Search by\nbarcode", "secFunc")
        self.btn_search_key = DetailFunctionButton("Search by\nkey", "secFunc")
        self.btn_ok = DetailFunctionButton("OK", "okBtn")

        layout_map = [
            (self.btn_new, 0, 0), (self.btn_modify, 0, 1),
            (self.btn_delete, 0, 2), (self.btn_error, 0, 3),

            (self.btn_search_barcode, 1, 1),
            (self.btn_search_key, 1, 2), (self.btn_ok, 1, 3),

            (self.btn_cancel, 2, 3)
        ]
        for widget, r, c in layout_map:
            grid.addWidget(widget, r, c)

        for c in range(4):
            grid.setColumnStretch(c, 1)
        for r in range(5):
            grid.setRowStretch(r, 1)

        outer.addLayout(grid, stretch=4)

        # Wire actions to the parent screen's existing service calls
        self.btn_new.clicked.connect(self.parent_screen._add_product)
        self.btn_modify.clicked.connect(self._on_modify)
        self.btn_delete.clicked.connect(self._on_delete)
        self.btn_error.clicked.connect(self._clear)
        self.btn_cancel.clicked.connect(self._clear)
        self.btn_ok.clicked.connect(self._clear)
        self.btn_search_barcode.clicked.connect(self._on_search_barcode)
        self.btn_search_key.clicked.connect(self._on_search_key)

    # ── Display ──────────────────────────────────────────────────────────

    def _clear(self):
        if self.current_product_id is not None:
            self.current_product_id = None
            for label in self.field_labels.values():
                label.setText("—")


    def show_product(self, product):
        self.current_product_id = product.id
        self.field_labels["name"].setText(product.name or "—")
        dept = product.category.name if getattr(product, "category", None) else "—"
        self.field_labels["department"].setText(dept)
        self.field_labels["unit"].setText(product.unit or "—")
        self.field_labels["price"].setText(f"€{product.price:.2f}")
        self.field_labels["barcode"].setText(product.barcode or "—")
        is_active = getattr(product, "is_active", True)
        self.field_labels["active"].setText("Yes" if is_active else "No")
        self.field_labels["stock"].setText(str(product.stock_quantity))
        self.show()

    # ── Actions ──────────────────────────────────────────────────────────

    def _on_modify(self):
        if self.current_product_id is None:
            return
        self.parent_screen._edit_product(self.current_product_id)

    def _on_delete(self):
        if self.current_product_id is None:
            return
        self.parent_screen._delete_product(self.current_product_id)
        self.hide()

    def _on_search_barcode(self):
        self.parent_screen.search_input.setFocus()
        self.parent_screen.search_input.setPlaceholderText("Scan or type barcode…")

    def _on_search_key(self):
        self.parent_screen.search_input.setFocus()
        self.parent_screen.search_input.setPlaceholderText("Search by name or barcode…")

    def _stub_action(self, label: str):
        QMessageBox.information(self, label, f"{label} — coming soon.")


class InventoryScreen(QWidget):
    navigate = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # ── Article detail panel (always visible) ─────────────────────────────
        self.detail_panel = ArticleDetailPanel(self)
        layout.addWidget(self.detail_panel)

        # ── Search / filter bar ───────────────────────────────────────────────
        toolbar = QHBoxLayout()

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search by name or barcode…")
        self.search_input.setFixedHeight(44)
        self.search_input.textChanged.connect(self.refresh)
        toolbar.addWidget(self.search_input, stretch=2)

        self.category_filter = QComboBox()
        self.category_filter.setFixedHeight(44)
        self.category_filter.addItem("All Categories", None)
        self.category_filter.currentIndexChanged.connect(self.refresh)
        toolbar.addWidget(self.category_filter)

        self.low_stock_btn = QPushButton("Low Stock")
        self.low_stock_btn.setCheckable(True)
        self.low_stock_btn.setFixedHeight(44)
        self.low_stock_btn.toggled.connect(self.refresh)
        toolbar.addWidget(self.low_stock_btn)

        add_btn = QPushButton("＋ Add Product")
        add_btn.setObjectName("primaryBtn")
        add_btn.setFixedHeight(44)
        add_btn.clicked.connect(self._add_product)
        toolbar.addWidget(add_btn)

        layout.addLayout(toolbar)

        # ── Product table ─────────────────────────────────────────────────────
        self.table = QTableWidget(0, 8)
        self.table.setObjectName("inventoryTable")
        self.table.setHorizontalHeaderLabels([
            "Barcode", "Name", "Category", "Price", "Tax", "Stock", "Unit", "Actions"
        ])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        layout.addWidget(self.table, stretch=1)

        # ── Summary row ───────────────────────────────────────────────────────
        self.summary_label = QLabel()
        layout.addWidget(self.summary_label)

        self._product_cache = {}

    def refresh(self):
        with get_session() as session:
            # Refresh category filter
            cats = ProductService.get_all_categories(session)
            current_cat = self.category_filter.currentData()
            self.category_filter.blockSignals(True)
            self.category_filter.clear()
            self.category_filter.addItem("All Categories", None)
            for cat in cats:
                self.category_filter.addItem(cat.name, cat.id)
            if current_cat:
                idx = self.category_filter.findData(current_cat)
                if idx >= 0:
                    self.category_filter.setCurrentIndex(idx)
            self.category_filter.blockSignals(False)

            # Get products
            query = self.search_input.text().strip()
            if query:
                products = ProductService.search(session, query)
            else:
                products = ProductService.get_all(session)

            cat_id = self.category_filter.currentData()
            if cat_id:
                products = [p for p in products if p.category_id == cat_id]

            if self.low_stock_btn.isChecked():
                products = [p for p in products if p.is_low_stock]

            self._populate_table(products, session)
            self.summary_label.setText(
                f"{len(products)} product(s) shown"
                + (f" — {sum(1 for p in products if p.is_low_stock)} low stock" if products else "")
            )


    def _populate_table(self, products, session):
        self.table.setRowCount(0)
        self._product_cache = {}
        for p in products:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self._product_cache[row] = p.id

            self.table.setItem(row, 0, QTableWidgetItem(p.barcode or ""))
            self.table.setItem(row, 1, QTableWidgetItem(p.name))
            cat_name = p.category.name if p.category else "—"
            self.table.setItem(row, 2, QTableWidgetItem(cat_name))
            self.table.setItem(row, 3, QTableWidgetItem(f"€{p.price:.2f}"))
            self.table.setItem(row, 4, QTableWidgetItem(f"{p.tax}"))
            stock_item = QTableWidgetItem(f"{p.stock_quantity:.1f}")
            if p.is_low_stock:
                stock_item.setForeground(Qt.GlobalColor.red)
            self.table.setItem(row, 5, stock_item)
            self.table.setItem(row, 6, QTableWidgetItem(p.unit))

            # Action buttons
            actions = QWidget()
            actions_layout = QHBoxLayout(actions)
            actions_layout.setContentsMargins(2, 2, 2, 2)
            actions_layout.setSpacing(4)

            edit_btn = QPushButton("✏️")
            edit_btn.setFixedSize(36, 36)
            edit_btn.clicked.connect(lambda _, pid=p.id: self._edit_product(pid))
            actions_layout.addWidget(edit_btn)

            stock_btn = QPushButton("📦")
            stock_btn.setFixedSize(36, 36)
            stock_btn.setToolTip("Adjust stock")
            stock_btn.clicked.connect(lambda _, pid=p.id: self._adjust_stock(pid))
            actions_layout.addWidget(stock_btn)

            del_btn = QPushButton("🗑️")
            del_btn.setFixedSize(36, 36)
            del_btn.clicked.connect(lambda _, pid=p.id: self._delete_product(pid))
            actions_layout.addWidget(del_btn)

            self.table.setCellWidget(row, 7, actions)
            self.table.setRowHeight(row, 50)

    # ── Detail panel wiring ─────────────────────────────────────────────────

    def _on_row_selected(self):
        row = self.table.currentRow()
        if row < 0 or row not in self._product_cache:
            self.detail_panel._clear()
            return
        product_id = self._product_cache[row]
        with get_session() as session:
            product = ProductService.get_by_id(session, product_id)
            if product:
                self.detail_panel.show_product(product)
            else:
                self.detail_panel._clear()

    def _add_product(self):
        dialog = ProductDialog(self)
        if dialog.exec():
            with get_session() as session:
                ProductService.create(session, **dialog.get_data())
            self.refresh()

    def _edit_product(self, product_id: int):
        with get_session() as session:
            product = ProductService.get_by_id(session, product_id)
            if not product:
                return
            dialog = ProductDialog(self, product)
            if dialog.exec():
                ProductService.update(session, product_id, **dialog.get_data())
        self.refresh()

    def _adjust_stock(self, product_id: int):
        with get_session() as session:
            product = ProductService.get_by_id(session, product_id)
            if not product:
                return
            dialog = StockAdjustmentDialog(product, self)
            if dialog.exec():
                data = dialog.get_data()
                ProductService.adjust_stock(session, product_id, **data)
        self.refresh()

    def _delete_product(self, product_id: int):
        reply = QMessageBox.question(
            self, "Deactivate Product",
            "This will hide the product from the POS. Sales history is preserved.\nContinue?"
        )
        if reply == QMessageBox.StandardButton.Yes:
            with get_session() as session:
                ProductService.deactivate(session, product_id)
            self.refresh()

    def _clear(self):
        self.navigate.emit(0)