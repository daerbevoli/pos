"""
Product Search Dialog
Full-text search modal used from the POS screen.
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLineEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QPushButton, QHBoxLayout
)

from app.core.client_service import ClientService
from app.core.database import get_session
from app.models.models import Client


class ClientSearchDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Search Product")
        self.setMinimumSize(600, 450)
        self.selected_client: Client | None = None
        self._build_ui()

    def set_query(self, query: str):
        self.search_input.setText(query)
        self._search()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Type name")
        self.search_input.setFixedHeight(48)
        self.search_input.textChanged.connect(self._search)
        layout.addWidget(self.search_input)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Name", "Address", "Vat number"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.doubleClicked.connect(self._select)
        layout.addWidget(self.table)

        btn_row = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        select_btn = QPushButton("Select")
        select_btn.setObjectName("primaryBtn")
        select_btn.clicked.connect(self._select)
        btn_row.addWidget(select_btn)
        layout.addLayout(btn_row)

        self._products = []

    def _search(self):
        query = self.search_input.text().strip()
        if len(query) < 1:
            self.table.setRowCount(0)
            return
        with get_session() as session:
            self._clients = ClientService.search(session, query)
            self.table.setRowCount(0)
            for c in self._clients:
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.setItem(row, 0, QTableWidgetItem(c.name or ""))
                self.table.setItem(row, 1, QTableWidgetItem(c.address))
                self.table.setItem(row, 2, QTableWidgetItem(c.vatNumber))
                self.table.setRowHeight(row, 44)

    def _select(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._clients):
            return
        self.selected_product = self._clients[row]
        self.accept()
