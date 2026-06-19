"""
POS Screen
Grid-button touchscreen layout: sale tabs, ticket list, function grid,
payment row, and a numpad + category/product grid — modeled on classic
register touchscreen POS terminals (Lightspeed/Tilroy/Tlecom-style).
"""
import sys

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QLabel,
    QHeaderView, QMessageBox, QFrame, QSizePolicy, QButtonGroup
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QDateTime
from PyQt6.QtGui import QFont, QBrush, QColor

from app.core.database import get_session
from app.core.product_service import ProductService
from app.core.sales_service import Cart, SalesService
from app.core.settings_service import SettingsService
from app.ui.dialogs.product_search_dialog import ProductSearchDialog
from app.utils.utils import TicketTab, CategoryButton, FunctionButton, TapToDismissOverlay

from app.ui.dialogs.numpad_dialog import NumpadDialog

import logging

ADMIN_CODE = "2060" # Make env var or be able to be set


class POSScreen(QWidget):
    MAX_TABS = 5
    isAdmin = False

    def __init__(self):
        super().__init__()
        self.cart = Cart()
        self.tabs_data = {1: self.cart}     # ticket-slot -> Cart
        self.active_tab = 1
        self._load_settings()
        self._build_ui()
        self._start_clock()
        self.overlay = TapToDismissOverlay(self)  # <-- add this

    # ── Setup ────────────────────────────────────────────────────────────

    def _load_settings(self):
        with get_session() as session:
            settings = SettingsService.get_all(session)
        self.currency = settings.get("currency_symbol", "€")

        self.cashier_name = settings.get("cashier_name", "Cashier")

    def _build_ui(self):
        logging.info("Build UI called")

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        root.addLayout(self._build_tab_row())

        body = QHBoxLayout()
        body.setSpacing(6)
        body.addLayout(self._build_ticket_panel(), stretch=5)
        body.addLayout(self._build_control_grid(), stretch=4)
        root.addLayout(body, stretch=5)

        root.addLayout(self._build_bottom_grid(), stretch=4)

        QTimer.singleShot(100, self.search_input.setFocus)

    # ── Top: sale-slot tabs + clock ─────────────────────────────────────

    def _build_tab_row(self):
        row = QHBoxLayout()
        row.setSpacing(4)

        self.tab_group = QButtonGroup(self)
        self.tab_group.setExclusive(True)
        self.tab_buttons = {}

        for i in range(1, self.MAX_TABS + 1):
            btn = TicketTab(i)
            btn.clicked.connect(lambda _, idx=i: self._switch_tab(idx))
            self.tab_group.addButton(btn)
            self.tab_buttons[i] = btn
            row.addWidget(btn, stretch=1)

        self.tab_buttons[1].setChecked(True)

        clock_box = QVBoxLayout()
        clock_box.setSpacing(0)
        self.clock_label = QLabel("")
        self.clock_label.setObjectName("clockLabel")
        self.clock_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.status_label = QLabel(f"{self.cashier_name}")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        clock_box.addWidget(self.clock_label)
        clock_box.addWidget(self.status_label)

        clock_frame = QFrame()
        clock_frame.setObjectName("clockFrame")
        clock_frame.setLayout(clock_box)
        clock_frame.setFixedWidth(220)
        row.addWidget(clock_frame, stretch=0)

        return row

    def _start_clock(self):
        self._tick()
        timer = QTimer(self)
        timer.timeout.connect(self._tick)
        timer.start(1000)
        self._clock_timer = timer

    def _tick(self):
        now = QDateTime.currentDateTime()
        self.clock_label.setText(now.toString("dd-MM-yyyy   HH:mm"))

    # ── Left: ticket header + cart table ────────────────────────────────

    def _build_ticket_panel(self):
        col = QVBoxLayout()
        col.setSpacing(4)

        header = QHBoxLayout()
        self.ticket_title = QLabel(f"V {self.active_tab}")
        self.ticket_title.setObjectName("ticketTitle")
        header.addWidget(self.ticket_title)
        header.addStretch()
        self.ticket_date = QLabel("")
        self.ticket_date.setObjectName("ticketDate")
        header.addWidget(self.ticket_date)
        col.addLayout(header)

        # Hidden scan/search input — barcode scanner still types into this
        self.search_input = QLineEdit()
        self.search_input.setObjectName("barcodeInput")
        self.search_input.setPlaceholderText("Scan barcode or type product name…")
        self.search_input.setMinimumHeight(32)
        self.search_input.returnPressed.connect(self._on_barcode_enter)
        col.addWidget(self.search_input)

        self.cart_table = QTableWidget(0, 4)
        self.cart_table.setObjectName("cartTable")
        self.cart_table.setHorizontalHeaderLabels(["Qty", "Description", "Price", "Total"])
        self.cart_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.cart_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.cart_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.cart_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.cart_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.cart_table.verticalHeader().setVisible(False)
        self.cart_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        col.addWidget(self.cart_table, stretch=1)

        # Inline status line — shows discount/payment/change feedback,
        # replaces what would otherwise be a popup dialog.
        self.status_line = QLabel("")
        self.status_line.setObjectName("inlineStatus")
        self.status_line.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_line.setMinimumHeight(22)
        self.status_line.setMaximumHeight(36)
        col.addWidget(self.status_line)

        # Dedicated numeric entry — discount amount or tendered amount,
        # depending on which button is pressed next.
        amount_row = QHBoxLayout()
        amount_label = QLabel("Amount:")
        amount_label.setObjectName("amountLabel")
        self.amount_input = QLineEdit()
        self.amount_input.setObjectName("amountInput")
        self.amount_input.setPlaceholderText("Type a number, then €/% discount or Cash/Bancontact…")
        self.amount_input.setMinimumHeight(34)
        self.amount_input.returnPressed.connect(lambda: self._open_payment("cash"))
        amount_row.addWidget(amount_label)
        amount_row.addWidget(self.amount_input, stretch=1)
        col.addLayout(amount_row)

        return col

    # ── Right: function-key grid (arrows, qty, discount, payment types) ──

    def _build_control_grid(self):
        col = QVBoxLayout()
        col.setSpacing(4)

        grid = QGridLayout()
        grid.setSpacing(4)

        self.btn_left = FunctionButton("←", "navBtn")
        self.btn_right = FunctionButton("→", "navBtn")
        self.btn_reopen = FunctionButton("Reopen\nticket", "secFunc")
        self.btn_print_ticket = FunctionButton("Print\nticket", "secFunc")
        self.btn_print_invoice = FunctionButton("Print\ninvoice", "secFunc")
        self.btn_error = FunctionButton("Error", "errorBtn")

        self.btn_up = FunctionButton("↑", "navBtn")
        self.btn_plus = FunctionButton("+", "navBtn")
        self.btn_clear = FunctionButton("Clear", "clearBtn")

        self.btn_down = FunctionButton("↓", "navBtn")
        self.btn_minus = FunctionButton("-", "navBtn")
        self.btn_item_name = FunctionButton("Item\nname", "secFunc")
        self.btn_admin = FunctionButton("Admin", "secFunc")

        self.btn_disc_amt = FunctionButton("€\ndiscount", "discountBtn")
        self.btn_disc_pct = FunctionButton("%\ndiscount", "discountBtn")
        self.btn_barcode = FunctionButton("Barcode", "secFunc")
        self.btn_drawer = FunctionButton("Drawer", "secFunc")

        self.btn_customer = FunctionButton("Customer", "customerBtn")
        self.btn_card = FunctionButton("Card", "cardBtn")
        self.btn_ok = FunctionButton("OK", "okBtn")

        layout_map = [
            (self.btn_left, 0, 0, 1, 1), (self.btn_right, 0, 1, 1, 1),
            (self.btn_reopen, 0, 2, 1, 1), (self.btn_print_ticket, 0, 3, 1, 1),
            (self.btn_print_invoice, 0, 4, 1, 1), (self.btn_error, 0, 5, 1, 1),

            (self.btn_up, 1, 0, 1, 1), (self.btn_plus, 1, 1, 1, 1),
            (self.btn_clear, 1, 5, 1, 1),

            (self.btn_down, 2, 0, 1, 1), (self.btn_minus, 2, 1, 1, 1),
            (self.btn_item_name, 2, 3, 1, 1), (self.btn_admin, 2, 5, 1, 1),

            (self.btn_disc_amt, 3, 0, 1, 1), (self.btn_disc_pct, 3, 1, 1, 1),
            (self.btn_barcode, 3, 2, 1, 1), (self.btn_drawer, 3, 4, 1, 1),

            (self.btn_customer, 4, 2, 1, 1), (self.btn_card, 4, 3, 1, 1),
            (self.btn_ok, 4, 5, 1, 1),
        ]
        for widget, r, c, rs, cs in layout_map:
            grid.addWidget(widget, r, c, rs, cs)

        for c in range(6):
            grid.setColumnStretch(c, 1)
        for r in range(5):
            grid.setRowStretch(r, 1)

        col.addLayout(grid, stretch=3)

        # Payment-method row: Bancontact / Meal vouchers / Subtotal / Cash
        pay_grid = QGridLayout()
        pay_grid.setSpacing(4)

        self.btn_bancontact = FunctionButton("Bancontact", "payAltBtn")
        self.btn_meal_voucher = FunctionButton("Meal\nvoucher", "payAltBtn")
        self.btn_subtotal = FunctionButton("Subtotal", "subtotalBtn")
        self.btn_cash = FunctionButton("Cash", "cashBtn")

        pay_grid.addWidget(self.btn_bancontact, 0, 0)
        pay_grid.addWidget(self.btn_meal_voucher, 1, 0)
        pay_grid.addWidget(self.btn_subtotal, 0, 1, 2, 1)
        pay_grid.addWidget(self.btn_cash, 0, 2, 2, 1)
        pay_grid.setColumnStretch(0, 1)
        pay_grid.setColumnStretch(1, 1)
        pay_grid.setColumnStretch(2, 1)

        col.addLayout(pay_grid, stretch=2)

        # Wire up behavior
        self.btn_plus.clicked.connect(self._increase_product)
        self.btn_minus.clicked.connect(self._decrease_product)
        self.btn_clear.clicked.connect(self._clear_cart)
        self.btn_error.clicked.connect(self._remove_selected)
        self.btn_barcode.clicked.connect(lambda: self._open_search_dialog())
        self.btn_subtotal.clicked.connect(self._show_subtotal)
        self.btn_cash.clicked.connect(lambda: self._open_payment("cash"))
        self.btn_card.clicked.connect(lambda: self._open_payment("card"))
        self.btn_bancontact.clicked.connect(lambda: self._open_payment("bancontact"))
        self.btn_meal_voucher.clicked.connect(lambda: self._open_payment("meal_voucher"))
        self.btn_ok.clicked.connect(self._on_barcode_enter)
        self.btn_disc_pct.clicked.connect(self._apply_percent_discount)
        self.btn_disc_amt.clicked.connect(self._apply_amount_discount)
        self.btn_up.clicked.connect(lambda: self._move_selection(-1))
        self.btn_down.clicked.connect(lambda: self._move_selection(1))

        self.btn_admin.clicked.connect(self._admin)

        return col

    # ── Bottom: numpad + category/product grid ───────────────────────────

    def _build_bottom_grid(self):
        row = QHBoxLayout()
        row.setSpacing(4)

        # Category / quick-product grid (left, large area)
        self.category_grid = QGridLayout()
        self.category_grid.setSpacing(4)

        self.category_buttons = []
        # Each row: (labels, role). Empty label -> a blank placeholder key
        # rendered in that row's own tier color.
        labels_rows = [
            (["", "", "", "", "", "", "", ""], "blankBtnLight"),
            (["", "", "", "", "", "", "", ""], "blankBtnLight"),
            (["", "", "", "", "", "", "", ""], "productBtn"),
            (["General", "Vegetables", "Fruit", "Drinks", "Bakery", "Rice", "Asian food", ""], "categoryBtn"),
            (["", "Seafood", "Takeaway food", "Takeaway item", "Trays", "Cooking item", "", "Checkout"], "categoryBtn"),
        ]
        for r, (labels, role) in enumerate(labels_rows):
            for c, label in enumerate(labels):
                role_use = role if label else ("blankBtnLight" if role == "categoryBtn" else role)
                btn = CategoryButton(label, role_use)
                if label == "General":
                    btn.setObjectName("generalBtn")
                elif label == "Checkout":
                    btn.setObjectName("checkoutBtn")
                    btn.clicked.connect(self._show_subtotal)
                self.category_grid.addWidget(btn, r, c)
                self.category_buttons.append(btn)

        for c in range(8):
            self.category_grid.setColumnStretch(c, 1)
        for r in range(5):
            self.category_grid.setRowStretch(r, 1)

        row.addLayout(self.category_grid, stretch=4)

        # Numpad (right)
        numpad = QGridLayout()
        numpad.setSpacing(4)
        keys = [
            ("7", 0, 0), ("8", 0, 1), ("9", 0, 2),
            ("4", 1, 0), ("5", 1, 1), ("6", 1, 2),
            ("1", 2, 0), ("2", 2, 1), ("3", 2, 2),
            ("0", 3, 0), (",", 3, 1), ("⌫", 3, 2),
        ]
        for label, r, c in keys:
            btn = QPushButton(label)
            btn.setObjectName("numKey" if label not in ("⌫",) else "numKeyDel")
            btn.setMinimumHeight(36)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            btn.clicked.connect(lambda _, l=label: self._numpad_press(l))
            numpad.addWidget(btn, r, c)

        for c in range(3):
            numpad.setColumnStretch(c, 1)
        for r in range(4):
            numpad.setRowStretch(r, 1)

        row.addLayout(numpad, stretch=1)
        return row

    # ── Numpad / scan input helpers ──────────────────────────────────────

    def _numpad_press(self, label: str):
        if label == "⌫":
            self.amount_input.setText(self.amount_input.text()[:-1])
        elif label == ",":
            if "." not in self.amount_input.text():
                self.amount_input.insert(".")
        else:
            self.amount_input.insert(label)
        self.amount_input.setFocus()

    # ── Tab (sale-slot) switching ────────────────────────────────────────

    def _switch_tab(self, idx: int):
        self.active_tab = idx
        if idx not in self.tabs_data:
            self.tabs_data[idx] = Cart()
        self.cart = self.tabs_data[idx]
        self.ticket_title.setText(f"V {idx}")
        self._refresh_cart()

    def _update_tab_label(self, idx: int):
        cart = self.tabs_data.get(idx)
        if cart and cart.items:
            self.tab_buttons[idx]._set_label(f"V {idx}", f"{cart.total:.2f}".replace(".", ","))
        else:
            self.tab_buttons[idx]._set_label(f"V {idx}", "")

    # ── Cart interactions (unchanged backend wiring) ─────────────────────

    def _on_barcode_enter(self):
        query = self.search_input.text().strip()
        if not query:
            return
        with get_session() as session:
            product = ProductService.get_by_barcode(session, query)
            if not product:
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
            self._refresh_cart(select_last=True)
        self.search_input.setFocus()

    def _clear_cart(self):
        if not self.cart.items:
            return
        if QMessageBox.question(self, "Clear Ticket", "Remove all items?") == QMessageBox.StandardButton.Yes:
            self.cart.clear()
            self.cart.global_discount = 0.0
            self.amount_input.clear()
            self.search_input.clear()
            self.status_line.setText("")
            self._refresh_cart()

    def _remove_selected(self):
        product_id = self._get_selected_product_id()
        if product_id is None:
            return
        self.cart.remove_item(product_id)
        self._refresh_cart()

    def _apply_percent_discount(self):
        if self.cart.item_count == 0:
            self._show_overlay("No items in cart.", title="Empty Ticket", kind="error")
            return

        value = self._read_amount_input()
        if value is None:
            self._show_overlay("Enter a number first to apply a discount", "Empty discount", kind="info")
            return
        pct = min(value, 100.0)
        discount_amount = self.cart.subtotal * (pct / 100.0)
        self.cart.global_discount = discount_amount
        self.amount_input.clear()

        self._show_discount(discount_amount, "%")
        self.amount_input.setFocus()

    def _apply_amount_discount(self):
        if self.cart.item_count == 0:
            self._show_overlay("No items in cart.", title="Empty Ticket", kind="error")
            return

        value = self._read_amount_input()
        if value is None:
            self._show_overlay("Enter a number first to apply a discount", "Empty discount", kind="info")
            return
        # Clamp: a discount can never exceed the subtotal.
        discount_amount = min(value, self.cart.subtotal)
        self.cart.global_discount = discount_amount
        self.amount_input.clear()

        self._show_discount(discount_amount, "€")
        self.amount_input.setFocus()




    # Subtotal gets added at every press and removed at item addition
    def _show_subtotal(self):
        if self.cart.item_count == 0:
            self._show_overlay("No items in cart.", title="Empty Ticket", kind="error")
            return
        row = self.cart_table.rowCount()

        self.cart_table.insertRow(row)

        subtotal = [
            QTableWidgetItem(str(self.cart.item_count)),
            QTableWidgetItem("SUBTOTAL"),
            QTableWidgetItem(""),
            QTableWidgetItem(f"{self.currency}{self.cart.total:.2f}")
        ]

        font = QFont()
        font.setBold(True)

        for col, item in enumerate(subtotal):
            item.setFont(font)
            item.setBackground(QBrush(QColor(255, 230, 120)))
            self.cart_table.setItem(row, col, item)

        self.cart_table.setRowHeight(row, 25)

    # ── UI refresh ────────────────────────────────────────────────────────

    def _refresh_cart(self, select_last=False):
        selected_id = self._get_selected_product_id()

        self.cart_table.setRowCount(0)
        for item in self.cart.items.values():
            row = self.cart_table.rowCount()
            self.cart_table.insertRow(row)
            self.cart_table.setItem(row, 0, QTableWidgetItem(str(item.quantity)))
            self.cart_table.setItem(row, 1, QTableWidgetItem(item.product_name))
            self.cart_table.setItem(row, 2, QTableWidgetItem(f"{self.currency}{item.unit_price:.2f}"))
            self.cart_table.setItem(row, 3, QTableWidgetItem(f"{self.currency}{item.line_total:.2f}"))
            self.cart_table.setRowHeight(row, 25)

        if select_last or not self.cart.items:
            self.cart_table.selectRow(self.cart_table.rowCount() - 1)
        elif selected_id is not None and selected_id in self.cart.items:
            row = list(self.cart.items.keys()).index(selected_id)
            self.cart_table.selectRow(row)

        self._update_tab_label(self.active_tab)

    def _move_selection(self, delta: int):
        row = self.cart_table.currentRow()
        new_row = max(0, min(self.cart_table.rowCount() - 1, row + delta))
        self.cart_table.selectRow(new_row)

    # ── Payment ───────────────────────────────────────────────────────────

    def _open_payment(self, method: str):
        if not self.cart.items:
            self._show_overlay("Add items before payment.", title="Empty Ticket", kind="error")
            return

        typed = self._read_amount_input()
        total = self.cart.total

        if typed is None:
            # No number typed -> exact payment, no change.
            tendered = total
        else:
            tendered = typed

        with get_session() as session:
            sale = SalesService.finalize_sale(
                session,
                cart=self.cart,
                payment_method=method,
                amount_tendered=tendered
            )

        change = max(0.0, tendered - total)
        method_label = {
            "cash": "Cash", "card": "Card",
            "bancontact": "Bancontact", "meal_voucher": "Meal voucher"
        }.get(method, method.title())

        if change > 0:
            self.status_line.setText(
                f"Paid {self.currency}{tendered:.2f} ({method_label}) — Change {self.currency}{change:.2f}"
            )
        else:
            self.status_line.setText(f"Paid {self.currency}{tendered:.2f} ({method_label})")

        self.amount_input.clear()
        self.cart.global_discount = 0.0
        self.cart.clear()
        self._refresh_cart()
        self.amount_input.setFocus()


    def _get_selected_product_id(self):
        row = self.cart_table.currentRow()
        if row < 0:
            return None
        keys = list(self.cart.items.keys())
        if row >= len(keys):
            return None
        return keys[row]

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

    def _read_amount_input(self) -> float | None:
        """Parse the dedicated amount field. Returns None if empty/invalid."""
        text = self.amount_input.text().strip().replace(",", ".")
        if not text:
            return None
        try:
            value = float(text)
        except ValueError:
            return None
        return max(0.0, value)

    def _admin(self):
        if self.isAdmin:
            self.isAdmin = False
            self.status_label.setText("Cashier")
            return

        dialog = NumpadDialog(title="Enter Quantity", parent=self)
        if dialog.exec():
            code = dialog.value
            if code == ADMIN_CODE:
                self.isAdmin = True
                self.status_label.setText("Admin")
            return

    def _show_overlay(self, message: str, title: str = "", kind: str = "info"):
        self.overlay.show_message(message, title=title, kind=kind)

    def _show_discount(self, amount: float, pct_or_curr: str):
        row = self.cart_table.rowCount()

        self.cart_table.insertRow(row)

        discount_str = str(round(amount, 2))
        discount = [
            QTableWidgetItem(""),
            QTableWidgetItem("DISCOUNT  " + str(amount) + pct_or_curr),
            QTableWidgetItem(""),
            QTableWidgetItem('-' + discount_str),
        ]

        font = QFont()
        font.setBold(True)

        for col, item in enumerate(discount):
            item.setFont(font)
            item.setBackground(QBrush(QColor(145, 230, 120)))
            self.cart_table.setItem(row, col, item)

        self.cart_table.setRowHeight(row, 25)


