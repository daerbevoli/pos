"""
Inventory Screen
View, add, edit products and manage stock levels.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QLabel,
    QHeaderView, QMessageBox, QComboBox
)
from PyQt6.QtCore import Qt

from app.core.database import get_session
from app.core.product_service import ProductService
from app.ui.dialogs.product_dialog import ProductDialog
from app.ui.dialogs.stock_adjustment_dialog import StockAdjustmentDialog


class InventoryScreen(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # ── Toolbar ───────────────────────────────────────────────────────────
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

        self.low_stock_btn = QPushButton("⚠️ Low Stock Only")
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
        self.table.setHorizontalHeaderLabels([
            "Barcode", "Name", "Category", "Price", "Tax", "Stock", "Unit", "Actions"
        ])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        # ── Summary row ───────────────────────────────────────────────────────
        self.summary_label = QLabel()
        layout.addWidget(self.summary_label)

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
        for p in products:
            row = self.table.rowCount()
            self.table.insertRow(row)

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
