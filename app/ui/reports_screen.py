"""
Reports Screen
Daily summary, date range sales, and top products.
"""
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QLabel, QHeaderView,
    QDateEdit, QGroupBox, QGridLayout, QSizePolicy
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


    navigate = pyqtSignal(int)

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

        # Quick range presets
        for label, days in [("Today", 0), ("Last 7 days", 7), ("Last 30 days", 30)]:
            btn = QPushButton(label)
            btn.setFixedHeight(BUTTON_HEIGHT)
            btn.clicked.connect(lambda _, d=days: self._set_range(d))
            controls.addWidget(btn)

        load_btn = QPushButton("Load Report")
        load_btn.setObjectName("primaryBtn")
        load_btn.setFixedHeight(BUTTON_HEIGHT)
        load_btn.clicked.connect(self._load_report)
        controls.addWidget(load_btn)

        sales_btn = FunctionButton("Sales", "salesBtn")
        sales_btn.setFixedHeight(BUTTON_HEIGHT)
        controls.addWidget(sales_btn)

        vat_btn = FunctionButton("VAT breakdown", "InvBtn")
        vat_btn.setFixedHeight(BUTTON_HEIGHT)
        controls.addWidget(vat_btn)

        cats_btn = FunctionButton("Categories", "InvBtn")
        cats_btn.setFixedHeight(BUTTON_HEIGHT)
        controls.addWidget(cats_btn)

        invoices_btn = FunctionButton("Invoices", "InvBtn")
        invoices_btn.setFixedHeight(BUTTON_HEIGHT)
        controls.addWidget(invoices_btn)

        x_report_btn = FunctionButton("X Report", "InvBtn")
        x_report_btn.setFixedHeight(BUTTON_HEIGHT)
        x_report_btn.clicked.connect(self._print_x_report)
        controls.addWidget(x_report_btn)

        z_report_btn = FunctionButton("Z Report", "InvBtn")
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
        self.sales_table = QTableWidget(0, 7)
        self.sales_table.setObjectName("reportTable")
        self.sales_table.setHorizontalHeaderLabels([
            "Sale #", "Date & Time", "Client name", "VAT number", "Items", "Payment", "Total"
        ])
        self.sales_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.sales_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.sales_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.sales_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.sales_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.sales_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.sales_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
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

        sales_btn.clicked.connect(lambda: self._show_table("sales"))
        invoices_btn.clicked.connect(self._invoices_only)
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

            for sale in sales:
                row = self.sales_table.rowCount()
                self.sales_table.insertRow(row)
                display_number = sale.invoice.invoice_number if sale.invoice else sale.sale_number
                self.sales_table.setItem(row, 0, QTableWidgetItem(display_number))
                self.sales_table.setItem(row, 1, QTableWidgetItem(
                    sale.created_at.strftime("%d/%m/%Y %H:%M")
                ))
                # Read the invoice's own snapshot, not the live client — a
                # renamed/deactivated client (or an invoice issued with no
                # client at all) must not change what an already-issued
                # invoice is shown as having billed.
                client_name = (sale.invoice.client_name if sale.invoice else None) or "/"
                self.sales_table.setItem(row, 2, QTableWidgetItem(client_name))
                vat_num = (sale.invoice.client_vat_number if sale.invoice else None) or "/"
                self.sales_table.setItem(row, 3, QTableWidgetItem(vat_num))
                self.sales_table.setItem(row, 4, QTableWidgetItem(str(len(sale.items))))
                self.sales_table.setItem(row, 5, QTableWidgetItem(sale.payment_method.upper()))
                self.sales_table.setItem(row, 6, QTableWidgetItem(f"{sale.final_amount:.2f}"))
                self.sales_table.setRowHeight(row, ROW_HEIGHT)

            self.vat_table.setRowCount(0)
            for rate, amounts in totals["vat_breakdown"].items():
                row = self.vat_table.rowCount()
                self.vat_table.insertRow(row)
                self.vat_table.setItem(row, 0, QTableWidgetItem(f"{rate}%"))
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

