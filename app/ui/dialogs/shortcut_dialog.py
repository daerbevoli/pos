"""
Shortcut Dialog
Create / edit a POS shortcut: its name plus the ordered list of products
shown in its slots. Search the product catalogue on the left, build the
shortcut's list on the right. Nothing is written to the DB here — on OK the
dialog exposes `sc_name` and `product_ids` for the caller to persist.
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QMessageBox
)
from PyQt6.QtCore import Qt

from app.core.database import get_session
from app.core.product_service import ProductService
from app.constants import BUTTON_HEIGHT, DIALOG_WIDTH_XL
from app.utils.utils import FunctionButton


class ShortcutDialog(QDialog):

    def __init__(self, parent=None, sc_name: str = "", product_ids=None, existing_names=None):
        super().__init__(parent)
        self.setWindowTitle("Shortcut")
        self.setMinimumSize(DIALOG_WIDTH_XL + 200, 460)

        self._existing = {n.strip().lower() for n in (existing_names or [])}
        self._original = sc_name.strip().lower()
        self._name_in = sc_name.strip()

        # Result of the dialog, read by the caller after exec().
        self.sc_name = ""
        self.product_ids: list[int] = list(product_ids or [])

        # id -> display name, filled lazily as products are seen.
        self._names: dict[int, str] = {}

        self._build_ui()
        self._resolve_names(self.product_ids)
        self._reload_selected()
        self._run_search()

    # ── UI ───────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Name:"))
        self.name_edit = QLineEdit()
        self.name_edit.setText(self._name_in)
        name_row.addWidget(self.name_edit)
        root.addLayout(name_row)

        lists_row = QHBoxLayout()

        # Left: search + results
        left = QVBoxLayout()
        left.addWidget(QLabel("Search products"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Name or barcode")
        self.search_edit.textChanged.connect(self._run_search)
        left.addWidget(self.search_edit)
        self.results_list = QListWidget()
        self.results_list.itemDoubleClicked.connect(lambda _: self._add_selected_result())
        left.addWidget(self.results_list)
        self.add_btn = QPushButton("Add →")
        self.add_btn.clicked.connect(self._add_selected_result)
        left.addWidget(self.add_btn)
        lists_row.addLayout(left, 1)

        # Right: current items + reorder / remove
        right = QVBoxLayout()
        right.addWidget(QLabel("In this shortcut"))
        self.selected_list = QListWidget()
        right.addWidget(self.selected_list)
        reorder_row = QHBoxLayout()
        self.up_btn = QPushButton("↑")
        self.up_btn.clicked.connect(lambda: self._move(-1))
        self.down_btn = QPushButton("↓")
        self.down_btn.clicked.connect(lambda: self._move(1))
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.clicked.connect(self._remove_selected_item)
        reorder_row.addWidget(self.up_btn)
        reorder_row.addWidget(self.down_btn)
        reorder_row.addWidget(self.remove_btn)
        right.addLayout(reorder_row)
        lists_row.addLayout(right, 1)

        root.addLayout(lists_row)

        btn_row = QHBoxLayout()
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setFixedHeight(BUTTON_HEIGHT)
        self.cancel_btn.clicked.connect(self.reject)
        self.ok_btn = FunctionButton("OK", "okBtn")
        self.ok_btn.setFixedHeight(BUTTON_HEIGHT)
        self.ok_btn.clicked.connect(self.on_ok)
        btn_row.addStretch()
        btn_row.addWidget(self.cancel_btn)
        btn_row.addWidget(self.ok_btn)
        root.addLayout(btn_row)

    # ── Data helpers ─────────────────────────────────────────────────────

    def _resolve_names(self, ids):
        missing = [pid for pid in ids if pid not in self._names]
        if not missing:
            return
        with get_session() as session:
            for pid in missing:
                p = ProductService.get_by_id(session, pid)
                self._names[pid] = p.name if p else f"(deleted product #{pid})"

    def _run_search(self):
        term = self.search_edit.text().strip()
        self.results_list.clear()
        if not term:
            return
        with get_session() as session:
            products = ProductService.search(session, term)
            for p in products:
                self._names[p.id] = p.name
                item = QListWidgetItem(f"{p.name}  ·  {p.barcode or 'no barcode'}")
                item.setData(Qt.ItemDataRole.UserRole, p.id)
                if p.id in self.product_ids:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                    item.setText(item.text() + "   (added)")
                self.results_list.addItem(item)

    def _reload_selected(self):
        row = self.selected_list.currentRow()
        self.selected_list.clear()
        for pos, pid in enumerate(self.product_ids, start=1):
            item = QListWidgetItem(f"{pos}.  {self._names.get(pid, f'#{pid}')}")
            item.setData(Qt.ItemDataRole.UserRole, pid)
            self.selected_list.addItem(item)
        if 0 <= row < self.selected_list.count():
            self.selected_list.setCurrentRow(row)

    # ── Actions ──────────────────────────────────────────────────────────

    def _add_selected_result(self):
        item = self.results_list.currentItem()
        if item is None or not (item.flags() & Qt.ItemFlag.ItemIsEnabled):
            return
        pid = item.data(Qt.ItemDataRole.UserRole)
        if pid in self.product_ids:
            return
        self.product_ids.append(pid)
        self._reload_selected()
        self._run_search()  # re-mark the just-added row as "(added)"
        self.selected_list.setCurrentRow(self.selected_list.count() - 1)

    def _remove_selected_item(self):
        row = self.selected_list.currentRow()
        if row < 0:
            return
        self.product_ids.pop(row)
        self._reload_selected()
        self._run_search()

    def _move(self, delta: int):
        row = self.selected_list.currentRow()
        new_row = row + delta
        if row < 0 or not (0 <= new_row < len(self.product_ids)):
            return
        self.product_ids[row], self.product_ids[new_row] = (
            self.product_ids[new_row], self.product_ids[row],
        )
        self._reload_selected()
        self.selected_list.setCurrentRow(new_row)

    def on_ok(self):
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Shortcut", "Name cannot be empty.")
            return
        if name.lower() != self._original and name.lower() in self._existing:
            QMessageBox.warning(self, "Shortcut", f"“{name}” already exists.")
            return
        self.sc_name = name
        self.accept()
