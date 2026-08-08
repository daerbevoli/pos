"""
Reports Screen
Daily summary, date range sales, and top products.
"""
import json

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QLabel, QHeaderView,
    QDateEdit, QGroupBox, QGridLayout
)
from PyQt6.QtCore import Qt, QDate, pyqtSignal

from app.core.database import get_session
from app.core.sales_service import SalesService
from app.core.settings_service import SettingsService
from app.models.models import Product
from app.utils.utils import FunctionButton
from app.constants import BUTTON_HEIGHT, ROW_HEIGHT


def _payment_breakdown(sale) -> list[dict]:
    """Per-method split of a sale's payment; falls back to a single-method
    entry for sales recorded before split payments existed."""
    if sale.payment_breakdown:
        try:
            return json.loads(sale.payment_breakdown)
        except (ValueError, TypeError):
            pass
    return [{"method": sale.payment_method, "amount": sale.final_amount}]


def _amount_for_method(sale, method: str) -> float:
    return sum(leg.get("amount", 0.0) for leg in _payment_breakdown(sale) if leg.get("method") == method)


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

        invoices_btn = FunctionButton("Invoices", "InvBtn")
        invoices_btn.setFixedHeight(BUTTON_HEIGHT)
        invoices_btn.clicked.connect(self._invoices_only)
        controls.addWidget(invoices_btn)

        self.btn_ok = FunctionButton("OK", "okBtn")
        self.btn_ok.setFixedHeight(BUTTON_HEIGHT)
        self.btn_ok.clicked.connect(self._confirm)
        controls.addWidget(self.btn_ok)

        controls.addStretch()
        layout.addLayout(controls)

        # ── Summary cards ─────────────────────────────────────────────────────
        cards_group = QGroupBox("Summary")
        cards_layout = QGridLayout(cards_group)

        self.card_revenue = self._make_card("Total Revenue", "€0.00", True)
        self.card_transactions = self._make_card("Transactions", "0")
        self.card_avg = self._make_card("Avg. Transaction", "€0.00")
        self.card_cash = self._make_card("Cash Sales", "€0.00")
        self.card_card = self._make_card("Card Sales", "€0.00")

        cards_layout.addWidget(self.card_revenue, 0, 0)
        cards_layout.addWidget(self.card_transactions, 0, 1)
        cards_layout.addWidget(self.card_avg, 0, 2)
        cards_layout.addWidget(self.card_cash, 0, 3)
        cards_layout.addWidget(self.card_card, 0, 4)

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
        layout.addWidget(self.sales_table)

        # ── VAT breakdown ─────────────────────────────────────────────────────
        vat_group = QGroupBox("VAT Breakdown")
        vat_layout = QGridLayout(vat_group)
        for col, header in enumerate(["Rate", "Base (excl. tax)", "Tax", "Total (incl. tax)"]):
            lbl = QLabel(header)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            font = lbl.font()
            font.setBold(True)
            lbl.setFont(font)
            vat_layout.addWidget(lbl, 0, col)
        self._vat_labels = {}
        for i, rate in enumerate([0, 6, 21]):
            vat_layout.addWidget(QLabel(f"{rate}%"), i + 1, 0)
            base_lbl = QLabel("€0.00")
            base_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            tax_lbl = QLabel("€0.00")
            tax_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            total_lbl = QLabel("€0.00")
            total_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            vat_layout.addWidget(base_lbl, i + 1, 1)
            vat_layout.addWidget(tax_lbl, i + 1, 2)
            vat_layout.addWidget(total_lbl, i + 1, 3)
            self._vat_labels[rate] = (base_lbl, tax_lbl, total_lbl)
        layout.addWidget(vat_group)

        # ── Categories breakdown ─────────────────────────────────────────────
        categories_group = QGroupBox("Categories")
        categories_layout = QVBoxLayout(categories_group)
        self.categories_table = QTableWidget(0, 3)
        self.categories_table.setHorizontalHeaderLabels(["Category", "Quantity", "Total Amount"])
        self.categories_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.categories_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.categories_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.categories_table.verticalHeader().setVisible(False)
        self.categories_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        categories_layout.addWidget(self.categories_table)
        layout.addWidget(categories_group)


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
        self._load_report()

    def _load_report(self, invoices: bool = False):
        start = self.date_from.date().toPyDate()
        end = self.date_to.date().toPyDate()

        with get_session() as session:
            currency = SettingsService.get(session, "currency_symbol", "€")
            sales = SalesService.get_sales_range(session, start, end)

            if invoices:
                sales = [sale for sale in sales if sale.invoice is not None]

            total_revenue = sum(s.final_amount for s in sales)
            total_transactions = len(sales)
            avg = total_revenue / total_transactions if total_transactions else 0
            cash_total = sum(_amount_for_method(s, "cash") for s in sales)
            card_total = sum(_amount_for_method(s, "card") for s in sales)

            self.card_revenue._value_label.setText(f"{currency}{total_revenue:.2f}")
            self.card_transactions._value_label.setText(str(total_transactions))
            self.card_avg._value_label.setText(f"{currency}{avg:.2f}")
            self.card_cash._value_label.setText(f"{currency}{cash_total:.2f}")
            self.card_card._value_label.setText(f"{currency}{card_total:.2f}")

            self.sales_table.setRowCount(0)

            vat_totals = {0: [0.0, 0.0], 6: [0.0, 0.0], 21: [0.0, 0.0]}  # rate -> [tax_sum, total_sum]
            category_totals = {}

            for sale in sales:
                row = self.sales_table.rowCount()
                self.sales_table.insertRow(row)
                display_number = sale.invoice.invoice_number if sale.invoice else sale.sale_number
                self.sales_table.setItem(row, 0, QTableWidgetItem(display_number))
                self.sales_table.setItem(row, 1, QTableWidgetItem(
                    sale.created_at.strftime("%d/%m/%Y %H:%M")
                ))
                client_name = sale.invoice.client.name if sale.invoice else "/"
                self.sales_table.setItem(row, 2, QTableWidgetItem(client_name))
                vat_num = sale.invoice.client.vatNumber if sale.invoice else "/"
                self.sales_table.setItem(row, 3, QTableWidgetItem(vat_num))
                self.sales_table.setItem(row, 4, QTableWidgetItem(str(len(sale.items))))
                if sale.payment_method == "mixed":
                    payment_str = "CASH+CARD"
                else:
                    payment_str = sale.payment_method.upper()
                self.sales_table.setItem(row, 5, QTableWidgetItem(payment_str))
                self.sales_table.setItem(row, 6, QTableWidgetItem(f"{currency}{sale.final_amount:.2f}"))
                self.sales_table.setRowHeight(row, ROW_HEIGHT)

                for item in sale.items:

                    rate = item.tax_rate if item.tax_rate in vat_totals else 0
                    vat_totals[rate][0] += item.tax_amount
                    vat_totals[rate][1] += item.line_total

                    category_name = item.product.category.name if item.product.category else "Uncategorized"
                    qty_sum, amount_sum = category_totals.get(category_name, [0.0, 0.0])
                    category_totals[category_name] = [qty_sum + item.quantity, amount_sum + item.line_total]

            for rate, (tax_sum, total_sum) in vat_totals.items():
                base_sum = total_sum - tax_sum
                base_lbl, tax_lbl, total_lbl = self._vat_labels[rate]
                base_lbl.setText(f"{currency}{base_sum:.2f}")
                tax_lbl.setText(f"{currency}{tax_sum:.2f}")
                total_lbl.setText(f"{currency}{total_sum:.2f}")

            self.categories_table.setRowCount(0)
            for category_name, (qty_sum, amount_sum) in sorted(category_totals.items()):
                row = self.categories_table.rowCount()
                self.categories_table.insertRow(row)
                self.categories_table.setItem(row, 0, QTableWidgetItem(category_name))
                self.categories_table.setItem(row, 1, QTableWidgetItem(f"{qty_sum:g}"))
                self.categories_table.setItem(row, 2, QTableWidgetItem(f"{currency}{amount_sum:.2f}"))
                self.categories_table.setRowHeight(row, ROW_HEIGHT)

    def _confirm(self):
        self.navigate.emit(0)

    def _invoices_only(self):
        self.invoices_only = not self.invoices_only
        self._load_report(invoices=self.invoices_only)