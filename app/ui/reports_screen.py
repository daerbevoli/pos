"""
Reports Screen
- Daily summary of sales and current and previous invoices
- Vat breakdown, category breakdown
- X report and Z report.
"""
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QLabel, QHeaderView,
    QDateEdit, QGroupBox, QGridLayout, QSizePolicy, QButtonGroup
)
from PyQt6.QtCore import Qt, QDate, pyqtSignal

from PyQt6.QtWidgets import QMessageBox

from app.core.database import get_session
from app.core.sales_service import SalesService
from app.core.settings_service import SettingsService
from app.core.receipt_service import ReceiptService, PrinterError
from app.core.report_service import XZReportService
from app.utils.utils import FunctionButton
from app.constants import BUTTON_HEIGHT, ROW_HEIGHT


class ReportsScreen(QWidget):

    # Navigate across screens
    navigate = pyqtSignal(int)

    # Send selected sale id to pos to display
    sale_selected = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self._build_ui()
        self._load_today()

        self.invoices_only = False

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # ── Date range controls ───────────────────────────────────────────────
        controls = QHBoxLayout()

        controls.addWidget(QLabel("From:"))
        self.date_from = QDateEdit(QDate.currentDate())
        self.date_from.setCalendarPopup(True)
        self.date_from.setFixedHeight(BUTTON_HEIGHT)
        controls.addWidget(self.date_from)

        controls.addWidget(QLabel("To:"))
        self.date_to = QDateEdit(QDate.currentDate())
        self.date_to.setCalendarPopup(True)
        self.date_to.setFixedHeight(BUTTON_HEIGHT)
        controls.addWidget(self.date_to)

        # Quick range presets — mutually exclusive, like the Sales/VAT/
        # Categories trio below: only one is ever "pressed" at a time.
        self._range_group = QButtonGroup(self)
        self._range_group.setExclusive(True)

        self.today_btn = QPushButton("Today")
        self.today_btn.setObjectName("salesBtn")
        self.today_btn.setCheckable(True)
        self.today_btn.setChecked(True)
        self.today_btn.setFixedHeight(BUTTON_HEIGHT)
        self.today_btn.clicked.connect(lambda: self._set_range(0))
        self._range_group.addButton(self.today_btn)
        controls.addWidget(self.today_btn)

        last_7_days_btn = QPushButton("Last 7 days")
        last_7_days_btn.setObjectName("salesBtn")
        last_7_days_btn.setCheckable(True)
        last_7_days_btn.setChecked(False)
        last_7_days_btn.setFixedHeight(BUTTON_HEIGHT)
        last_7_days_btn.clicked.connect(lambda: self._set_range(7))
        self._range_group.addButton(last_7_days_btn)
        controls.addWidget(last_7_days_btn)

        last_30_days_btn = QPushButton("Last 30 days")
        last_30_days_btn.setObjectName("salesBtn")
        last_30_days_btn.setCheckable(True)
        last_30_days_btn.setChecked(False)
        last_30_days_btn.setFixedHeight(BUTTON_HEIGHT)
        last_30_days_btn.clicked.connect(lambda: self._set_range(30))
        self._range_group.addButton(last_30_days_btn)
        controls.addWidget(last_30_days_btn)

        load_btn = QPushButton("Load Report")
        load_btn.setObjectName("primaryBtn")
        load_btn.setFixedHeight(BUTTON_HEIGHT)
        load_btn.clicked.connect(self._load_report)
        controls.addWidget(load_btn)

        # Sales/VAT/Categories are a tab-like, mutually exclusive trio — only
        # one is ever "pressed" (highlighted) at a time. Invoices is a
        # separate on/off filter, so it toggles independently of those three.
        self.sales_btn = FunctionButton("Sales", "salesBtn")
        self.sales_btn.setFixedHeight(BUTTON_HEIGHT)
        self.sales_btn.setCheckable(True)
        self.sales_btn.setChecked(True)
        controls.addWidget(self.sales_btn)

        vat_btn = FunctionButton("VAT breakdown", "salesBtn")
        vat_btn.setFixedHeight(BUTTON_HEIGHT)
        vat_btn.setCheckable(True)
        controls.addWidget(vat_btn)

        cats_btn = FunctionButton("Categories", "salesBtn")
        cats_btn.setFixedHeight(BUTTON_HEIGHT)
        cats_btn.setCheckable(True)
        controls.addWidget(cats_btn)

        self._view_group = QButtonGroup(self)
        self._view_group.setExclusive(True)
        for btn in (self.sales_btn, vat_btn, cats_btn):
            self._view_group.addButton(btn)

        self.invoices_btn = FunctionButton("Invoices", "InvBtn")
        self.invoices_btn.setFixedHeight(BUTTON_HEIGHT)
        self.invoices_btn.setCheckable(True)
        controls.addWidget(self.invoices_btn)

        x_report_btn = FunctionButton("X Report", "XRBtn")
        x_report_btn.setFixedHeight(BUTTON_HEIGHT)
        x_report_btn.clicked.connect(self._print_x_report)
        controls.addWidget(x_report_btn)

        z_report_btn = FunctionButton("Z Report", "ZRBtn")
        z_report_btn.setFixedHeight(BUTTON_HEIGHT)
        z_report_btn.clicked.connect(self._print_z_report)
        controls.addWidget(z_report_btn)

        self.btn_ok = FunctionButton("OK", "okBtn")
        self.btn_ok.setFixedHeight(BUTTON_HEIGHT)
        self.btn_ok.clicked.connect(self._confirm)
        controls.addWidget(self.btn_ok)

        controls.addStretch()
        layout.addLayout(controls)

        # ── Summary cards ─────────────────────────────────────────────────────
        cards_group = QGroupBox("Summary")
        cards_layout = QGridLayout(cards_group)

        self.card_revenue = self._make_card("Total Revenue", "0.00", True)
        self.card_transactions = self._make_card("Transactions", "0")
        self.card_avg = self._make_card("Avg. Transaction", "0.00")
        self.card_cash = self._make_card("Cash Sales", "0.00")
        self.card_card = self._make_card("Card Sales", "0.00")

        cards_layout.addWidget(self.card_revenue, 0, 0)
        cards_layout.addWidget(self.card_transactions, 0, 1)
        cards_layout.addWidget(self.card_avg, 0, 2)
        cards_layout.addWidget(self.card_cash, 0, 3)
        cards_layout.addWidget(self.card_card, 0, 4)

        cards_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout.addWidget(cards_group)

        # ── Sales table ───────────────────────────────────────────────────────
        self._sales_row_ids: dict[int, int] = {}  # table row -> DB Sale.id, rebuilt each _load_report()
        self.sales_table = QTableWidget(0, 8)
        self.sales_table.setObjectName("reportTable")
        self.sales_table.setHorizontalHeaderLabels([
            "Sale #", "Date & Time", "Client name", "VAT number", "Items", "Payment", "Total", "Updated"
        ])
        self.sales_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.sales_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.sales_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.sales_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.sales_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.sales_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.sales_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self.sales_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        self.sales_table.verticalHeader().setVisible(False)
        self.sales_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.sales_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        layout.addWidget(self.sales_table, stretch=1)

        # ── VAT breakdown ─────────────────────────────────────────────────────
        self.vat_table = QTableWidget(0, 4)
        self.vat_table.setObjectName("reportTable")
        self.vat_table.setHorizontalHeaderLabels([
            "Rate", "Base (excl. tax)", "Tax", "Total (incl. tax)"
        ])
        self.vat_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.vat_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.vat_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.vat_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.vat_table.verticalHeader().setVisible(False)
        self.vat_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.vat_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        layout.addWidget(self.vat_table, stretch=1)

        # ── Categories breakdown ─────────────────────────────────────────────
        self.categories_table = QTableWidget(0, 3)
        self.categories_table.setHorizontalHeaderLabels(["Category", "Quantity", "Total Amount"])
        self.categories_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.categories_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.categories_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.categories_table.verticalHeader().setVisible(False)
        self.categories_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.categories_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        layout.addWidget(self.categories_table, stretch=1)

        self.sales_btn.clicked.connect(lambda: self._show_table("sales"))
        self.invoices_btn.clicked.connect(self._invoices_only)
        vat_btn.clicked.connect(lambda: self._show_table("vat"))
        cats_btn.clicked.connect(lambda: self._show_table("categories"))


    def _make_card(self, title: str, value: str, bold: bool = False) -> QGroupBox:
        card = QGroupBox(title)
        card.setObjectName("summaryCard")
        v = QVBoxLayout(card)
        label = QLabel(value)
        label.setObjectName("cardValue")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if bold:
            font = QFont()
            font.setBold(True)
            label.setFont(font)
        v.addWidget(label)
        card._value_label = label
        return card

    def _set_range(self, days: int):
        today = QDate.currentDate()
        self.date_to.setDate(today)
        self.date_from.setDate(today.addDays(-days))
        self._load_report()

    def showEvent(self, event):
        super().showEvent(event)
        self._load_today()

    def _load_today(self):
        self.date_from.setDate(QDate.currentDate().toPyDate())
        self.date_to.setDate(QDate.currentDate().toPyDate())
        self._show_table("sales")
        self._load_report()
        self.sales_btn.setChecked(True)
        if self.invoices_btn.isChecked():
            self.invoices_btn.setChecked(False)
        self.today_btn.setChecked(True)


    def _load_report(self, invoices: bool = False):
        start = self.date_from.date().toPyDate()
        end = self.date_to.date().toPyDate()

        with get_session() as session:
            currency = SettingsService.get(session, "currency_symbol", "€")
            all_sales = SalesService.get_sales_range(session, start, end)

            sales = all_sales
            if invoices:
                sales = [sale for sale in all_sales if sale.invoice is not None]

            totals = XZReportService.compute_totals(session, sales)
            transaction_count = totals["transaction_count"]
            avg = totals["final_amount"] / transaction_count if transaction_count else 0
            payment_totals = {leg["method"]: leg["amount"] for leg in totals["payment_breakdown"]}

            self.card_revenue._value_label.setText(f"{totals['final_amount']:.2f}")
            self.card_transactions._value_label.setText(str(transaction_count))
            self.card_avg._value_label.setText(f"{avg:.2f}")
            self.card_cash._value_label.setText(f"{payment_totals.get('cash', 0.0):.2f}")
            self.card_card._value_label.setText(f"{payment_totals.get('card', 0.0):.2f}")

            self.sales_table.setRowCount(0)
            self._sales_row_ids = {}

            inv_sent_font = QFont()
            inv_sent_font.setBold(True)

            for sale in sales:
                row = self.sales_table.rowCount()
                self.sales_table.insertRow(row)
                self._sales_row_ids[row] = sale.id
                display_number = sale.invoice.invoice_number if sale.invoice else sale.sale_number
                self.sales_table.setItem(row, 0, QTableWidgetItem(display_number))
                self.sales_table.setItem(row, 1, QTableWidgetItem(
                    sale.created_at.strftime("%d/%m/%Y %H:%M")
                ))

                client_name = (sale.invoice.client_name if sale.invoice else None) or "/"
                self.sales_table.setItem(row, 2, QTableWidgetItem(client_name))
                vat_num = (sale.invoice.client_vat_number if sale.invoice else None) or "/"
                self.sales_table.setItem(row, 3, QTableWidgetItem(vat_num))
                self.sales_table.setItem(row, 4, QTableWidgetItem(str(len(sale.items))))
                self.sales_table.setItem(row, 5, QTableWidgetItem(sale.payment_method.upper()))
                self.sales_table.setItem(row, 6, QTableWidgetItem(f"{sale.final_amount:.2f}"))
                updated_at = "/" if sale.updated_at is None else sale.updated_at.strftime("%d/%m/%Y %H:%M")
                self.sales_table.setItem(row, 7, QTableWidgetItem(updated_at))

                if sale.invoice is not None and sale.invoice.sent_at is not None:
                    for col in range(self.sales_table.columnCount()):
                        self.sales_table.item(row, col).setFont(inv_sent_font)

                self.sales_table.setRowHeight(row, ROW_HEIGHT)

            self.vat_table.setRowCount(0)
            for rate, amounts in totals["vat_breakdown"].items():
                row = self.vat_table.rowCount()
                self.vat_table.insertRow(row)
                self.vat_table.setItem(row, 0, QTableWidgetItem(f"{rate} %"))
                self.vat_table.setItem(row, 1, QTableWidgetItem(f"{amounts['base']:.2f}"))
                self.vat_table.setItem(row, 2, QTableWidgetItem(f"{amounts['tax']:.2f}"))
                self.vat_table.setItem(row, 3, QTableWidgetItem(f"{amounts['total']:.2f}"))
                self.vat_table.setRowHeight(row, ROW_HEIGHT)

            self.categories_table.setRowCount(0)
            for category_name, (qty_sum, amount_sum) in sorted(totals["category_breakdown"].items()):
                row = self.categories_table.rowCount()
                self.categories_table.insertRow(row)
                self.categories_table.setItem(row, 0, QTableWidgetItem(category_name))
                self.categories_table.setItem(row, 1, QTableWidgetItem(f"{qty_sum:g}"))
                self.categories_table.setItem(row, 2, QTableWidgetItem(f"{amount_sum:.2f}"))
                self.categories_table.setRowHeight(row, ROW_HEIGHT)

    def _print_x_report(self):
        with get_session() as session:
            try:
                totals = XZReportService.generate_x_report(session)
                ReceiptService.print_x_report(session, totals)
            except PrinterError as e:
                QMessageBox.critical(self, "Printer Error", str(e))

    def _print_z_report(self):
        reply = QMessageBox.question(
            self, "Print Z Report",
            "This will print the Z report and permanently clear all sales "
            "recorded since the last Z report. This cannot be undone.\nContinue?"
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        with get_session() as session:
            z_report = XZReportService.close_z_report(session)
            try:
                ReceiptService.print_z_report(session, z_report)
            except PrinterError as e:
                QMessageBox.critical(
                    self, "Printer Error",
                    f"Z report {z_report.report_number} was saved successfully, "
                    f"but printing failed:\n{e}"
                )
        self._load_report(invoices=self.invoices_only)

    def _confirm(self):
        if self.sales_table.currentRow() != -1:
            self._display_sale()
        self.navigate.emit(0)

    def _invoices_only(self):
        self.invoices_only = not self.invoices_only
        self._load_report(invoices=self.invoices_only)

    def _show_table(self, table: str):
        tables_list = [
            (self.sales_table, "sales"),
            (self.categories_table, "categories"),
            (self.vat_table, "vat"),
        ]

        for table_item, table_name in tables_list:
            if table == table_name:
                table_item.show()
            else:
                table_item.hide()

    def _display_sale(self):
        row = self.sales_table.currentRow()
        sale_id = self._sales_row_ids.get(row)
        if sale_id is not None:
            self.sale_selected.emit(sale_id)
        self.sales_table.setCurrentCell(-1, -1)

