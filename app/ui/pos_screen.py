"""
POS Screen
Grid-button touchscreen layout: ticket list, function grid,
payment row, and a numpad + category/product grid.
Tab state (cart, frozen, client) is managed per V-tab slot and
driven externally by MainWindow via set_active_tab().
"""
import datetime
import json

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QLabel,
    QHeaderView, QMessageBox, QSizePolicy, QStackedWidget
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QRegularExpression
from PyQt6.QtGui import QFont, QBrush, QColor, QRegularExpressionValidator

from app.core.database import get_session
from app.core.product_service import ProductService
from app.core.sales_service import Cart, CartItem, SubtotalMarker, DiscountEntry, PaymentEntry, SalesService
from app.models.models import Sale, Invoice
from app.core.settings_service import SettingsService
from app.core.receipt_service import PrinterError, ReceiptService
from app.utils.utils import CategoryButton, FunctionButton, TapToDismissOverlay, TicketTable
from app.constants import (
    BUTTON_HEIGHT_COMPACT,
    CART_LABEL_HEIGHT,
    COLOR_ROW_DISCOUNT,
    COLOR_ROW_DIVIDER,
    COLOR_ROW_PAYMENT,
    COLOR_ROW_PAYMENT_DARK,
    COLOR_ROW_PENDING,
    FONT_SIZE_CART_ITEM,
    FONT_SIZE_CART_ROW,
    FONT_SIZE_FOOTER_TOTAL,
    ROW_HEIGHT_COMPACT,
    SPACING_SM,
    SPACING_XS,
)


from datetime import date

ADMIN_CODE = "2060"
WEIGHT_UNITS = {"kg", "g", "ml", "l"}


class _TabState:
    """Snapshot of one V-tab slot's POS state."""
    def __init__(self):
        self.cart             = Cart()
        self.sale_finished    = True
        self.is_invoice       = False
        self.client_id        = None
        self.client_name      = ""
        self.ticket_date_text = ""
        self.frozen_breakdown = []
        self.frozen_change    = 0.0
        self.frozen_total     = 0.0
        self.sale_id          = None   # DB Sale.id this frozen ticket was saved as, if any
        self.sale_ids         = []
        self.sales            = -1


class POSScreen(QWidget):
    navigate           = pyqtSignal(int)   # ask MainWindow to switch screen
    salesperson_changed = pyqtSignal(str)  # cashier name update for header
    tab_updated        = pyqtSignal(int, str)  # (vtab_idx, amount_str) for tab button

    isAdmin = False

    def __init__(self):
        super().__init__()
        self._tab_states: dict[int, _TabState] = {i: _TabState() for i in range(1, 6)}
        self._active_tab = 1
        self.cart             = self._tab_states[1].cart
        self.sale_finished    = True
        self.is_invoice       = False
        self.client_id        = None
        self._frozen_breakdown = []
        self._frozen_change   = 0.0
        self._frozen_total    = 0.0
        self._row_to_entry    = []     # cart_table row -> cart.entries index (None for divider/summary rows)
        self._current_sale_id = None   # DB Sale.id this tab's frozen ticket was saved as, if any
        self.sale_ids         = []     # all of today's completed sale ids, chronological, shared across tabs
        self.sales            = -1     # index into sale_ids: browse cursor / index of most recent sale

        self.overlay = TapToDismissOverlay(self)
        self._load_settings()
        self._build_ui()
        self._start_time_display()
        self._clear_cart(override=True)

    @property
    def cart_active(self) -> bool:
        return bool(self.cart.entries) or self.is_invoice

    @property
    def payment_in_progress(self) -> bool:
        """True once a partial tender has been taken but the sale isn't fully paid yet."""
        return not self.sale_finished and self.cart.paid_total > 0

    @property
    def reopened_ticket(self) -> bool:
        """True while editing a ticket reopened from a completed sale, awaiting re-payment."""
        return not self.sale_finished and self._current_sale_id is not None

    def _guard_payment_in_progress(self) -> bool:
        """Blocks cart-mutating actions while a partial payment is outstanding.
        Returns True (and shows an overlay) if the action should be blocked."""
        if self.payment_in_progress:
            self._show_overlay("Finish or remove the pending payment first", kind="error")
            return True
        return False

    def _guard_reopened_ticket(self) -> bool:
        """Blocks quantity changes on a reopened ticket.
        Returns True (and shows an overlay) if the action should be blocked."""
        if self.reopened_ticket:
            return True
        return False

    # ── Setup ────────────────────────────────────────────────────────────

    def _load_settings(self):
        with get_session() as session:
            settings = SettingsService.get_all(session)
            sales = SalesService.get_sales_for_date(session, date.today())
            self.sale_ids = [sale.id for sale in reversed(sales)]  # oldest first
            self.sales = len(self.sale_ids) - 1  # cursor starts on the most recent sale
        self.currency     = settings.get("currency_symbol", "€")
        self.cashier_name = settings.get("cashier_name", "Cashier")

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(SPACING_SM)

        body = QHBoxLayout()
        body.setSpacing(SPACING_SM)
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

    def _tick_time(self, override: bool = False):
        # No time ticking at finished (frozen) sale
        if self.sale_finished and not override:
            return
        self.ticket_date.setText(
            datetime.datetime.now().strftime("%d-%m-%Y %H:%M")
        )
    # ── Left: ticket header + cart table ────────────────────────────────

    def _build_ticket_panel(self):
        col = QVBoxLayout()
        col.setSpacing(SPACING_XS)

        self.header_widget = QWidget()
        self.header_widget.setObjectName("header")

        header_layout = QHBoxLayout(self.header_widget)
        header_layout.setContentsMargins(8, 4, 8, 4)

        self.ticket_title = QLabel(f"V {self._active_tab}")
        self.ticket_title.setObjectName("ticketTitle")
        self.ticket_date = QLabel("")
        self.ticket_date.setObjectName("ticketDate")

        header_layout.addWidget(self.ticket_title)
        header_layout.addStretch()
        header_layout.addWidget(self.ticket_date)

        col.addWidget(self.header_widget)

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
        self.client_label.setMinimumHeight(CART_LABEL_HEIGHT)
        self.client_label.hide()
        col.addWidget(self.client_label)

        self.cart_table.backspace_pressed.connect(self._remove_selected)
        self.cart_table.enter_pressed.connect(self._on_barcode_enter)
        self.cart_table.text_entered.connect(self._on_ticket_text)

        col.addWidget(self.cart_table, stretch=1)

        self.ticket_total_lbl = QLabel("")
        self.ticket_total_lbl.setObjectName("ticketTotalLbl")
        self.ticket_total_lbl.setMinimumHeight(CART_LABEL_HEIGHT)
        self.ticket_total_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.combined_input = QLineEdit()
        self.combined_input.setObjectName("combinedInput")
        self.combined_input.setMinimumHeight(CART_LABEL_HEIGHT)
        self.combined_input.setValidator(
            QRegularExpressionValidator(QRegularExpression(r'-?[0-9]*[.,]?[0-9]*'))
        )
        self.combined_input.returnPressed.connect(self._on_barcode_enter)

        self.payment_footer = QWidget()
        self.payment_footer.setObjectName("paymentFooter")
        self.payment_footer.setMinimumHeight(CART_LABEL_HEIGHT)
        _fl = QHBoxLayout(self.payment_footer)
        _fl.setContentsMargins(10, 4, 10, 4)
        self.footer_total_lbl  = QLabel()
        self.footer_change_lbl = QLabel()
        _footer_font = QFont()
        _footer_font.setBold(True)
        _footer_font.setPixelSize(FONT_SIZE_FOOTER_TOTAL)
        self.footer_total_lbl.setFont(_footer_font)
        self.footer_change_lbl.setFont(_footer_font)
        self.footer_total_lbl.setObjectName("footerTotalLabel")
        self.footer_change_lbl.setObjectName("footerChangeLabel")
        _fl.addWidget(self.footer_total_lbl)
        _fl.addStretch()
        _fl.addWidget(self.footer_change_lbl)

        self.input_stack = QStackedWidget()
        self.input_stack.addWidget(self.combined_input)
        self.input_stack.addWidget(self.payment_footer)

        self.input_row = QHBoxLayout()
        self.input_row.addWidget(self.input_stack, stretch=1)
        self.input_row.addWidget(self.ticket_total_lbl)
        col.addLayout(self.input_row)

        return col

    # ── Right: function-key grid ─────────────────────────────────────────

    def _build_control_grid(self):
        col = QVBoxLayout()
        col.setSpacing(SPACING_XS)

        grid = QGridLayout()
        grid.setSpacing(SPACING_XS)

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

            (self.btn_client, 4, 2, 1, 1),
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
        pay_grid.setSpacing(SPACING_XS)

        self.btn_card         = FunctionButton("card", "cashBtn")
        self.btn_subtotal     = FunctionButton("Subtotal", "subtotalBtn")
        self.btn_cash         = FunctionButton("Cash", "cashBtn")

        pay_grid.addWidget(self.btn_card, 0, 0, 2, 1)
        pay_grid.addWidget(self.btn_subtotal, 0, 1, 2, 1)
        pay_grid.addWidget(self.btn_cash, 0, 2, 2, 1)
        pay_grid.setColumnStretch(0, 1)
        pay_grid.setColumnStretch(1, 1)
        pay_grid.setColumnStretch(2, 1)

        col.addLayout(pay_grid, stretch=2)

        # Wire up
        self.btn_reopen.clicked.connect(self._reopen_ticket)
        self.btn_plus.clicked.connect(self._increase_product)
        self.btn_minus.clicked.connect(self._decrease_product)
        self.btn_clear.clicked.connect(self._clear_cart)
        self.btn_error.clicked.connect(self._remove_selected)
        self.btn_subtotal.clicked.connect(self._show_subtotal)
        self.btn_cash.clicked.connect(lambda: self._open_payment("cash"))
        self.btn_card.clicked.connect(lambda: self._open_payment("card"))
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

        self.btn_left.clicked.connect(self._previous_sale)
        self.btn_right.clicked.connect(self._next_sale)

        self.btn_print_ticket.clicked.connect(self._print_ticket)
        self.btn_print_invoice.clicked.connect(self._print_invoice)
        self.btn_drawer.clicked.connect(self._open_drawer)

        return col



    # ── Bottom: numpad + category/product grid ───────────────────────────

    def _build_bottom_grid(self):
        row = QHBoxLayout()
        row.setSpacing(SPACING_XS)

        self.category_grid = QGridLayout()
        self.category_grid.setSpacing(SPACING_XS)

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
        numpad.setSpacing(SPACING_XS)
        keys = [
            ("7", 0, 0), ("8", 0, 1), ("9", 0, 2),
            ("4", 1, 0), ("5", 1, 1), ("6", 1, 2),
            ("1", 2, 0), ("2", 2, 1), ("3", 2, 2),
            ("0", 3, 0), (".", 3, 1), ("⌫", 3, 2),
        ]
        for label, r, c in keys:
            btn = QPushButton(label)
            btn.setObjectName("numKey" if label != "⌫" else "numKeyDel")
            btn.setMinimumHeight(BUTTON_HEIGHT_COMPACT)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
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
        s.cart             = self.cart
        s.sale_finished    = self.sale_finished
        s.is_invoice       = self.is_invoice
        s.client_id        = self.client_id
        s.client_name      = self.client_label.text() if self.client_label.isVisible() else ""
        s.ticket_date_text = self.ticket_date.text() if self.sale_finished else ""
        s.frozen_breakdown = self._frozen_breakdown
        s.frozen_change    = self._frozen_change
        s.frozen_total     = self._frozen_total
        s.sale_id          = self._current_sale_id

    def _load_tab_state(self, idx: int):
        s = self._tab_states[idx]
        self.cart          = s.cart
        self.sale_finished = s.sale_finished
        self.is_invoice    = s.is_invoice
        self.client_id     = s.client_id
        self._current_sale_id = s.sale_id

        if s.client_name:
            self.client_label.setText(s.client_name)
            self.client_label.show()
        else:
            self.client_label.hide()

        # Restore frozen / unfrozen visuals
        self._frozen_breakdown = s.frozen_breakdown or []
        self._frozen_change    = s.frozen_change or 0.0
        self._frozen_total     = s.frozen_total
        self._set_frozen_style(s.sale_finished or not self.cart_active)
        if s.sale_finished:
            self._update_payment_footer()
            self.input_stack.setCurrentIndex(1)
            if s.ticket_date_text:
                self.ticket_date.setText(s.ticket_date_text)
        else:
            self.input_stack.setCurrentIndex(0)

        self.ticket_title.setText(f"V {idx}")
        self._refresh_cart()
        self.cart_table.setFocus()

    # ── Numpad / scan input helpers ──────────────────────────────────────

    def _numpad_press(self, label: str):
        if label == "⌫":
            self.combined_input.setText(self.combined_input.text()[:-1])
        elif label == ".":
            if "." not in self.combined_input.text():
                self.combined_input.insert(".")
        else:
            self.combined_input.insert(label)
        self.cart_table.setFocus()

    # ── Cart interactions ────────────────────────────────────────────────

    def _on_ticket_text(self, text: str):
        if self.sale_finished:
            self._unfreeze_ticket()
        if text in ".,":
            if "." in self.combined_input.text():
                return
            text = "."
        self.combined_input.insert(text)

    def _selected_pending_item(self):
        """The selected CartItem if it's a weight/volume item still awaiting
        its amount (quantity is None), otherwise None."""
        idx = self._get_selected_entry_index()
        if idx is None:
            return None
        entry = self.cart.entries[idx]
        if isinstance(entry, CartItem) and entry.quantity is None:
            return entry
        return None

    def _on_barcode_enter(self):
        if self.sale_finished:
            self._unfreeze_ticket()
        if self._guard_payment_in_progress():
            return

        pending_entry = self._selected_pending_item()
        if pending_entry is not None:
            query = self.combined_input.text().strip()
            # A barcode is always longer than a typed weight/volume amount —
            # treat anything over 6 characters (incl. the decimal point) as
            # an attempted scan and block it until the amount is filled in.
            if len(query) > 6:
                self._show_overlay("Enter the pending amount before scanning another item", kind="info")
                self.combined_input.clear()
                return
            amount = self._read_amount_input()
            if amount is None or amount <= 0:
                self._show_overlay("Enter an valid amount", kind="info")
                return
            pending_entry.quantity = amount
            self.combined_input.clear()
            self._refresh_cart(select_last=True)
            return

        query = self.combined_input.text().strip()
        if not query:
            return

        with get_session() as session:
            product, quantity, quantity_typed = self._resolve_scan(session, query)
            if product:
                if product.unit in WEIGHT_UNITS and not quantity_typed:
                    quantity = None
                self.cart.add_product(product, quantity=quantity)
                self._refresh_cart(select_last=True)
                self.combined_input.clear()
            else:
                self._show_overlay("Unknown barcode", kind="error")
        self.combined_input.clear()

    def _resolve_scan(self, session, query: str):
        """Split combined_input's text into (product, quantity, quantity_typed).

        Barcodes in this catalog are 13 or 14 digits, so a fixed-length split
        can't tell a bare barcode apart from a typed quantity prefix followed
        by one. Try the plain scan first, then peel off a prefix assuming a
        14-digit barcode, then again assuming 13 — whichever actually matches
        a product wins.
        """
        product = ProductService.get_by_barcode(session, query)
        if product:
            return product, 1, False

        for barcode_len in (14, 13):
            if len(query) <= barcode_len:
                continue
            prefix, barcode = query[:-barcode_len], query[-barcode_len:]
            try:
                quantity = int(round(float(prefix)))
            except ValueError:
                continue
            product = ProductService.get_by_barcode(session, barcode)
            if product:
                return product, quantity, True

        return None, 1, False


    def _clear_cart(self, override: bool = False):
        if not override and not self.cart_active:
            return
        if override or QMessageBox.question(self, "Clear cart", "Clear cart?") == QMessageBox.StandardButton.Yes:
            self._frozen_breakdown = []
            self._frozen_change    = 0.0
            self._frozen_total     = 0.0
            self.input_stack.setCurrentIndex(0)
            self.ticket_total_lbl.setVisible(False)
            self.cart.clear()
            self.combined_input.clear()
            self.client_label.setVisible(False)
            self.client_id = None
            self.is_invoice = False
            self._current_sale_id = None
            self._set_frozen_style(True)
            self._refresh_cart()
            self._tick_time(override=True)
            self.sale_finished = True
            self.sales = len(self.sale_ids)
        self.cart_table.setFocus()

    def _remove_selected(self):
        if self.combined_input.text():
            self.combined_input.setText(self.combined_input.text()[:-1])
            return
        if self.sale_finished:
            return
        if not self.cart.entries:
            self._clear_cart(override=True)
            return
        idx = self._get_selected_entry_index()
        if idx is None:
            return
        entry = self.cart.entries[idx]
        if self.payment_in_progress and not isinstance(entry, PaymentEntry):
            self._show_overlay("Finish or remove the pending payment first", kind="error")
            return
        needs_reversal = (
            self._current_sale_id is not None
            and isinstance(entry, CartItem)
            and entry.quantity is not None
            and not entry.is_reversal
        )
        if needs_reversal and entry.has_reversal:
            # Already reversed once — capped at one reversal per line.
            self.cart_table.setFocus()
            return
        if needs_reversal:
            # This ticket was already saved as a completed sale, so the
            # record can't just lose the line — the original row stays put,
            # and a reversal is appended as the newest row instead.
            entry.has_reversal = True
            self.cart.entries.append(CartItem(
                product_id=entry.product_id,
                product_name=entry.product_name,
                product_barcode=entry.product_barcode,
                unit_price=entry.unit_price,
                quantity=-entry.quantity,
                unit=entry.unit,
                discount=-entry.discount,
                is_reversal=True,
                reversal_of=entry,
            ))
        else:
            if isinstance(entry, CartItem) and entry.is_reversal and entry.reversal_of is not None:
                # Removing the reversal itself un-caps the original line
                # so it can be reversed again.
                entry.reversal_of.has_reversal = False
            self.cart.entries.pop(idx)
        self._refresh_cart(select_last=needs_reversal)
        self.cart_table.setFocus()

    def _apply_percent_discount(self):
        if self.sale_finished:
            return
        if self._guard_payment_in_progress():
            return
        value = self._read_amount_input()
        if value is None:
            self._show_overlay("Enter a number first to apply a discount", kind="info")
            return
        base = self._get_discount_base()
        if base is None or base <= 0:
            self._show_overlay("Nothing to discount", kind="error")
            return
        pct = min(value, 100.0)
        amount = round(base * pct / 100.0, 2)
        self.cart.entries.append(DiscountEntry(amount=amount, label=f"{pct:g}%"))
        self.combined_input.clear()
        self._refresh_cart(select_last=True)
        self.cart_table.setFocus()

    def _apply_amount_discount(self):
        if self.sale_finished:
            return
        if self._guard_payment_in_progress():
            return
        value = self._read_amount_input()
        if value is None:
            self._show_overlay("Enter a number first to apply a discount", kind="info")
            return
        base = self._get_discount_base()
        if base is None or base <= 0:
            self._show_overlay("Nothing to discount", kind="error")
            return
        amount = round(min(value, base), 2)
        self.cart.entries.append(DiscountEntry(amount=amount, label=f"{self.currency}{amount:.2f}"))
        self.combined_input.clear()
        self._refresh_cart(select_last=True)
        self.cart_table.setFocus()

    def _get_discount_base(self) -> float | None:
        """
        Returns the amount the next discount applies to:
        - last CartItem's line_total  → item discount
        - last section's net total    → section discount (entry above is SubtotalMarker)
        Existing DiscountEntry rows are skipped when looking back.
        """
        for entry in reversed(self.cart.entries):
            if isinstance(entry, DiscountEntry):
                continue
            if isinstance(entry, CartItem):
                return entry.line_total
            if isinstance(entry, SubtotalMarker):
                return self._last_section_total()
            break
        return None

    def _last_section_total(self) -> float:
        """Net total of items+discounts in the section that ends at the last SubtotalMarker."""
        total = 0.0
        past_last_marker = False
        for entry in reversed(self.cart.entries):
            if isinstance(entry, SubtotalMarker):
                if not past_last_marker:
                    past_last_marker = True
                    continue
                break
            if past_last_marker:
                if isinstance(entry, CartItem):
                    total += entry.line_total
                elif isinstance(entry, DiscountEntry):
                    total -= entry.amount
        return total

    def _show_subtotal(self):
        if self.sale_finished:
            return
        if self._guard_payment_in_progress():
            return
        if not self.cart.entries:
            self._show_overlay(message="Cart empty")
        # Allow subtotal if the current section has at least a CartItem or DiscountEntry
        section_has_content = False
        for entry in reversed(self.cart.entries):
            if isinstance(entry, SubtotalMarker):
                break
            if isinstance(entry, (CartItem, DiscountEntry)):
                section_has_content = True
                break
        if not section_has_content:
            return
        self.cart.add_subtotal()
        self._refresh_cart(select_last=True)
        self.cart_table.setFocus()

    # ── UI refresh ────────────────────────────────────────────────────────

    def _insert_subtotal_row(self, total: float, count: int):
        row = self.cart_table.rowCount()
        self.cart_table.insertRow(row)
        cells = [
            QTableWidgetItem(str(count)),
            QTableWidgetItem("SUBTOTAL"),
            QTableWidgetItem(""),
            QTableWidgetItem(f"{self.currency}{total:.2f}"),
        ]
        font = QFont()
        font.setBold(True)
        font.setPointSize(FONT_SIZE_CART_ROW)
        for col, cell in enumerate(cells):
            cell.setFont(font)
            cell.setBackground(QBrush(QColor(*COLOR_ROW_PENDING)))
            self.cart_table.setItem(row, col, cell)
        self.cart_table.setRowHeight(row, ROW_HEIGHT_COMPACT)

    def _insert_divider_row(self):
        r = self.cart_table.rowCount()
        self.cart_table.insertRow(r)
        for c in range(4):
            cell = QTableWidgetItem("")
            cell.setBackground(QBrush(QColor(*COLOR_ROW_DIVIDER)))
            self.cart_table.setItem(r, c, cell)
        self.cart_table.setRowHeight(r, 3)
        self._row_to_entry.append(None)

    def _refresh_cart(self, select_last=False):
        prev_idx = self._get_selected_entry_index()
        self.cart_table.setRowCount(0)
        self._row_to_entry: list[int | None] = []

        section_total = 0.0
        section_count = 0
        section_has_items = False
        prev_subtotal = 0.0
        payment_divider_shown = False
        font_bold = QFont(); font_bold.setPixelSize(FONT_SIZE_CART_ROW); font_bold.setBold(True)
        font_item = QFont(); font_item.setPixelSize(FONT_SIZE_CART_ITEM); font_item.setBold(False)
        for i, entry in enumerate(self.cart.entries):
            if isinstance(entry, CartItem):
                r = self.cart_table.rowCount()
                self.cart_table.insertRow(r)
                self._row_to_entry.append(i)
                pending = entry.quantity is None
                is_weight = entry.unit in WEIGHT_UNITS
                if is_weight:
                    qty_text = "?" if pending else ("-1" if entry.quantity < 0 else "1")
                    weight_text = "?" if pending else f"{abs(entry.quantity):g}{entry.unit}"
                    name_text = f"{entry.product_name} - {weight_text}"
                    price_text = f"{self.currency}{entry.unit_price:.2f}/{entry.unit}"
                    # A weight article is one line item, not `quantity` kg of them.
                    count_contribution = 0 if pending else (-1 if entry.quantity < 0 else 1)
                else:
                    qty_text = "?" if pending else f"{entry.quantity:g}"
                    name_text = entry.product_name
                    price_text = f"{self.currency}{entry.unit_price:.2f}"
                    count_contribution = entry.quantity or 0
                for col, text in enumerate([
                    qty_text,
                    name_text,
                    price_text,
                    "?" if pending else f"{self.currency}{entry.line_total:.2f}",
                ]):
                    cell = QTableWidgetItem(text)
                    cell.setFont(font_item)
                    if pending:
                        cell.setBackground(QBrush(QColor(*COLOR_ROW_PENDING)))
                    self.cart_table.setItem(r, col, cell)
                self.cart_table.setRowHeight(r, ROW_HEIGHT_COMPACT)
                section_total += entry.line_total
                section_count += count_contribution
                section_has_items = True

            elif isinstance(entry, DiscountEntry):
                r = self.cart_table.rowCount()
                self.cart_table.insertRow(r)
                self._row_to_entry.append(i)
                cells = [
                    QTableWidgetItem(""),
                    QTableWidgetItem(f"DISCOUNT  {entry.label}"),
                    QTableWidgetItem(""),
                    QTableWidgetItem(f"-{self.currency}{entry.amount:.2f}"),
                ]
                for c, cell in enumerate(cells):
                    cell.setFont(font_bold)
                    cell.setBackground(QBrush(QColor(*COLOR_ROW_DISCOUNT)))
                    self.cart_table.setItem(r, c, cell)
                self.cart_table.setRowHeight(r, ROW_HEIGHT_COMPACT)
                section_total += entry.line_total   # negative
            elif isinstance(entry, SubtotalMarker):
                # Discount-only section: show net against the previous subtotal
                display_total = section_total if section_has_items else prev_subtotal + section_total
                self._insert_subtotal_row(display_total, section_count)
                self._row_to_entry.append(i)
                prev_subtotal = display_total
                section_total = 0.0
                section_count = 0
                section_has_items = False

            elif isinstance(entry, PaymentEntry):
                if not payment_divider_shown:
                    self._insert_divider_row()
                    payment_divider_shown = True
                r = self.cart_table.rowCount()
                self.cart_table.insertRow(r)
                self._row_to_entry.append(i)
                method_label = {"cash": "Cash", "card": "Card"}.get(entry.method, entry.method.title())
                cells = [
                    QTableWidgetItem(""),
                    QTableWidgetItem(f"PAID  {method_label}"),
                    QTableWidgetItem(""),
                    QTableWidgetItem(f"-{self.currency}{entry.amount:.2f}"),
                ]
                for c, cell in enumerate(cells):
                    cell.setFont(font_bold)
                    cell.setBackground(QBrush(QColor(*COLOR_ROW_PAYMENT)))
                    self.cart_table.setItem(r, c, cell)
                self.cart_table.setRowHeight(r, ROW_HEIGHT_COMPACT)

        # ── Payment rows (frozen state) ──────────────────────────────────
        if self.sale_finished and self._frozen_breakdown:
            font_pay = QFont(); font_pay.setBold(True); font_pay.setPixelSize(FONT_SIZE_CART_ROW)
            self._insert_divider_row()
            for leg in self._frozen_breakdown:
                r = self.cart_table.rowCount()
                self.cart_table.insertRow(r)
                self._row_to_entry.append(None)
                method_label = {"cash": "Cash", "card": "Card"}.get(leg["method"], leg["method"].title())
                leg_str = f"{leg['amount']:.2f}"
                for ci, text in enumerate(["", method_label, "", leg_str]):
                    cell = QTableWidgetItem(text)
                    cell.setFont(font_pay)
                    cell.setBackground(QBrush(QColor(*COLOR_ROW_PAYMENT)))
                    self.cart_table.setItem(r, ci, cell)
                self.cart_table.setRowHeight(r, ROW_HEIGHT_COMPACT)
            if self._frozen_change > 0:
                r = self.cart_table.rowCount()
                self.cart_table.insertRow(r)
                self._row_to_entry.append(None)
                change_str = f"-{self._frozen_change:.2f}"
                for ci, text in enumerate(["", "Change", "", change_str]):
                    cell = QTableWidgetItem(text)
                    cell.setFont(font_pay)
                    cell.setBackground(QBrush(QColor(*COLOR_ROW_PAYMENT_DARK)))
                    self.cart_table.setItem(r, ci, cell)
                self.cart_table.setRowHeight(r, ROW_HEIGHT_COMPACT)

        # ── Row selection ────────────────────────────────────────────────
        if select_last or not self.cart.entries or self.sale_finished:
            self.cart_table.selectRow(self.cart_table.rowCount() - 1)
        elif prev_idx is not None and prev_idx in self._row_to_entry:
            self.cart_table.selectRow(self._row_to_entry.index(prev_idx))
        else:
            self.cart_table.selectRow(self.cart_table.rowCount() - 1)

        # ── Tab button label ─────────────────────────────────────────────
        remaining = self.cart.remaining_due
        amount = f"{remaining:.2f}" if self.cart.entries and not self.sale_finished else ""
        self.tab_updated.emit(self._active_tab, amount)

        # ── Running total (always visible, independent of frozen state) ──
        if self.sale_finished:
            self.ticket_total_lbl.setText("")
        else:
            label = "Remaining" if self.cart.paid_total > 0 else "Total"
            self.ticket_total_lbl.setText(f"{label}  {self.currency}{remaining:.2f}")

    def _move_selection(self, delta: int):
        if self.sale_finished:
            return
        row = self.cart_table.currentRow()
        new_row = max(0, min(self.cart_table.rowCount() - 1, row + delta))
        self.cart_table.selectRow(new_row)

    # ── Payment ───────────────────────────────────────────────────────────

    def _open_payment(self, method: str):
        if self.sale_finished:
            self._show_overlay("No sale")
            return
        if not any(isinstance(e, CartItem) for e in self.cart.entries):
            self._show_overlay("Add items before payment", kind="error")
            return
        if any(isinstance(e, CartItem) and e.quantity is None for e in self.cart.entries):
            self._show_overlay("Fill in the amount for pending items first", kind="error")
            return

        total     = self.cart.total
        remaining = self.cart.remaining_due
        typed     = self._read_amount_input()
        tendered  = round(remaining if typed is None else typed, 2)

        if tendered <= 0:
            self._show_overlay("Enter an amount first", kind="error")
            return

        if tendered + 0.005 < remaining:
            # Underpayment: merge into this method's running partial tender
            # (one row per method, not one row per tap of Cash/Card).
            existing = next((e for e in self.cart.entries if isinstance(e, PaymentEntry) and e.method == method), None)
            if existing is not None:
                existing.amount = round(existing.amount + tendered, 2)
            else:
                self.cart.entries.append(PaymentEntry(method=method, amount=tendered))
            self.combined_input.clear()
            self._refresh_cart(select_last=True)
            self.cart_table.setFocus()
            return

        # Enough to cover what's left — fold every method's contribution into
        # one breakdown row per method, for persistence and the receipt.
        prior_payments = [e for e in self.cart.entries if isinstance(e, PaymentEntry)]
        total_tendered = round(sum(p.amount for p in prior_payments) + tendered, 2)
        methods_used = {p.method for p in prior_payments} | {method}
        final_method = method if len(methods_used) == 1 else "mixed"

        breakdown = [{"method": p.method, "amount": p.amount} for p in prior_payments]
        existing_final = next((b for b in breakdown if b["method"] == method), None)
        if existing_final is not None:
            existing_final["amount"] = round(existing_final["amount"] + tendered, 2)
        else:
            breakdown.append({"method": method, "amount": round(tendered, 2)})

        self.cart.entries = [e for e in self.cart.entries if not isinstance(e, PaymentEntry)]

        with get_session() as session:
            if self._current_sale_id is not None:
                # Re-paying a reopened ticket: overwrite the existing sale in place.
                sale = SalesService.update_sale(
                    session,
                    sale_id=self._current_sale_id,
                    cart=self.cart,
                    payment_method=final_method,
                    amount_tendered=total_tendered,
                    payment_breakdown=breakdown,
                )
                self._current_sale_id = sale.id
            elif self.is_invoice:
                invoice = SalesService.finalize_invoice(
                    session,
                    cart=self.cart,
                    payment_method=final_method,
                    amount_tendered=total_tendered,
                    notes="Invoice",
                    client_id=self.client_id,
                    payment_breakdown=breakdown,
                )
                self._current_sale_id = invoice.sale_id
                self.sale_ids.append(invoice.sale_id)
                self.sales = len(self.sale_ids) - 1
            else:
                sale = SalesService.finalize_sale(
                    session,
                    cart=self.cart,
                    payment_method=final_method,
                    amount_tendered=total_tendered,
                    payment_breakdown=breakdown,
                )
                self._current_sale_id = sale.id
                self.sale_ids.append(sale.id)
                self.sales = len(self.sale_ids) - 1
        change = max(0.0, total_tendered - total)
        self._freeze_ticket(breakdown, change)

    def _set_frozen_style(self, frozen: bool):
        for widget in (self.cart_table, self.client_label, self.header_widget, self.ticket_title, self.ticket_date, self.combined_input, self.ticket_total_lbl):
            widget.setProperty("frozen", frozen)
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def _freeze_ticket(self, breakdown: list[dict], change: float):
        self.sale_finished     = True
        self._frozen_breakdown = breakdown
        self._frozen_change    = change
        self._frozen_total     = self.cart.total
        self._set_frozen_style(True)
        self.combined_input.clear()
        self._update_payment_footer()
        self.input_stack.setCurrentIndex(1)
        self._refresh_cart(select_last=True)
        self.ticket_total_lbl.setVisible(False)
        self._open_drawer()
        self.cart_table.setFocus()

    def _update_payment_footer(self):
        total_str = f"{self._frozen_total:.2f}"
        self.footer_total_lbl.setText(f"Total  {total_str}")
        if self._frozen_change > 0:
            change_str = f"{self._frozen_change:.2f}"
            self.footer_change_lbl.setText(f"Change  -{change_str}")
        else:
            self.footer_change_lbl.setText("")

    def _unfreeze_ticket(self):
        self.sale_finished     = False
        self._frozen_breakdown = []
        self._frozen_change    = 0.0
        self._frozen_total     = 0.0
        self._current_sale_id = None
        self.cart.clear()
        self._set_frozen_style(False)
        self.input_stack.setCurrentIndex(0)
        self._refresh_cart()
        self.ticket_total_lbl.setVisible(True)
        self.cart_table.setFocus()

    def _reopen_ticket(self):
        """Make the tab's just-frozen sale editable again, reloaded from its DB snapshot."""
        if not self.sale_finished or self._current_sale_id is None:
            return
        with get_session() as session:
            sale = session.query(Sale).filter_by(id=self._current_sale_id).first()
            if not sale:
                self._show_overlay("Sale not found", kind="error")
                return
            if sale.invoice is not None:
                self._show_overlay(
                    "This sale has already been invoiced and can't be edited.\n"
                    "Issue a credit note for corrections instead", kind="error",
                )
                return
            self.cart.entries = Cart.from_snapshot(sale.cart_snapshot).entries

        self.sale_finished     = False
        self._frozen_breakdown = []
        self._frozen_change    = 0.0
        self._frozen_total     = 0.0
        # self._current_sale_id stays set: next payment overwrites this sale in place.
        self._set_frozen_style(False)
        self.input_stack.setCurrentIndex(0)
        self._refresh_cart()
        self.ticket_total_lbl.setVisible(True)
        self.cart_table.setFocus()

    def _previous_sale(self):
        if self.cart_active and not self.sale_finished:
            self._show_overlay("Sale active", kind="info")
            return
        if not self.sale_ids:
            self._show_overlay("No earlier sales", kind="info")
            return
        if self.sales <= 0:
            self._show_overlay("No earlier sales", kind="info")
            return
        self._show_sale_at(self.sales - 1)
        self.cart_table.setFocus()

    def _next_sale(self):
        if self.cart_active and not self.sale_finished:
            self._show_overlay("Sale active", kind="info")
            return
        if not self.sale_finished:
            self._show_overlay("No later sales", kind="info")
            return
        if self.sales >= len(self.sale_ids) - 1:
            self._show_overlay("No later sales", kind="info")
            return
        self._show_sale_at(self.sales + 1)
        self.cart_table.setFocus()

    def _show_sale_at(self, index: int):
        self.sales = index
        self._current_sale_id = self.sale_ids[self.sales]

        with get_session() as session:
            sale = session.query(Sale).filter_by(id=self._current_sale_id).first()
            if not sale:
                self._show_overlay("Sale not found", kind="error")
                return
            if sale.invoice:
                self.client_label.setText("INVOICE - " + sale.invoice.client_name)
                self.client_label.show()
            else:
                self.client_label.hide()
            self.cart.entries = Cart.from_snapshot(sale.cart_snapshot).entries

        self.sale_finished     = True
        if sale.payment_breakdown:
            self._frozen_breakdown = json.loads(sale.payment_breakdown)
        else:
            self._frozen_breakdown = [{"method": sale.payment_method, "amount": sale.amount_tendered or 0.0}]
        self._frozen_change    = sale.change_given or 0.0
        self._frozen_total     = sale.total_amount
        self._set_frozen_style(True)
        self._update_payment_footer()
        self.input_stack.setCurrentIndex(1)
        self.ticket_date.setText(sale.created_at.strftime("%d-%m-%Y %H:%M"))
        self._refresh_cart()


    def _print_ticket(self):
        if self._current_sale_id is None:
            self._show_overlay("No ticket to print", kind="error")
            return
        with get_session() as session:
            sale = session.query(Sale).filter_by(id=self._current_sale_id).first()
            if not sale:
                self._show_overlay("Sale not found", kind="error")
                return
            try:
                ReceiptService.print_receipt(session, sale)
            except PrinterError as e:
                self._show_overlay(str(e), kind="error")

    def _print_invoice(self):
        if self._current_sale_id is None:
            self._show_overlay("No ticket to print", kind="error")
            return
        with get_session() as session:
            sale = session.query(Sale).filter_by(id=self._current_sale_id).first()
            if not sale or not sale.invoice:
                self._show_overlay("This sale has no invoice", kind="error")
                return
            try:
                ReceiptService.print_invoice(session, sale.invoice)
            except PrinterError as e:
                self._show_overlay(str(e), kind="error")

    def _open_drawer(self):
        with get_session() as session:
            try:
                ReceiptService.open_drawer(session)
            except PrinterError as e:
                self._show_overlay(str(e), kind="error")

    def _get_selected_entry_index(self) -> int | None:
        """Index into cart.entries for the selected row; None for divider/non-entry rows."""
        if self.sale_finished:
            return None
        row = self.cart_table.currentRow()
        row_map = getattr(self, "_row_to_entry", None)
        if row < 0 or not row_map or row >= len(row_map):
            return None
        return row_map[row]

    def _get_selected_product_id(self):
        idx = self._get_selected_entry_index()
        if idx is None:
            return None
        entry = self.cart.entries[idx]
        return entry.product_id if isinstance(entry, CartItem) else None

    def _increase_product(self):
        if self._guard_payment_in_progress() or self._guard_reopened_ticket():
            return
        idx = self._get_selected_entry_index()
        if idx is None:
            return
        entry = self.cart.entries[idx]
        if isinstance(entry, CartItem) and entry.quantity is not None and not entry.is_reversal and not entry.has_reversal:
            if entry.unit in WEIGHT_UNITS:
                return
            entry.quantity += 1
            self._refresh_cart()

    def _decrease_product(self):
        if self._guard_payment_in_progress() or self._guard_reopened_ticket():
            return
        idx = self._get_selected_entry_index()
        if idx is None:
            return
        entry = self.cart.entries[idx]
        if isinstance(entry, CartItem) and entry.quantity is not None and entry.quantity > 1:
            if entry.unit in WEIGHT_UNITS:
                return
            entry.quantity -= 1
            self._refresh_cart()

    def _read_amount_input(self) -> float | None:
        text = self.combined_input.text().strip()
        if not text:
            return None
        try:
            return max(0.0, float(text))
        except ValueError:
            return None

    def _admin(self):
        self.isAdmin = True
        self.salesperson_changed.emit("Admin")
        # if self.isAdmin:
        #     self.isAdmin = False
        #     self.salesperson_changed.emit(self.cashier_name)
        #     return
        # dialog = NumpadDialog(title="Enter Code", parent=self)
        # if dialog.exec():
        #     if dialog.value == ADMIN_CODE:
        #         self.isAdmin = True
        #         self.salesperson_changed.emit("Admin")

    def _show_overlay(self, message: str, title: str = "", kind: str = "info"):
        self.overlay.show_message(message, kind=kind)

    def set_client(self, client_id: int, client_name: str):
        if client_id and client_name:
            if self.sale_finished:
                self._unfreeze_ticket()
            self.client_label.setText("INVOICE - " + client_name)
            self.client_label.show()
            self.client_id = client_id
            self.is_invoice = True
            self._refresh_cart(select_last=True)
        self.cart_table.setFocus()

    def add_product_by_id(self, product_id: int):
        if self._guard_payment_in_progress():
            return
        if self._selected_pending_item() is not None:
            self._show_overlay("Enter the pending amount before adding another item", kind="info")
            return

        query = self.combined_input.text().strip()
        quantity_typed = bool(query)
        quantity = int(round(float(query))) if quantity_typed else 1

        with get_session() as session:
            product = ProductService.get_by_id(session, product_id)
            if product:
                if self.sale_finished:
                    self._unfreeze_ticket()
                if product.unit in WEIGHT_UNITS and not quantity_typed:
                    quantity = None
                self.cart.add_product(product, quantity=quantity)
                self._refresh_cart(select_last=True)
        self.combined_input.clear()

    def _emit_signal(self, signal: int):
        if signal == 4 and not self.isAdmin:
            self._show_overlay("Only Admin", kind="error")
            return
        self.navigate.emit(signal)
