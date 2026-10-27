"""
Z Reports Dialog
Every closed Z report, newest first, with a button to print the selected
one again. A reprint is titled as a copy (ReceiptService.print_z_report) so
it can't pass for a second closing; nothing here changes any data.
"""
import logging

from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from app.constants import DIALOG_BUTTON_HEIGHT, Z_REPORTS_DIALOG_MIN_SIZE
from app.core.database import get_session
from app.core.receipt_service import PrinterError, ReceiptService
from app.core.report_service import XZReportService
from app.models.models import ZReport
from app.utils.utils import FunctionButton, TapToDismissOverlay

logger = logging.getLogger(__name__)

_DATE_FORMAT = "%d/%m/%Y %H:%M"


class ZReportsDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Z Reports")
        self.setMinimumSize(*Z_REPORTS_DIALOG_MIN_SIZE)
        self.overlay = TapToDismissOverlay(self)
        self._row_ids: dict[int, int] = {}  # table row -> ZReport.id
        self._build_ui()
        self._reload()

    def _build_ui(self):
        root = QVBoxLayout(self)

        self.table = QTableWidget(0, 5)
        self.table.setObjectName("reportTable")
        self.table.setHorizontalHeaderLabels(["Z report", "From", "To", "Transactions", "Total"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        root.addWidget(self.table, 1)

        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.reject)
        self.btn_print = FunctionButton("Print", "okBtn")
        self.btn_print.clicked.connect(self._print_selected)
        buttons = QHBoxLayout()
        for btn in (self.btn_close, self.btn_print):
            btn.setFixedHeight(DIALOG_BUTTON_HEIGHT)
            buttons.addWidget(btn)
        root.addLayout(buttons)

    def _reload(self):
        with get_session() as session:
            reports = XZReportService.all_z_reports(session)
            rows = [
                (z.id, z.report_number, z.period_start.strftime(_DATE_FORMAT),
                 z.period_end.strftime(_DATE_FORMAT), str(z.transaction_count),
                 f"{z.final_amount:.2f}")
                for z in reports
            ]
        self.table.setRowCount(len(rows))
        self._row_ids = {}
        for row, (z_id, *cells) in enumerate(rows):
            for col, text in enumerate(cells):
                self.table.setItem(row, col, QTableWidgetItem(text))
            self._row_ids[row] = z_id
        if rows:
            self.table.selectRow(0)

    def _print_selected(self):
        row = self.table.currentRow()
        if row == -1 or row not in self._row_ids:
            self.overlay.show_message("Select a Z report first.")
            return
        with get_session() as session:
            z_report = session.get(ZReport, self._row_ids[row])
            number = z_report.report_number
            try:
                ReceiptService.print_z_report(session, z_report, reprint=True)
            except PrinterError as e:
                self.overlay.show_message(f"Printing failed:\n{e}", kind="error")
                return
        self.overlay.show_message(f"{number} printed.")
