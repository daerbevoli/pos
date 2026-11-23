"""
Customer Display
Customer-facing window that continuously mirrors the active POS ticket
panel
Fed by POSScreen.display_changed; opens full screen on a second monitor
when one is connected, otherwise as a normal window toggled from Settings.
"""
from PyQt6.QtCore import QItemSelectionModel, Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QFont, QGuiApplication
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.constants import (
    CART_INFO_BAR_HEIGHT,
    CART_ROW_HEIGHT,
    CUSTOMER_DISPLAY_WINDOW_SIZE,
    FONT_SIZE_CART,
    FONT_SIZE_PAID_FOOTER,
    SPACING_XS,
)
from app.ui.pos_screen import size_cart_columns


class CustomerDisplay(QWidget):
    def __init__(self, parent=None):
        # A separate top-level window, but parented so it closes with the main window.
        super().__init__(parent, Qt.WindowType.Window)
        self.setObjectName("customerDisplay")
        self.setWindowTitle("Customer Display")
        self.resize(*CUSTOMER_DISPLAY_WINDOW_SIZE)
        self._build_ui()

    def _build_ui(self):
        col = QVBoxLayout(self)
        col.setContentsMargins(SPACING_XS, SPACING_XS, SPACING_XS, SPACING_XS)
        col.setSpacing(SPACING_XS)

        self.header_widget = QWidget()
        self.header_widget.setObjectName("header")
        header_layout = QHBoxLayout(self.header_widget)
        header_layout.setContentsMargins(8, 4, 8, 4)
        self.ticket_title = QLabel()
        self.ticket_title.setObjectName("ticketTitle")
        self.ticket_date = QLabel()
        self.ticket_date.setObjectName("ticketDate")
        header_layout.addWidget(self.ticket_title)
        header_layout.addStretch()
        header_layout.addWidget(self.ticket_date)
        col.addWidget(self.header_widget)

        self.client_label = QLabel()
        self.client_label.setObjectName("clientLabel")
        self.client_label.setMinimumHeight(CART_INFO_BAR_HEIGHT)
        self.client_label.hide()
        col.addWidget(self.client_label)

        self.cart_table = QTableWidget(0, 4)
        self.cart_table.setObjectName("cartTable")
        hh = self.cart_table.horizontalHeader()
        hh.hide()
        size_cart_columns(self.cart_table)
        self.cart_table.verticalHeader().hide()
        self.cart_table.verticalHeader().setMinimumSectionSize(0)  # else Windows raises rows to 24px, see POSScreen
        self.cart_table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.cart_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.cart_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.cart_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.cart_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        col.addWidget(self.cart_table, stretch=1)

        self.cart_input = QLineEdit()
        self.cart_input.setObjectName("cartInput")
        self.cart_input.setMinimumHeight(CART_INFO_BAR_HEIGHT)
        self.cart_input.setReadOnly(True)
        self.cart_input.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.payment_footer = QWidget()
        self.payment_footer.setObjectName("paymentFooter")
        self.payment_footer.setMinimumHeight(CART_INFO_BAR_HEIGHT)
        fl = QHBoxLayout(self.payment_footer)
        fl.setContentsMargins(5, 2, 5, 2)
        footer_font = QFont()
        footer_font.setBold(True)
        footer_font.setPixelSize(FONT_SIZE_PAID_FOOTER)
        self.footer_total_lbl = QLabel()
        self.footer_total_lbl.setObjectName("footerTotalLabel")
        self.footer_change_lbl = QLabel()
        self.footer_change_lbl.setObjectName("footerChangeLabel")
        for lbl in (self.footer_total_lbl, self.footer_change_lbl):
            lbl.setFont(footer_font)
        fl.addWidget(self.footer_total_lbl)
        fl.addStretch()
        fl.addWidget(self.footer_change_lbl)

        self.input_stack = QStackedWidget()
        self.input_stack.addWidget(self.cart_input)
        self.input_stack.addWidget(self.payment_footer)

        self.ticket_total_lbl = QLabel()
        self.ticket_total_lbl.setObjectName("ticketTotalLbl")
        self.ticket_total_lbl.setMinimumHeight(CART_INFO_BAR_HEIGHT)
        self.ticket_total_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        input_row = QHBoxLayout()
        input_row.addWidget(self.input_stack, stretch=1)
        input_row.addWidget(self.ticket_total_lbl)
        col.addLayout(input_row)

    # ── Placement ─────────────────────────────────────────────────────────

    @staticmethod
    def secondary_screen(main_window: QWidget):
        """The first connected screen the main window isn't on, if any."""
        main_screen = main_window.screen()
        return next((s for s in QGuiApplication.screens() if s is not main_screen), None)

    def show_on(self, screen):
        """Full screen on `screen` (a customer-facing monitor)."""
        self.setGeometry(screen.geometry())
        self.showFullScreen()

    def toggle(self, main_window: QWidget):
        if self.isVisible():
            self.hide()
            return
        screen = self.secondary_screen(main_window)
        if screen is not None:
            self.show_on(screen)
        else:
            self.showNormal()
            self.raise_()

    # ── Content ───────────────────────────────────────────────────────────

    def _set_frozen_style(self, frozen: bool):
        for widget in (self.cart_table, self.client_label, self.header_widget,
                       self.ticket_title, self.ticket_date, self.cart_input, self.ticket_total_lbl):
            widget.setProperty("frozen", frozen)
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def update_ticket(self, state: dict):
        """Slot for POSScreen.display_changed — see POSScreen.emit_display()
        for the keys of `state`."""
        self._set_frozen_style(state["frozen"])
        self.ticket_title.setText(state["title"])
        self.ticket_date.setText(state["date"])
        self.client_label.setText(state["client"])
        self.client_label.setVisible(bool(state["client"]))

        self.input_stack.setCurrentIndex(state["input_page"])
        self.footer_total_lbl.setText(state["footer_total"])
        self.footer_change_lbl.setText(state["footer_change"])
        self.ticket_total_lbl.setText(state["total"])
        self.ticket_total_lbl.setVisible(state["total_visible"])

        rows = state["rows"]
        self.cart_table.setRowCount(len(rows))
        fonts = {}
        for bold in (False, True):
            font = QFont()
            font.setPixelSize(FONT_SIZE_CART)
            font.setBold(bold)
            fonts[bold] = font
        for r, row in enumerate(rows):
            brush = QBrush(QColor(*row["background"])) if row["background"] else None
            for c, text in enumerate(row["texts"]):
                cell = QTableWidgetItem(text)
                cell.setFont(fonts[row["bold"]])
                if brush is not None:
                    cell.setBackground(brush)
                self.cart_table.setItem(r, c, cell)
            self.cart_table.setRowHeight(r, 3 if row["divider"] else CART_ROW_HEIGHT)
        selected = state["selected_row"]
        self.cart_table.clearSelection()
        if selected is not None:
            self.cart_table.selectionModel().select(
                self.cart_table.model().index(selected, 0),
                QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows,
            )
        target = len(rows) - 1 if selected is None else selected
        if target >= 0:
            self.cart_table.scrollTo(self.cart_table.model().index(target, 0))
            QTimer.singleShot(0, lambda: self._scroll_to(target))

    def _scroll_to(self, row: int):
        if row < self.cart_table.rowCount():
            self.cart_table.scrollTo(self.cart_table.model().index(row, 0))
