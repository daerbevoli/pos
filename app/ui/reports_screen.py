"""
Reports Screen
Daily summary, date range sales, and top products.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QLabel, QHeaderView,
    QDateEdit, QGroupBox, QGridLayout, QComboBox
)
from PyQt6.QtCore import Qt, QDate
from datetime import date, timedelta

from app.core.database import get_session
from app.core.sales_service import SalesService
from app.core.settings_service import SettingsService


class ReportsScreen(QWidget):
    def __init__(self):
        super().__init__()
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
        self.date_from.setFixedHeight(40)
        controls.addWidget(self.date_from)

        controls.addWidget(QLabel("To:"))
        self.date_to = QDateEdit(QDate.currentDate())
        self.date_to.setCalendarPopup(True)
        self.date_to.setFixedHeight(40)
        controls.addWidget(self.date_to)

        # Quick range presets
        for label, days in [("Today", 0), ("Last 7 days", 7), ("Last 30 days", 30)]:
            btn = QPushButton(label)
            btn.setFixedHeight(40)
            btn.clicked.connect(lambda _, d=days: self._set_range(d))
            controls.addWidget(btn)

        load_btn = QPushButton("Load Report")
        load_btn.setObjectName("primaryBtn")
        load_btn.setFixedHeight(40)
        load_btn.clicked.connect(self._load_report)
        controls.addWidget(load_btn)

        controls.addStretch()
        layout.addLayout(controls)

        # ── Summary cards ─────────────────────────────────────────────────────
        cards_group = QGroupBox("Summary")
        cards_layout = QGridLayout(cards_group)

        self.card_revenue = self._make_card("Total Revenue", "€0.00")
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
        self.sales_table = QTableWidget(0, 5)
        self.sales_table.setObjectName("reportTable")
        self.sales_table.setHorizontalHeaderLabels([
            "Sale #", "Date & Time", "Items", "Payment", "Total"
        ])
        self.sales_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.sales_table.verticalHeader().setVisible(False)
        self.sales_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.sales_table.setAlternatingRowColors(True)
        layout.addWidget(self.sales_table)

    def _make_card(self, title: str, value: str) -> QGroupBox:
        card = QGroupBox(title)
        card.setObjectName("summaryCard")
        v = QVBoxLayout(card)
        label = QLabel(value)
        label.setObjectName("cardValue")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(label)
        card._value_label = label
        return card

    def _set_range(self, days: int):
        today = QDate.currentDate()
        self.date_to.setDate(today)
        self.date_from.setDate(today.addDays(-days))
        self._load_report()

    def _load_today(self):
        self._load_report()

    def _load_report(self):
        start = self.date_from.date().toPyDate()
        end = self.date_to.date().toPyDate()

        with get_session() as session:
            currency = SettingsService.get(session, "currency_symbol", "€")
            sales = SalesService.get_sales_range(session, start, end)

            total_revenue = sum(s.final_amount for s in sales)
            total_transactions = len(sales)
            avg = total_revenue / total_transactions if total_transactions else 0
            cash_total = sum(s.final_amount for s in sales if s.payment_method == "cash")
            card_total = sum(s.final_amount for s in sales if s.payment_method == "card")

            self.card_revenue._value_label.setText(f"{currency}{total_revenue:.2f}")
            self.card_transactions._value_label.setText(str(total_transactions))
            self.card_avg._value_label.setText(f"{currency}{avg:.2f}")
            self.card_cash._value_label.setText(f"{currency}{cash_total:.2f}")
            self.card_card._value_label.setText(f"{currency}{card_total:.2f}")

            self.sales_table.setRowCount(0)
            for sale in sales:
                row = self.sales_table.rowCount()
                self.sales_table.insertRow(row)
                self.sales_table.setItem(row, 0, QTableWidgetItem(sale.sale_number))
                self.sales_table.setItem(row, 1, QTableWidgetItem(
                    sale.created_at.strftime("%d/%m/%Y %H:%M")
                ))
                self.sales_table.setItem(row, 2, QTableWidgetItem(str(len(sale.items))))
                self.sales_table.setItem(row, 3, QTableWidgetItem(sale.payment_method.upper()))
                self.sales_table.setItem(row, 4, QTableWidgetItem(f"{currency}{sale.final_amount:.2f}"))
                self.sales_table.setRowHeight(row, 44)
