"""
Reports Screen
- Daily summary of sales and current and previous invoices
- Vat breakdown, category breakdown
- X report and Z report.
"""
import json

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
from app.core.receipt_service import ReceiptService, PrinterError
from app.core.report_service import (
    XZReportService, invoice_category_breakdown, invoice_vat_breakdown,
)
from app.models.models import Invoice, Sale
from app.utils.utils import FunctionButton
from app.constants import REPORTS_BUTTON_HEIGHT, REPORT_ROW_HEIGHT


def _make_card(title: str, value: str, bold: bool = False) -> QGroupBox:
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

class ReportsScreen(QWidget):

    # Navigate across screens
    navigate = pyqtSignal(int)

    # Send selected sale id to pos to display
    sale_selected = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        # Invoices filter: once on, every reload (range buttons, Load Report,
        # Z report, Mark sent) stays on invoices until toggled off.
        self.invoices_only = False
        self._build_ui()
        self._load_today()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # ── Date range controls ───────────────────────────────────────────────
        controls = QHBoxLayout()

        controls.addWidget(QLabel("From:"))
        self.date_from = QDateEdit(QDate.currentDate())
        self.date_from.setCalendarPopup(True)
        self.date_from.setFixedHeight(REPORTS_BUTTON_HEIGHT)
        controls.addWidget(self.date_from)

        controls.addWidget(QLabel("To:"))
        self.date_to = QDateEdit(QDate.currentDate())
        self.date_to.setCalendarPopup(True)
        self.date_to.setFixedHeight(REPORTS_BUTTON_HEIGHT)
        controls.addWidget(self.date_to)

        self._range_group = QButtonGroup(self)
        self._range_group.setExclusive(True)

        self.today_btn = QPushButton("Today")
        self.today_btn.setObjectName("salesBtn")
        self.today_btn.setCheckable(True)
        self.today_btn.setChecked(True)
        self.today_btn.setFixedHeight(REPORTS_BUTTON_HEIGHT)
        self.today_btn.clicked.connect(lambda: self._set_range(0))
        self._range_group.addButton(self.today_btn)
        controls.addWidget(self.today_btn)

        last_7_days_btn = QPushButton("Last 7 days")
        last_7_days_btn.setObjectName("salesBtn")
        last_7_days_btn.setCheckable(True)
        last_7_days_btn.setChecked(False)
        last_7_days_btn.setFixedHeight(REPORTS_BUTTON_HEIGHT)
        last_7_days_btn.clicked.connect(lambda: self._set_range(7))
        self._range_group.addButton(last_7_days_btn)
        controls.addWidget(last_7_days_btn)

        last_30_days_btn = QPushButton("Last 30 days")
        last_30_days_btn.setObjectName("salesBtn")
        last_30_days_btn.setCheckable(True)
        last_30_days_btn.setChecked(False)
        last_30_days_btn.setFixedHeight(REPORTS_BUTTON_HEIGHT)
        last_30_days_btn.clicked.connect(lambda: self._set_range(30))
        self._range_group.addButton(last_30_days_btn)
        controls.addWidget(last_30_days_btn)

        load_btn = QPushButton("Load Report")
        load_btn.setObjectName("primaryBtn")
        load_btn.setFixedHeight(REPORTS_BUTTON_HEIGHT)
        load_btn.clicked.connect(lambda: self._load_report())
        controls.addWidget(load_btn)

        self.sales_btn = FunctionButton("Sales", "salesBtn")
        self.sales_btn.setFixedHeight(REPORTS_BUTTON_HEIGHT)
        self.sales_btn.setCheckable(True)
        self.sales_btn.setChecked(True)
        controls.addWidget(self.sales_btn)

        vat_btn = FunctionButton("VAT breakdown", "salesBtn")
        vat_btn.setFixedHeight(REPORTS_BUTTON_HEIGHT)
        vat_btn.setCheckable(True)
        controls.addWidget(vat_btn)

        cats_btn = FunctionButton("Categories", "salesBtn")
        cats_btn.setFixedHeight(REPORTS_BUTTON_HEIGHT)
        cats_btn.setCheckable(True)
        controls.addWidget(cats_btn)

        self._view_group = QButtonGroup(self)
        self._view_group.setExclusive(True)
        for btn in (self.sales_btn, vat_btn, cats_btn):
            self._view_group.addButton(btn)

        self.invoices_btn = FunctionButton("Invoices", "InvBtn")
        self.invoices_btn.setFixedHeight(REPORTS_BUTTON_HEIGHT)
        self.invoices_btn.setCheckable(True)
        controls.addWidget(self.invoices_btn)

        mark_sent_btn = FunctionButton("Mark sent", "InvBtn")
        mark_sent_btn.setFixedHeight(REPORTS_BUTTON_HEIGHT)
        mark_sent_btn.clicked.connect(self._mark_invoice_sent)
        controls.addWidget(mark_sent_btn)

        x_report_btn = FunctionButton("X Report", "XRBtn")
        x_report_btn.setFixedHeight(REPORTS_BUTTON_HEIGHT)
        x_report_btn.clicked.connect(self._print_x_report)
        controls.addWidget(x_report_btn)

        z_report_btn = FunctionButton("Z Report", "ZRBtn")
        z_report_btn.setFixedHeight(REPORTS_BUTTON_HEIGHT)
        z_report_btn.clicked.connect(self._print_z_report)
        controls.addWidget(z_report_btn)

        self.btn_ok = FunctionButton("OK", "okBtn")
        self.btn_ok.setFixedHeight(REPORTS_BUTTON_HEIGHT)
        self.btn_ok.clicked.connect(self._confirm)
        controls.addWidget(self.btn_ok)

        controls.addStretch()
        layout.addLayout(controls)

        # ── Summary cards ─────────────────────────────────────────────────────
        cards_group = QGroupBox("Summary")
        cards_layout = QGridLayout(cards_group)

        self.card_revenue = _make_card("Total Revenue", "0.00", True)
        self.card_transactions = _make_card("Transactions", "0")
        self.card_avg = _make_card("Avg. Transaction", "0.00")
        self.card_cash = _make_card("Cash Sales", "0.00")
        self.card_card = _make_card("Card Sales", "0.00")

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
        self.invoices_only = False
        self.invoices_btn.setChecked(False)
        self._load_report()
        self.sales_btn.setChecked(True)
        self.today_btn.setChecked(True)


    def _load_report(self):
        start = self.date_from.date().toPyDate()
        end = self.date_to.date().toPyDate()

        with get_session() as session:
            self.sales_table.setRowCount(0)
            self._sales_row_ids = {}
            self._invoice_row_ids = {}

            if self.invoices_only:
                # Read from the invoices table: a Z report purges sales but
                # keeps their invoices, which then have no sale to list them by.
                invoice_rows = SalesService.get_invoices_range(session, start, end)
                for invoice in invoice_rows:
                    self._add_row(invoice.sale, invoice)
                # The payment split only exists on the sale, so it covers just
                # the invoices whose sale hasn't been purged yet; VAT and
                # categories are rebuilt from every invoice's own line items.
                sales = [invoice.sale for invoice in invoice_rows if invoice.sale is not None]
                totals = XZReportService.compute_totals(session, sales)
                totals["vat_breakdown"] = invoice_vat_breakdown(invoice_rows)
                totals["category_breakdown"] = invoice_category_breakdown(session, invoice_rows)
                revenue = round(sum(invoice.final_amount or 0.0 for invoice in invoice_rows), 2)
                transaction_count = len(invoice_rows)
            else:
                sales = SalesService.get_sales_range(session, start, end)
                for sale in sales:
                    self._add_row(sale, sale.invoice)
                totals = XZReportService.compute_totals(session, sales)
                revenue = totals["final_amount"]
                transaction_count = totals["transaction_count"]

            avg = revenue / transaction_count if transaction_count else 0
            payment_totals = {leg["method"]: leg["amount"] for leg in totals["payment_breakdown"]}

            self.card_revenue._value_label.setText(f"{revenue:.2f}")
            self.card_transactions._value_label.setText(str(transaction_count))
            self.card_avg._value_label.setText(f"{avg:.2f}")
            self.card_cash._value_label.setText(f"{payment_totals.get('cash', 0.0):.2f}")
            self.card_card._value_label.setText(f"{payment_totals.get('card', 0.0):.2f}")

            self.vat_table.setRowCount(0)
            for rate, amounts in totals["vat_breakdown"].items():
                row = self.vat_table.rowCount()
                self.vat_table.insertRow(row)
                self.vat_table.setItem(row, 0, QTableWidgetItem(f"{rate} %"))
                self.vat_table.setItem(row, 1, QTableWidgetItem(f"{amounts['base']:.2f}"))
                self.vat_table.setItem(row, 2, QTableWidgetItem(f"{amounts['tax']:.2f}"))
                self.vat_table.setItem(row, 3, QTableWidgetItem(f"{amounts['total']:.2f}"))
                self.vat_table.setRowHeight(row, REPORT_ROW_HEIGHT)

            self.categories_table.setRowCount(0)
            for category_name, (qty_sum, amount_sum) in sorted(totals["category_breakdown"].items()):
                row = self.categories_table.rowCount()
                self.categories_table.insertRow(row)
                self.categories_table.setItem(row, 0, QTableWidgetItem(category_name))
                self.categories_table.setItem(row, 1, QTableWidgetItem(f"{qty_sum:g}"))
                self.categories_table.setItem(row, 2, QTableWidgetItem(f"{amount_sum:.2f}"))
                self.categories_table.setRowHeight(row, REPORT_ROW_HEIGHT)

    def _add_row(self, sale: Sale | None, invoice: Invoice | None):
        """One sales_table row for a sale and/or its invoice. Either may be
        missing: a plain sale has no invoice, and an invoice whose sale a Z
        report purged has no sale — it's shown from its own frozen snapshot."""
        row = self.sales_table.rowCount()
        self.sales_table.insertRow(row)
        if sale is not None:
            self._sales_row_ids[row] = sale.id
        if invoice is not None:
            self._invoice_row_ids[row] = invoice.id

        def fmt(dt):
            return "/" if dt is None else dt.strftime("%d/%m/%Y %H:%M")

        if invoice is not None:
            number = invoice.invoice_number
            created = invoice.issued_at
            client_name = invoice.client_name or "/"
            vat_num = invoice.client_vat_number or "/"
            final_amount = invoice.final_amount or 0.0
        else:
            number, created, client_name, vat_num = sale.sale_number, sale.created_at, "/", "/"
            final_amount = sale.final_amount
        if sale is not None:
            item_count = len(sale.items)
            payment = sale.payment_method.upper()
            updated_at = sale.updated_at
        else:
            snapshot = json.loads(invoice.line_items_snapshot) if invoice.line_items_snapshot else []
            item_count = sum(1 for entry in snapshot if entry.get("type") == "item")
            payment, updated_at = "/", None

        values = [number, fmt(created), client_name, vat_num, str(item_count), payment,
                  f"{final_amount:.2f}", fmt(updated_at)]
        for col, value in enumerate(values):
            self.sales_table.setItem(row, col, QTableWidgetItem(value))

        if invoice is not None and invoice.sent_at is not None:
            sent_font = QFont()
            sent_font.setBold(True)
            for col in range(self.sales_table.columnCount()):
                self.sales_table.item(row, col).setFont(sent_font)

        self.sales_table.setRowHeight(row, REPORT_ROW_HEIGHT)

    def _print_x_report(self):
        with get_session() as session:
            try:
                totals = XZReportService.generate_x_report(session)
                ReceiptService.print_x_report(session, totals)
            except PrinterError as e:
                QMessageBox.critical(self, "Printer Error", str(e))

    def _print_z_report(self):
        # Checked before the confirmation, so the cashier learns why up front.
        with get_session() as session:
            unsent = XZReportService.unsent_invoice_numbers(session)
        if unsent:
            self._warn_unsent_invoices(unsent)
            return

        reply = QMessageBox.question(
            self, "Print Z Report",
            "This will print the Z report and clear all sales. This cannot be undone.\nContinue?"
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        with get_session() as session:
            # Re-checked inside close_z_report(): an invoice may have been
            # created on another V-tab while the dialog was open.
            try:
                z_report = XZReportService.close_z_report(session)
            except ValueError:
                self._warn_unsent_invoices(XZReportService.unsent_invoice_numbers(session))
                return
            try:
                ReceiptService.print_z_report(session, z_report)
            except PrinterError as e:
                QMessageBox.critical(
                    self, "Printer Error",
                    f"Z report {z_report.report_number} was saved successfully, "
                    f"but printing failed:\n{e}"
                )
        self._load_report()

    def _mark_invoice_sent(self):
        """Manually lock the selected invoice as sent — for one delivered
        outside the ERP flow. Same effect as a successful send: it can no
        longer be reopened/edited, and stops blocking the Z report."""
        row = self.sales_table.currentRow()
        if row == -1:
            QMessageBox.information(self, "Mark Invoice Sent", "Select an invoice first.")
            return
        invoice_id = self._invoice_row_ids.get(row)
        if invoice_id is None:
            QMessageBox.information(self, "Mark Invoice Sent", "The selected sale is not an invoice.")
            return
        with get_session() as session:
            invoice = session.get(Invoice, invoice_id)
            if invoice.sent_at is not None:
                QMessageBox.information(self, "Mark Invoice Sent", f"{invoice.invoice_number} is already sent.")
                return
            invoice_number = invoice.invoice_number

        reply = QMessageBox.question(
            self, "Mark Invoice Sent",
            f"Are you sure you want to mark {invoice_number} as sent?\n\n"
            "It will no longer be editable — corrections will need a credit note.",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        with get_session() as session:
            SalesService.mark_invoice_id_sent(session, invoice_id)
        self._load_report()

    def _warn_unsent_invoices(self, invoice_numbers: list[str]):
        QMessageBox.warning(
            self, "Z Report Blocked",
            "These invoices haven't been sent to the ERP yet:\n\n"
            + "\n".join(invoice_numbers)
            + "\n\nSend them first — once the Z report clears the sales, "
              "they can no longer be sent from the POS."
        )

    def _confirm(self):
        if self.sales_table.currentRow() != -1 and not self._display_sale():
            return
        self.navigate.emit(0)

    def _invoices_only(self):
        self.invoices_only = not self.invoices_only
        self.invoices_btn.setChecked(self.invoices_only)
        self._load_report()

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

    def _display_sale(self) -> bool:
        """Show the selected row's sale on the POS. False (nothing shown) for
        an invoice whose sale a Z report has already purged."""
        row = self.sales_table.currentRow()
        sale_id = self._sales_row_ids.get(row)
        if sale_id is None and row in self._invoice_row_ids:
            QMessageBox.information(
                self, "Invoice",
                "This invoice's sale was cleared by a Z report, so it can't be opened on the POS. Open it in the ERP.",
            )
            return False
        if sale_id is not None:
            self.sale_selected.emit(sale_id)
        self.sales_table.setCurrentCell(-1, -1)
        return True

