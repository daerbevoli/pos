"""
POS Screen
The main checkout screen: barcode scan, search, cart, payment.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QLabel,
    QHeaderView, QMessageBox, QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QKeyEvent

from app.core.database import get_session
from app.core.product_service import ProductService
from app.core.sales_service import Cart, SalesService
from app.core.settings_service import SettingsService
from app.ui.dialogs.payment_dialog import PaymentDialog
from app.ui.dialogs.product_search_dialog import ProductSearchDialog


class POSScreen(QWidget):
    def __init__(self):
        super().__init__()
        self.cart = Cart()
        self._load_settings()
        self._build_ui()

    def _load_settings(self):
        with get_session() as session:
            settings = SettingsService.get_all(session)
        self.currency = settings.get("currency_symbol", "€")
        self.cart.tax_rate = float(settings.get("tax_rate", "0.0"))

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # ── Left panel: scan / search / cart ──────────────────────────────────
        left = QVBoxLayout()

        # Barcode / search input
        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setFixedSize(800, 100)
        self.search_input.setObjectName("barcodeInput")
        self.search_input.setPlaceholderText("Scan barcode or type product name…")
        self.search_input.setFixedHeight(54)
        self.search_input.returnPressed.connect(self._on_barcode_enter)
        search_row.addWidget(self.search_input)

        search_btn = QPushButton("🔍 Search")
        search_btn.setObjectName("secondaryBtn")
        search_btn.setFixedHeight(54)
        search_btn.clicked.connect(self._open_search_dialog)
        search_row.addWidget(search_btn)
        left.addLayout(search_row)

        # Cart table + side buttons
        cart_row = QHBoxLayout()

        self.cart_table = QTableWidget(0, 5)
        self.cart_table.setObjectName("cartTable")
        self.cart_table.setHorizontalHeaderLabels(["Product", "Price", "Qty", "Total", ""])
        self.cart_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.cart_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.cart_table.setColumnWidth(4, 50)
        self.cart_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.cart_table.verticalHeader().setVisible(False)
        self.cart_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        cart_row.addWidget(self.cart_table)

        # + / - buttons beside the table
        side_btns = QVBoxLayout()
        side_btns.setAlignment(Qt.AlignmentFlag.AlignTop)
        side_btns.setSpacing(6)

        plus_btn = QPushButton("+")
        plus_btn.setObjectName("plusBtn")
        plus_btn.setFixedSize(50, 50)
        plus_btn.clicked.connect(self._increase_product)
        side_btns.addWidget(plus_btn)

        minus_btn = QPushButton("-")
        minus_btn.setObjectName("minusBtn")
        minus_btn.setFixedSize(50, 50)
        minus_btn.clicked.connect(self._decrease_product)
        side_btns.addWidget(minus_btn)

        # discount_btn = QPushButton("%")
        # discount_btn.setObjectName("discountBtn")
        # discount_btn.setFixedSize(50, 50)
        # discount_btn.clicked.connect(self._apply_discount)
        # side_btns.addWidget(minus_btn)



        cart_row.addLayout(side_btns)
        left.addLayout(cart_row)


        # Quick action buttons
        actions_row = QHBoxLayout()
        clear_btn = QPushButton("Clear")
        clear_btn.setObjectName("dangerBtn")
        clear_btn.clicked.connect(self._clear_cart)
        actions_row.addWidget(clear_btn)

        void_btn = QPushButton("❌")
        void_btn.setObjectName("warningBtn")
        void_btn.clicked.connect(self._void_last_sale)
        actions_row.addWidget(void_btn)
        left.addLayout(actions_row)

        layout.addLayout(left, stretch=4)

        # ── Right panel: totals and payment ──────────────────────────────────
        right = QVBoxLayout()
        right.setSpacing(8)

        totals_frame = QFrame()
        totals_frame.setObjectName("totalsFrame")
        totals_layout = QVBoxLayout(totals_frame)
        totals_layout.setSpacing(12)

        totals_layout.addWidget(QLabel("ORDER SUMMARY"), alignment=Qt.AlignmentFlag.AlignCenter)

        self.items_label = self._make_total_row(totals_layout, "Items")
        self.subtotal_label = self._make_total_row(totals_layout, "Subtotal")
        self.tax_label = self._make_total_row(totals_layout, "Tax")
        self.discount_label = self._make_total_row(totals_layout, "Discount")

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        totals_layout.addWidget(divider)

        self.total_label = QLabel(f"{self.currency}0.00")
        self.total_label.setObjectName("grandTotal")
        self.total_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        totals_layout.addWidget(self.total_label)

        right.addWidget(totals_frame)
        right.addStretch()

        # Payment buttons
        cash_btn = QPushButton("CASH")
        cash_btn.setObjectName("payBtn")
        cash_btn.setFixedHeight(70)
        cash_btn.clicked.connect(lambda: self._open_payment("cash"))
        right.addWidget(cash_btn)

        card_btn = QPushButton("CARD")
        card_btn.setObjectName("payBtnSecondary")
        card_btn.setFixedHeight(70)
        card_btn.clicked.connect(lambda: self._open_payment("card"))
        right.addWidget(card_btn)

        layout.addLayout(right, stretch=1)

        # Auto-focus the scan input
        QTimer.singleShot(100, self.search_input.setFocus)

    def _make_total_row(self, parent_layout, label_text) -> QLabel:
        row = QHBoxLayout()
        row.addWidget(QLabel(label_text))
        value = QLabel("—")
        value.setAlignment(Qt.AlignmentFlag.AlignRight)
        row.addWidget(value)
        parent_layout.addLayout(row)
        return value

    # ── Cart interactions ─────────────────────────────────────────────────────

    def _on_barcode_enter(self):
        query = self.search_input.text().strip()
        if not query:
            return
        with get_session() as session:
            # Try exact barcode first
            product = ProductService.get_by_barcode(session, query)
            if not product:
                # Try name search — if exactly 1 result, add it
                results = ProductService.search(session, query)
                if len(results) == 1:
                    product = results[0]
                elif len(results) > 1:
                    self.search_input.clear()
                    self._open_search_dialog(query)
                    return
            if product:
                self.cart.add_product(product)
                self._refresh_cart(select_last=True)
                self.search_input.clear()
            else:
                QMessageBox.warning(self, "Not Found", f"No product found for: {query}")
        self.search_input.clear()

    def _open_search_dialog(self, initial_query=""):
        dialog = ProductSearchDialog(self)
        if initial_query:
            dialog.set_query(initial_query)
        if dialog.exec() and dialog.selected_product:
            self.cart.add_product(dialog.selected_product)
            self._refresh_cart(select_last=True )
        self.search_input.setFocus()

    def _clear_cart(self):
        if not self.cart.items:
            return
        if QMessageBox.question(self, "Clear Cart", "Remove all items?") == QMessageBox.StandardButton.Yes:
            self.cart.clear()
            self._refresh_cart()

    def _void_last_sale(self):
        # TODO: Open void dialog to pick a recent sale
        QMessageBox.information(self, "Void Sale", "Void sale feature — coming soon.")

    # ── UI refresh ────────────────────────────────────────────────────────────

    def _refresh_cart(self, select_last=False):
        # Remember which product was selected
        selected_id = self._get_selected_product_id()

        self.cart_table.setRowCount(0)
        for item in self.cart.items.values():
            row = self.cart_table.rowCount()
            self.cart_table.insertRow(row)
            self.cart_table.setItem(row, 0, QTableWidgetItem(item.product_name))
            self.cart_table.setItem(row, 1, QTableWidgetItem(f"{self.currency}{item.unit_price:.2f}"))
            self.cart_table.setItem(row, 2, QTableWidgetItem(str(item.quantity)))
            self.cart_table.setItem(row, 3, QTableWidgetItem(f"{self.currency}{item.line_total:.2f}"))

            remove_btn = QPushButton("✕")
            remove_btn.setObjectName("removeBtn")
            product_id = item.product_id
            remove_btn.clicked.connect(lambda _, pid=product_id: self._remove_item(pid))
            self.cart_table.setCellWidget(row, 4, remove_btn)
            self.cart_table.setRowHeight(row, 48)

        # Restore selection
        if select_last or not self.cart.items:
            self.cart_table.selectRow(self.cart_table.rowCount() - 1)
        elif selected_id is not None and selected_id in self.cart.items:
            row = list(self.cart.items.keys()).index(selected_id)
            self.cart_table.selectRow(row)

        self._refresh_totals()

    def _remove_item(self, product_id: int):
        self.cart.remove_item(product_id)
        self._refresh_cart()

    def _refresh_totals(self):
        self.items_label.setText(str(self.cart.item_count))
        self.subtotal_label.setText(f"{self.currency}{self.cart.subtotal:.2f}")
        self.tax_label.setText(f"{self.currency}{self.cart.tax_amount:.2f}")
        self.discount_label.setText(f"{self.currency}{self.cart.global_discount:.2f}")
        self.total_label.setText(f"{self.currency}{self.cart.total:.2f}")

    # ── Payment ───────────────────────────────────────────────────────────────

    def _open_payment(self, method: str):
        if not self.cart.items:
            QMessageBox.warning(self, "Empty Cart", "Add items before payment.")
            return
        dialog = PaymentDialog(self.cart, method, self.currency, self)
        if dialog.exec():
            tendered = dialog.amount_tendered
            with get_session() as session:
                sale = SalesService.finalize_sale(
                    session,
                    cart=self.cart,
                    payment_method=method,
                    amount_tendered=tendered
                )
            QMessageBox.information(
                self, "Sale Complete",
                f"Sale {sale.sale_number}\nTotal: {self.currency}{sale.final_amount:.2f}"
                + (f"\nChange: {self.currency}{sale.change_given:.2f}" if sale.change_given else "")
            )
            self.cart.clear()
            self._refresh_cart()
            self.search_input.setFocus()

    def _get_selected_product_id(self):
        row = self.cart_table.currentRow()
        print(row)
        if row < 0:  # -1 means nothing selected
            return None
        # Get product_id from the cart items list at that row position
        return list(self.cart.items.keys())[row]

    def _increase_product(self):
        product_id = self._get_selected_product_id()
        if product_id is None:
            return
        self.cart.items[product_id].quantity += 1
        self._refresh_cart()

    def _decrease_product(self):
        product_id = self._get_selected_product_id()
        if product_id is None:
            return
        if self.cart.items[product_id].quantity > 1:
            self.cart.items[product_id].quantity -= 1
        else:
            return
        self._refresh_cart()
