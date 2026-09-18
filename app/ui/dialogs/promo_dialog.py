"""
Promo Dialog
Create / edit a Promo: its name, active date range, and the set of products
it discounts. Each product in the promo gets its own discount, entered as
either a percentage or a fixed amount — whichever isn't typed in is derived
automatically, alongside a live preview of the resulting price. Nothing is
written to the DB here — on OK the dialog exposes promo_name/start_date/
end_date/is_active/items for the caller to persist via
ProductService.create_promo()/update_promo()/set_promo_items().
"""
from datetime import date

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QMessageBox, QDateEdit, QCheckBox,
    QComboBox, QDoubleSpinBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView,
)
from PyQt6.QtCore import Qt, QDate

from app.core.database import get_session
from app.core.product_service import ProductService
from app.constants import BUTTON_HEIGHT, DIALOG_WIDTH_XL
from app.utils.utils import FunctionButton

# Column indices for the products table.
COL_PRODUCT, COL_PRICE, COL_TYPE, COL_VALUE, COL_NEW_PRICE, COL_REMOVE = range(6)


class PromoDialog(QDialog):

    def __init__(
        self, parent=None,
        promo_name: str = "",
        start_date: date | None = None,
        end_date: date | None = None,
        is_active: bool = True,
        existing_names=None,
        items=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Promo")
        self.setMinimumSize(DIALOG_WIDTH_XL + 340, 520)

        self._existing = {n.strip().lower() for n in (existing_names or [])}
        self._original = promo_name.strip().lower()

        # Result of the dialog, read by the caller after exec().
        self.promo_name = ""
        self.start_date: date | None = None
        self.end_date: date | None = None
        self.is_active = is_active

        # Working list of per-product discounts: dicts with product_id, name,
        # price, discount_type ("percent"|"fixed"), discount_value.
        self._items: list[dict] = []

        self._build_ui(promo_name, start_date, end_date, is_active)
        self._load_initial_items(items or [])
        self._run_search()

    # ── UI ───────────────────────────────────────────────────────────────

    def _build_ui(self, promo_name, start_date, end_date, is_active):
        root = QVBoxLayout(self)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Name:"))
        self.name_edit = QLineEdit()
        self.name_edit.setText(promo_name)
        self.name_edit.setPlaceholderText("e.g. New Year Promo")
        name_row.addWidget(self.name_edit)
        root.addLayout(name_row)

        range_row = QHBoxLayout()
        self.date = QCheckBox("Date")
        self.indefinite = QCheckBox("Indefinite")
        range_row.addWidget(self.date)
        range_row.addWidget(self.indefinite)
        range_row.addStretch()
        root.addLayout(range_row)

        dates_row = QHBoxLayout()
        today = QDate.currentDate()

        self.start_label = QLabel("Start date:")
        dates_row.addWidget(self.start_label)
        self.start_edit = QDateEdit()
        self.start_edit.setCalendarPopup(True)
        self.start_edit.setDisplayFormat("dd-MM-yyyy")
        self.start_edit.setDate(QDate(start_date.year, start_date.month, start_date.day) if start_date else today)
        dates_row.addWidget(self.start_edit)

        self.end_label = QLabel("End date:")
        dates_row.addWidget(self.end_label)
        self.end_edit = QDateEdit()
        self.end_edit.setCalendarPopup(True)
        self.end_edit.setDisplayFormat("dd-MM-yyyy")
        self.end_edit.setDate(
            QDate(end_date.year, end_date.month, end_date.day) if end_date else today.addDays(7)
        )
        dates_row.addWidget(self.end_edit)

        self.active_check = QCheckBox("Active")
        self.active_check.setChecked(is_active)
        dates_row.addWidget(self.active_check)
        root.addLayout(dates_row)

        # Mutually exclusive — "Date" reveals the start/end pickers above;
        # "Indefinite" hides them and the promo runs until removed/edited.
        self.date.toggled.connect(self._on_range_mode_toggled)
        self.indefinite.toggled.connect(self._on_range_mode_toggled)
        has_dates = start_date is not None and end_date is not None
        self.date.setChecked(has_dates)
        self.indefinite.setChecked(not has_dates)
        self._sync_date_fields_visibility()

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

        # Right: products in this promo, each with its own discount
        right = QVBoxLayout()
        right.addWidget(QLabel("In this promo"))
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Product", "Price", "Discount", "Value", "New price", ""]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_PRODUCT, QHeaderView.ResizeMode.Stretch)
        for col in (COL_PRICE, COL_TYPE, COL_VALUE, COL_NEW_PRICE, COL_REMOVE):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        right.addWidget(self.table, 1)
        lists_row.addLayout(right, 2)

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

    def _on_range_mode_toggled(self, checked: bool):
        sender = self.sender()
        other = self.indefinite if sender is self.date else self.date
        if not checked:
            # Can't uncheck one without checking the other — revert.
            sender.blockSignals(True)
            sender.setChecked(True)
            sender.blockSignals(False)
        else:
            other.blockSignals(True)
            other.setChecked(False)
            other.blockSignals(False)
        self._sync_date_fields_visibility()

    def _sync_date_fields_visibility(self):
        show = self.date.isChecked()
        self.start_label.setVisible(show)
        self.start_edit.setVisible(show)
        self.end_label.setVisible(show)
        self.end_edit.setVisible(show)

    # ── Data helpers ─────────────────────────────────────────────────────

    def _load_initial_items(self, items: list[dict]):
        """Resolve each incoming {"product_id", "discount_type",
        "discount_value"} into a full row (with name/price fetched once)
        and populate the table."""
        if not items:
            return
        with get_session() as session:
            for it in items:
                product = ProductService.get_by_id(session, it["product_id"])
                if not product:
                    continue  # product since deleted — drop it from the promo
                self._items.append({
                    "product_id": it["product_id"],
                    "name": product.name,
                    "price": product.price,
                    "discount_type": it["discount_type"],
                    "discount_value": it["discount_value"],
                })
        self._rebuild_table()

    def _current_product_ids(self) -> set[int]:
        return {it["product_id"] for it in self._items}

    def _run_search(self):
        term = self.search_edit.text().strip()
        self.results_list.clear()
        if not term:
            return
        already = self._current_product_ids()
        with get_session() as session:
            products = ProductService.search(session, term)
            for p in products:
                price_text = "open price" if p.is_open_price else f"{p.price:.2f}"
                item = QListWidgetItem(f"{p.name}  ·  {price_text}")
                item.setData(Qt.ItemDataRole.UserRole, p.id)
                item.setData(Qt.ItemDataRole.UserRole + 1, p.name)
                item.setData(Qt.ItemDataRole.UserRole + 2, p.price)
                if p.id in already:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                    item.setText(item.text() + "   (added)")
                self.results_list.addItem(item)

    # ── Table (right side) ───────────────────────────────────────────────

    def _rebuild_table(self):
        self.table.setRowCount(len(self._items))
        for row, item in enumerate(self._items):
            self._fill_row(row, item)

    def _fill_row(self, row: int, item: dict):
        self.table.setItem(row, COL_PRODUCT, QTableWidgetItem(item["name"]))
        self.table.setItem(row, COL_PRICE, QTableWidgetItem(f"{item['price']:.2f}"))

        type_combo = QComboBox()
        type_combo.addItem("% off", "percent")
        type_combo.addItem("€ off", "fixed")
        type_combo.setCurrentIndex(0 if item["discount_type"] == "percent" else 1)
        type_combo.currentIndexChanged.connect(
            lambda _, it=item, combo=type_combo: self._on_type_changed(it, combo)
        )
        self.table.setCellWidget(row, COL_TYPE, type_combo)

        value_spin = QDoubleSpinBox()
        value_spin.setDecimals(2)
        value_spin.setMinimum(0.0)
        self._configure_value_spin(value_spin, item)
        value_spin.setValue(item["discount_value"])
        value_spin.valueChanged.connect(
            lambda v, it=item: self._on_value_changed(it, v)
        )
        self.table.setCellWidget(row, COL_VALUE, value_spin)

        new_price_item = QTableWidgetItem("")
        new_price_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.table.setItem(row, COL_NEW_PRICE, new_price_item)

        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(lambda _, it=item: self._remove_item(it))
        self.table.setCellWidget(row, COL_REMOVE, remove_btn)

        self._update_new_price(row, item)

    @staticmethod
    def _configure_value_spin(spin: QDoubleSpinBox, item: dict):
        if item["discount_type"] == "percent":
            spin.setMaximum(100.0)
        else:
            spin.setMaximum(max(item["price"], 0.01))

    def _row_of(self, item: dict) -> int | None:
        for row, it in enumerate(self._items):
            if it is item:
                return row
        return None

    def _on_type_changed(self, item: dict, combo: QComboBox):
        item["discount_type"] = combo.currentData()
        # Clamp the current value into the new unit's valid range (e.g. a
        # €5 discount becomes 5% rather than an out-of-range 500%) and
        # refresh the value spinbox's limits/suffix to match.
        row = self._row_of(item)
        if row is None:
            return
        spin: QDoubleSpinBox = self.table.cellWidget(row, COL_VALUE)
        spin.blockSignals(True)
        self._configure_value_spin(spin, item)
        if item["discount_value"] > spin.maximum():
            item["discount_value"] = spin.maximum()
        spin.setValue(item["discount_value"])
        spin.blockSignals(False)
        self._update_new_price(row, item)

    def _on_value_changed(self, item: dict, value: float):
        item["discount_value"] = value
        row = self._row_of(item)
        if row is not None:
            self._update_new_price(row, item)

    def _update_new_price(self, row: int, item: dict):
        price = item["price"]
        if item["discount_type"] == "percent":
            new_price = price * (1 - item["discount_value"] / 100)
            equivalent = f"(≈ {price - new_price:.2f} off)"
        else:
            new_price = price - item["discount_value"]
            pct = (item["discount_value"] / price * 100) if price else 0.0
            equivalent = f"(≈ {pct:.0f}% off)"
        new_price = max(new_price, 0.0)
        cell = self.table.item(row, COL_NEW_PRICE)
        cell.setText(f"{new_price:.2f}  {equivalent}")

    def _add_selected_result(self):
        item_widget = self.results_list.currentItem()
        if item_widget is None or not (item_widget.flags() & Qt.ItemFlag.ItemIsEnabled):
            return
        pid = item_widget.data(Qt.ItemDataRole.UserRole)
        if pid in self._current_product_ids():
            return
        self._items.append({
            "product_id": pid,
            "name": item_widget.data(Qt.ItemDataRole.UserRole + 1),
            "price": item_widget.data(Qt.ItemDataRole.UserRole + 2),
            "discount_type": "percent",
            "discount_value": 10.0,
        })
        self._rebuild_table()
        self._run_search()  # re-mark the just-added row as "(added)"

    def _remove_item(self, item: dict):
        self._items.remove(item)
        self._rebuild_table()
        self._run_search()

    # ── Confirm ──────────────────────────────────────────────────────────

    def on_ok(self):
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Promo", "Name cannot be empty.")
            return
        if name.lower() != self._original and name.lower() in self._existing:
            QMessageBox.warning(self, "Promo", f"“{name}” already exists.")
            return
        if self.date.isChecked():
            start = self.start_edit.date().toPyDate()
            end = self.end_edit.date().toPyDate()
            if end < start:
                QMessageBox.warning(self, "Promo", "End date can't be before the start date.")
                return
        else:
            start = end = None  # indefinite — always active until removed/edited

        self.promo_name = name
        self.start_date = start
        self.end_date = end
        self.is_active = self.active_check.isChecked()
        self.items = [
            {
                "product_id": it["product_id"],
                "discount_type": it["discount_type"],
                "discount_value": it["discount_value"],
            }
            for it in self._items
        ]
        self.accept()
