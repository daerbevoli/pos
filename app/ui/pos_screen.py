"""
POS Screen
Grid-button touchscreen layout: ticket list, function grid,
payment row, and a numpad + category/product grid.
Tab state (cart, frozen, client) is managed per V-tab slot and
driven externally by MainWindow via set_active_tab().
"""
import sys

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QLabel,
    QHeaderView, QMessageBox, QFrame, QSizePolicy, QStackedWidget
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QDateTime
from PyQt6.QtGui import QFont, QBrush, QColor

from app.core.database import get_session
from app.core.product_service import ProductService
from app.core.sales_service import Cart, SalesService
from app.core.settings_service import SettingsService
from app.ui.dialogs.client_search_dialog import ClientSearchDialog
from app.ui.dialogs.product_search_dialog import ProductSearchDialog
from app.utils.utils import CategoryButton, FunctionButton, TapToDismissOverlay, TicketTable
from app.ui.dialogs.numpad_dialog import NumpadDialog

import logging

ADMIN_CODE = "2060"


class _TabState:
    """Snapshot of one V-tab slot's POS state."""
    def __init__(self):
        self.cart         = Cart()
        self.sale_finished = False
        self.is_invoice   = False
        self.client_id    = None
        self.client_name  = ""
        self.payment_text = ""


class POSScreen(QWidget):
    navigate           = pyqtSignal(int)   # ask MainWindow to switch screen
    salesperson_changed = pyqtSignal(str)  # cashier name update for header
    tab_updated        = pyqtSignal(int, str)  # (vtab_idx, amount_str) for tab button

    isAdmin = False

    def __init__(self):
        super().__init__()
        self._tab_states: dict[int, _TabState] = {i: _TabState() for i in range(1, 6)}
        self._active_tab = 1
        self.cart         = self._tab_states[1].cart
        self.sale_finished = False
        self.is_invoice   = False
        self.client_id    = None

        self.overlay = TapToDismissOverlay(self)
        self._load_settings()
        self._build_ui()
        self._start_time_display()

    @property
    def cart_active(self) -> bool:
        return bool(self.cart.items) or self.is_invoice

    # ── Setup ────────────────────────────────────────────────────────────

    def _load_settings(self):
        with get_session() as session:
            settings = SettingsService.get_all(session)
        self.currency     = settings.get("currency_symbol", "€")
        self.cashier_name = settings.get("cashier_name", "Cashier")

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        body = QHBoxLayout()
        body.setSpacing(6)
        body.addLayout(self._build_ticket_panel(), stretch=5)
        body.addLayout(self._build_control_grid(), stretch=4)
        root.addLayout(body, stretch=5)

        root.addLayout(self._build_bottom_grid(), stretch=4)

        QTimer.singleShot(100, self.combined_input.setFocus)

    # ── Time display (ticket header only) ──

    def _start_time_display(self):
        self._tick_time()
        t = QTimer(self)
        t.timeout.connect(self._tick_time)
        t.start(1000)

    def _tick_time(self):
        self.ticket_date.setText(QDateTime.currentDateTime().toString("HH:mm"))

    # ── Left: ticket header + cart table ────────────────────────────────

    def _build_ticket_panel(self):
        col = QVBoxLayout()
        col.setSpacing(4)

        header = QHBoxLayout()
        self.ticket_title = QLabel(f"V {self._active_tab}")
        self.ticket_title.setObjectName("ticketTitle")
        header.addWidget(self.ticket_title)
        header.addStretch()
        self.ticket_date = QLabel("")
        self.ticket_date.setObjectName("ticketDate")
        header.addWidget(self.ticket_date)
        col.addLayout(header)

        self.cart_table = TicketTable(0, 4)
        self.cart_table.setObjectName("cartTable")
        self.cart_table.setHorizontalHeaderLabels(["Qty", "Description", "Price", "Total"])
        self.cart_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.cart_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.cart_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.cart_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.cart_table.horizontalHeader().setVisible(False)
        self.cart_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.cart_table.verticalHeader().setVisible(False)
        self.cart_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        self.client_label = QLabel("")
        self.client_label.setObjectName("clientLabel")
        self.client_label.setMinimumHeight(34)
        self.client_label.setStyleSheet("color: #0000ff; background-color: #fbf3ee; font: bold;")
        self.client_label.setVisible(False)
        col.addWidget(self.client_label)

        self.cart_table.backspace_pressed.connect(self._remove_selected)
        self.cart_table.enter_pressed.connect(self._on_barcode_enter)
        self.cart_table.text_entered.connect(self._on_ticket_text)

        col.addWidget(self.cart_table, stretch=1)

        self.combined_input = QLineEdit()
        self.combined_input.setObjectName("combinedInput")
        self.combined_input.setPlaceholderText("")
        self.combined_input.setMinimumHeight(34)
        self.combined_input.returnPressed.connect(self._on_barcode_enter)

        self.payment_label = QLabel()
        self.payment_label.setObjectName("paymentLabel")
        self.payment_label.setMinimumHeight(34)
        self.payment_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

        self.input_stack = QStackedWidget()
        self.input_stack.addWidget(self.combined_input)  # 0 — normal
        self.input_stack.addWidget(self.payment_label)   # 1 — frozen
        col.addWidget(self.input_stack)

        return col

    # ── Right: function-key grid ─────────────────────────────────────────

    def _build_control_grid(self):
        col = QVBoxLayout()
        col.setSpacing(4)

        grid = QGridLayout()
        grid.setSpacing(4)

        self.btn_left          = FunctionButton("←", "navBtn")
        self.btn_right         = FunctionButton("→", "navBtn")
        self.btn_reopen        = FunctionButton("Reopen\nticket", "secFunc")
        self.btn_print_ticket  = FunctionButton("Print\nticket", "secFunc")
        self.btn_print_invoice = FunctionButton("Print\ninvoice", "secFunc")
        self.btn_error         = FunctionButton("Error", "errorBtn")

        self.btn_up    = FunctionButton("↑", "navBtn")
        self.btn_plus  = FunctionButton("+", "navBtn")
        self.btn_clear = FunctionButton("Clear", "clearBtn")

        self.btn_down  = FunctionButton("↓", "navBtn")
        self.btn_minus = FunctionButton("-", "navBtn")
        self.btn_admin = FunctionButton("Admin", "secFunc")

        self.btn_disc_amt = FunctionButton("€\ndiscount", "discountBtn")
        self.btn_disc_pct = FunctionButton("%\ndiscount", "discountBtn")
        self.btn_drawer   = FunctionButton("Drawer", "secFunc")

        self.btn_card = FunctionButton("Card", "cardBtn")
        self.btn_ok   = FunctionButton("OK", "okBtn")

        self.btn_articles = FunctionButton("Articles", "secFunc")
        self.btn_client   = FunctionButton("Client", "customerBtn")
        self.btn_settings = FunctionButton("Settings", "secFunc")
        self.btn_reports  = FunctionButton("Reports", "reportsBtn")

        layout_map = [
            (self.btn_left, 0, 0, 1, 1), (self.btn_right, 0, 1, 1, 1),
            (self.btn_reopen, 0, 2, 1, 1), (self.btn_print_ticket, 0, 3, 1, 1),
            (self.btn_print_invoice, 0, 4, 1, 1), (self.btn_error, 0, 5, 1, 1),

            (self.btn_up, 1, 0, 1, 1), (self.btn_plus, 1, 1, 1, 1),
            (self.btn_clear, 1, 5, 1, 1),

            (self.btn_down, 2, 0, 1, 1), (self.btn_minus, 2, 1, 1, 1),
            (self.btn_settings, 2, 3, 1, 1), (self.btn_admin, 2, 5, 1, 1),

            (self.btn_disc_amt, 3, 0, 1, 1), (self.btn_disc_pct, 3, 1, 1, 1),
            (self.btn_articles, 3, 2, 1, 1), (self.btn_drawer, 3, 4, 1, 1),
            (self.btn_reports, 3, 5, 1, 1),

            (self.btn_client, 4, 2, 1, 1), (self.btn_card, 4, 3, 1, 1),
            (self.btn_ok, 4, 5, 1, 1),
        ]
        for widget, r, c, rs, cs in layout_map:
            grid.addWidget(widget, r, c, rs, cs)

        for c in range(6):
            grid.setColumnStretch(c, 1)
        for r in range(5):
            grid.setRowStretch(r, 1)

        col.addLayout(grid, stretch=3)

        # Payment row
        pay_grid = QGridLayout()
        pay_grid.setSpacing(4)

        self.btn_bancontact   = FunctionButton("Bancontact", "payAltBtn")
        self.btn_meal_voucher = FunctionButton("Meal\nvoucher", "payAltBtn")
        self.btn_subtotal     = FunctionButton("Subtotal", "subtotalBtn")
        self.btn_cash         = FunctionButton("Cash", "cashBtn")

        pay_grid.addWidget(self.btn_bancontact, 0, 0)
        pay_grid.addWidget(self.btn_meal_voucher, 1, 0)
        pay_grid.addWidget(self.btn_subtotal, 0, 1, 2, 1)
        pay_grid.addWidget(self.btn_cash, 0, 2, 2, 1)
        pay_grid.setColumnStretch(0, 1)
        pay_grid.setColumnStretch(1, 1)
        pay_grid.setColumnStretch(2, 1)

        col.addLayout(pay_grid, stretch=2)

        # Wire up
        self.btn_plus.clicked.connect(self._increase_product)
        self.btn_minus.clicked.connect(self._decrease_product)
        self.btn_clear.clicked.connect(self._clear_cart)
        self.btn_error.clicked.connect(self._remove_selected)
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
        self.btn_articles.clicked.connect(lambda: self._emit_signal(1))
        self.btn_client.clicked.connect(lambda: self._emit_signal(2))
        self.btn_settings.clicked.connect(lambda: self._emit_signal(3))
        self.btn_reports.clicked.connect(lambda: self._emit_signal(4))

        return col

    # ── Bottom: numpad + category/product grid ───────────────────────────

    def _build_bottom_grid(self):
        row = QHBoxLayout()
        row.setSpacing(4)

        self.category_grid = QGridLayout()
        self.category_grid.setSpacing(4)

        self.category_buttons = []
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
            btn.setObjectName("numKey" if label != "⌫" else "numKeyDel")
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

    # ── V-tab state management ───────────────────────────────────────────

    def set_active_tab(self, idx: int):
        """Called by MainWindow when the user selects a different V tab."""
        if idx == self._active_tab:
            return
        self._save_tab_state()
        self._active_tab = idx
        self._load_tab_state(idx)

    def _save_tab_state(self):
        s = self._tab_states[self._active_tab]
        s.cart          = self.cart
        s.sale_finished = self.sale_finished
        s.is_invoice    = self.is_invoice
        s.client_id     = self.client_id
        s.client_name   = self.client_label.text() if self.client_label.isVisible() else ""
        s.payment_text  = self.payment_label.text()

    def _load_tab_state(self, idx: int):
        s = self._tab_states[idx]
        self.cart          = s.cart
        self.sale_finished = s.sale_finished
        self.is_invoice    = s.is_invoice
        self.client_id     = s.client_id

        if s.client_name:
            self.client_label.setText(s.client_name)
            self.client_label.setVisible(True)
        else:
            self.client_label.setVisible(False)

        # Restore frozen / unfrozen visuals
        frozen = "true" if s.sale_finished else "false"
        self.cart_table.setProperty("frozen", frozen)
        self.cart_table.style().unpolish(self.cart_table)
        self.cart_table.style().polish(self.cart_table)
        if s.sale_finished:
            self.payment_label.setText(s.payment_text)
            self.input_stack.setCurrentIndex(1)
        else:
            self.input_stack.setCurrentIndex(0)

        self.ticket_title.setText(f"V {idx}")
        self._refresh_cart()
        self.combined_input.setFocus()

    # ── Numpad / scan input helpers ──────────────────────────────────────

    def _numpad_press(self, label: str):
        if label == "⌫":
            self.combined_input.setText(self.combined_input.text()[:-1])
        elif label == ",":
            if "." not in self.combined_input.text():
                self.combined_input.insert(".")
        else:
            self.combined_input.insert(label)
        self.combined_input.setFocus()

    # ── Cart interactions ────────────────────────────────────────────────

    def _on_ticket_text(self, text: str):
        if self.sale_finished:
            self._unfreeze_ticket()
        self.combined_input.insert(text)

    def _on_barcode_enter(self):
        query = self.combined_input.text().strip()
        if not query:
            return
        if self.sale_finished:
            self._unfreeze_ticket()
        with get_session() as session:
            product = ProductService.get_by_barcode(session, query)
            if product:
                self.cart.add_product(product)
                self._refresh_cart(select_last=True)
                self.combined_input.clear()
            else:
                self._show_overlay("Unknown barcode", kind="error")
        self.combined_input.clear()

    def _open_search_dialog(self, initial_query=""):
        dialog = ProductSearchDialog(self)
        if initial_query:
            dialog.set_query(initial_query)
        if dialog.exec() and dialog.selected_product:
            if self.sale_finished:
                self._unfreeze_ticket()
            self.cart.add_product(dialog.selected_product)
            self._refresh_cart(select_last=True)
        self.combined_input.setFocus()

    def _clear_cart(self):
        if not self.cart_active:
            return
        if QMessageBox.question(self, "Clear Cart", "Clear cart?") == QMessageBox.StandardButton.Yes:
            self.cart.clear()
            self.cart.global_discount = 0.0
            self.combined_input.clear()
            self.client_label.setVisible(False)
            self.client_id = None
            self.is_invoice = False
            self._refresh_cart()
        self.combined_input.setFocus()

    def add_product_by_id(self, product_id: int):
        with get_session() as session:
            product = ProductService.get_by_id(session, product_id)
            if product:
                self.cart.add_product(product)
                self._refresh_cart(select_last=True)
                self.combined_input.clear()
            else:
                self._show_overlay("Unknown barcode", kind="error")
        self.combined_input.clear()

    def _remove_selected(self):
        if self.sale_finished:
            return
        product_id = self._get_selected_product_id()
        if product_id is None:
            return
        self.cart.remove_item(product_id)
        self._refresh_cart()
        self.combined_input.setFocus()

    def _apply_percent_discount(self):
        if self.sale_finished:
            return
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
        self.combined_input.clear()
        self._show_discount(pct, discount_amount, "%")
        self.combined_input.setFocus()

    def _apply_amount_discount(self):
        if self.sale_finished:
            return
        if self.cart.item_count == 0:
            self._show_overlay("No items in cart.", title="Empty Ticket", kind="error")
            return
        value = self._read_amount_input()
        if value is None:
            self._show_overlay("Enter a number first to apply a discount", "Empty discount", kind="info")
            return
        discount_amount = min(value, self.cart.subtotal)
        self.cart.global_discount = discount_amount
        self.combined_input.clear()
        self._show_discount(value, discount_amount, "€")
        self.combined_input.setFocus()

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
            QTableWidgetItem(f"{self.currency}{self.cart.total:.2f}"),
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

        # Notify MainWindow so the tab button label stays current
        amount = f"{self.cart.total:.2f}".replace(".", ",") if self.cart.items else ""
        self.tab_updated.emit(self._active_tab, amount)

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
        tendered = total if typed is None else typed

        with get_session() as session:
            SalesService.finalize_sale(
                session,
                cart=self.cart,
                payment_method=method,
                amount_tendered=tendered,
            )
            if self.is_invoice:
                SalesService.finalize_invoice(
                    session,
                    cart=self.cart,
                    payment_method=method,
                    amount_tendered=tendered,
                    notes="",
                    client_id=self.client_id,
                )

        change = max(0.0, tendered - total)
        self._freeze_ticket(method, tendered, change)

    def _freeze_ticket(self, method: str, tendered: float, change: float):
        self.sale_finished = True
        self.cart_table.setProperty("frozen", "true")
        self.cart_table.style().unpolish(self.cart_table)
        self.cart_table.style().polish(self.cart_table)
        self.combined_input.clear()

        method_label = {
            "cash": "Cash", "card": "Card",
            "bancontact": "Bancontact", "meal_voucher": "Meal voucher",
        }.get(method, method.title())
        parts = [f"PAID BY  {method_label}", f"{self.currency}{tendered:.2f}"]
        if change > 0:
            parts.append(f"Change: {self.currency}{change:.2f}")
        self.payment_label.setText("    |    ".join(parts))
        self.input_stack.setCurrentIndex(1)
        self.cart_table.setFocus()

    def _unfreeze_ticket(self):
        self.sale_finished = False
        self.cart.clear()
        self.cart.global_discount = 0.0
        self.cart_table.setProperty("frozen", "false")
        self.cart_table.style().unpolish(self.cart_table)
        self.cart_table.style().polish(self.cart_table)
        self.input_stack.setCurrentIndex(0)
        self._refresh_cart()

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
            self._refresh_cart()

    def _read_amount_input(self) -> float | None:
        text = self.combined_input.text().strip().replace(",", ".")
        if not text:
            return None
        try:
            return max(0.0, float(text))
        except ValueError:
            return None

    def _admin(self):
        if self.isAdmin:
            self.isAdmin = False
            self.salesperson_changed.emit(self.cashier_name)
            return
        dialog = NumpadDialog(title="Enter Code", parent=self)
        if dialog.exec():
            if dialog.value == ADMIN_CODE:
                self.isAdmin = True
                self.salesperson_changed.emit("Admin")

    def _show_overlay(self, message: str, title: str = "", kind: str = "info"):
        self.overlay.show_message(message, title=title, kind=kind)

    def _show_discount(self, value: float, amount: float, pct_or_curr: str):
        row = self.cart_table.rowCount()
        self.cart_table.insertRow(row)
        discount = [
            QTableWidgetItem(""),
            QTableWidgetItem("DISCOUNT  " + str(value) + pct_or_curr),
            QTableWidgetItem(""),
            QTableWidgetItem("-" + str(round(amount, 2))),
        ]
        font = QFont()
        font.setBold(True)
        for col, item in enumerate(discount):
            item.setFont(font)
            item.setBackground(QBrush(QColor(145, 230, 120)))
            self.cart_table.setItem(row, col, item)
        self.cart_table.setRowHeight(row, 25)

    def set_client(self, client_id: int, client_name: str):
        if client_id and client_name:
            if self.sale_finished:
                self._unfreeze_ticket()
            self.client_label.setText("INVOICE - " + client_name)
            self.client_label.setVisible(True)
            self.client_id = client_id
            self.is_invoice = True
            self._refresh_cart(select_last=True)
        self.combined_input.setFocus()

    def add_product_by_id(self, product_id: int):
        with get_session() as session:
            product = ProductService.get_by_id(session, product_id)
            if product:
                if self.sale_finished:
                    self._unfreeze_ticket()
                self.cart.add_product(product)
                self._refresh_cart(select_last=True)

    def _emit_signal(self, signal: int):
        if signal == 4 and not self.isAdmin:
            self._show_overlay("Only Admin", title="No Permission", kind="error")
            return
        self.navigate.emit(signal)
