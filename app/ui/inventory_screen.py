"""
Inventory Screen
Table list of products on top; selecting a row shows an "Artikel
selecteren"-style detail panel below, with a field list on the left and a
function-key grid on the right (New/Modify/Delete article, Price label,
Shelf label, Pre-pack, Print shelf, Search by barcode/key, OK/Cancel).
New/Modify article edit the fields inline in the panel itself; while a
Tax/Unit/Category field is focused, the product table is swapped out for a
choice-button grid in the same spot.
"""
import logging

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QLabel,
    QHeaderView, QMessageBox, QComboBox, QFrame, QSizePolicy,
    QDoubleSpinBox, QStackedWidget
)
from PyQt6.QtCore import Qt, QEvent, QLocale, pyqtSignal

from app.core.database import get_session
from app.core.product_service import ProductService
from app.models.models import Product
from app.ui.widgets.form_fields import PickerDisplay, FieldRow
from app.ui.dialogs.stock_adjustment_dialog import StockAdjustmentDialog
from app.utils.utils import TapToDismissOverlay, FunctionButton
from app.constants import (
    BUTTON_HEIGHT_XS,
    ICON_BUTTON_SIZE,
    INPUT_HEIGHT,
    INPUT_HEIGHT_COMPACT,
    MARGIN_COMPACT,
    ROW_HEIGHT_LARGE,
    SPACING_MD,
    SPACING_XS,
)


class ArticleDetailPanel(QFrame):
    """
    Detail view for a single product: a field list on the left (editable
    inline for New/Modify), a function-key grid on the right. Hidden until a
    row is selected in the table above it.
    """
    navigate = pyqtSignal(int)
    selected_product = pyqtSignal(int)

    def __init__(self, parent_screen):
        super().__init__(parent_screen)
        self.parent_screen = parent_screen
        self.current_product_id = None
        self._mode = "display"  # "display" | "new" | "edit"

        # Picker state
        self._tax_val = "0"
        self._unit_val = "pcs"
        self._category_id = None
        self._category_name = "— No Category —"
        self._categories: list[tuple[str, int]] = []

        self._active_row: FieldRow | None = None
        self._active_picker: str | None = None

        self.overlay = TapToDismissOverlay(self)

        self.setObjectName("articleDetailPanel")
        self._load_categories()
        self._build_ui()

    # ── Setup ────────────────────────────────────────────────────────────

    def _load_categories(self):
        with get_session() as session:
            cats = ProductService.get_all_categories(session)
            self._categories = [(c.name, c.id) for c in cats]

    def _build_ui(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(3, 3, 3, 3)
        outer.setSpacing(SPACING_XS)

        # ── Left: field list ────────────────────────────────────────────
        field_frame = QFrame()
        field_frame.setObjectName("articleFieldFrame")
        field_col = QVBoxLayout(field_frame)
        field_col.setContentsMargins(6, 6, 6, 6)
        field_col.setSpacing(SPACING_XS)

        title_row = QHBoxLayout()
        self._title_label = QLabel("Select article")
        self._title_label.setObjectName("articleDetailTitle")
        title_row.addWidget(self._title_label)
        title_row.addStretch()
        self._active_status_label = QLabel("—")
        self._active_status_label.setObjectName("articleFieldValue")
        title_row.addWidget(self._active_status_label)
        field_col.addLayout(title_row)

        self.barcode = QLineEdit()
        self.barcode.setPlaceholderText("")
        self.barcode.setMaxLength(14)
        self.barcode.setMinimumHeight(INPUT_HEIGHT_COMPACT)

        self.name = QLineEdit()
        self.name.setMinimumHeight(INPUT_HEIGHT_COMPACT)

        self.price = QDoubleSpinBox()
        self.price.setLocale(QLocale.c())
        self.price.setPrefix("€ ")
        self.price.setMaximum(99999.99)
        self.price.setDecimals(2)
        self.price.setMinimumHeight(INPUT_HEIGHT_COMPACT)

        self.tax_display = PickerDisplay(f"{self._tax_val} %")

        self.stock = QDoubleSpinBox()
        self.stock.setLocale(QLocale.c())
        self.stock.setMaximum(999999)
        self.stock.setDecimals(2)
        self.stock.setMinimumHeight(INPUT_HEIGHT_COMPACT)

        self.min_stock = QDoubleSpinBox()
        self.min_stock.setLocale(QLocale.c())
        self.min_stock.setMaximum(999999)
        self.min_stock.setDecimals(2)
        self.min_stock.setValue(5)
        self.min_stock.setMinimumHeight(INPUT_HEIGHT_COMPACT)

        self.unit_display = PickerDisplay(self._unit_val)
        self.category_display = PickerDisplay(self._category_name)

        rows_spec = [
            ("Barcode",          self.barcode,          None),
            ("Name *",           self.name,             None),
            ("Selling Price *",  self.price,            None),
            ("Tax *",              self.tax_display,    "tax"),
            ("Stock Quantity",   self.stock,            None),
            ("Min Stock Level",  self.min_stock,        None),
            ("Unit *",             self.unit_display,   "unit"),
            ("Category",         self.category_display, "category"),
        ]

        self._fields = []
        self._row_map: dict = {}
        self._picker_map: dict = {}

        for label_text, widget, picker_key in rows_spec:
            row = FieldRow(label_text, widget)
            field_col.addWidget(row)
            self._fields.append(widget)
            self._row_map[widget] = row
            if picker_key:
                self._picker_map[widget] = picker_key
            widget.installEventFilter(self)

        field_col.addStretch()
        outer.addWidget(field_frame, stretch=3)

        # ── Picker page (placed by InventoryScreen in its table stack) ───
        self.picker_page = QFrame()
        self.picker_page.setObjectName("pickerPanel")
        picker_vbox = QVBoxLayout(self.picker_page)
        picker_vbox.setContentsMargins(5, 4, 5, 4)
        picker_vbox.setSpacing(3)

        self._picker_title = QLabel("")
        self._picker_title.setObjectName("pickerTitle")
        picker_vbox.addWidget(self._picker_title)

        self._picker_grid = QGridLayout()
        self._picker_grid.setSpacing(3)
        picker_vbox.addLayout(self._picker_grid)
        picker_vbox.addStretch()

        # ── Right: function-key grid ────────────────────────────────────
        grid = QGridLayout()
        grid.setSpacing(SPACING_XS)

        self.btn_new = FunctionButton("New\narticle", "newArticleBtn")
        self.btn_modify = FunctionButton("Modify\narticle", "secFunc")
        self.btn_delete = FunctionButton("Delete\narticle", "deleteArticleBtn")
        self.btn_error = FunctionButton("Error", "errorBtn")

        self.btn_print_label = FunctionButton("Print\nlabel", "secFunc")
        self.btn_cancel = FunctionButton("Cancel", "cancelBtn")

        self.btn_up = FunctionButton("Up", "SecFunc")
        self.btn_down = FunctionButton("Down", "SecFunc")

        self.btn_search_barcode = FunctionButton("Search by\nbarcode", "secFunc")
        self.btn_search_key = FunctionButton("Search by\nkey", "secFunc")
        self.btn_ok = FunctionButton("OK", "okBtn")


        layout_map = [
            (self.btn_new, 0, 0), (self.btn_modify, 0, 1),
            (self.btn_delete, 0, 2), (self.btn_error, 0, 3),

            (self.btn_up, 1, 0), (self.btn_cancel, 1, 3),

            (self.btn_down, 2, 0), (self.btn_search_barcode, 2, 1),
            (self.btn_search_key, 2, 2), (self.btn_ok, 2, 3)
        ]
        for widget, r, c in layout_map:
            widget.setMinimumHeight(BUTTON_HEIGHT_XS)
            grid.addWidget(widget, r, c)

        for c in range(4):
            grid.setColumnStretch(c, 1)
        for r in range(5):
            grid.setRowStretch(r, 1)

        outer.addLayout(grid, stretch=3)

        # Wire actions
        self.btn_new.clicked.connect(self._start_new)
        self.btn_modify.clicked.connect(self._start_edit)
        self.btn_delete.clicked.connect(self._on_delete)
        self.btn_error.clicked.connect(self._on_cancel)
        self.btn_cancel.clicked.connect(self._on_cancel)
        self.btn_ok.clicked.connect(self._on_ok)
        self.btn_search_barcode.clicked.connect(self._on_search_barcode)
        self.btn_search_key.clicked.connect(self._on_search_key)
        self.btn_up.clicked.connect(lambda: self._navigate(-1))
        self.btn_down.clicked.connect(lambda: self._navigate(1))

        self._set_edit_mode(False)

    # ── Event filter (focus tracking + keyboard nav + picker/table swap) ──

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.FocusIn:
            if self._active_row:
                self._active_row.set_active(False)
            row = self._row_map.get(obj)
            if row:
                self._active_row = row
                row.set_active(True)
            picker_key = self._picker_map.get(obj)
            self._refresh_picker(picker_key)
            if picker_key and self._mode in ("new", "edit"):
                self.parent_screen._show_picker_page()
            else:
                self.parent_screen._show_table_page()

        elif event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Up:
                self._navigate(-1)
                return True
            elif key == Qt.Key.Key_Down:
                self._navigate(1)
                return True
            elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                return True

        return super().eventFilter(obj, event)

    def _navigate(self, direction: int):
        focused = self.focusWidget()
        if focused not in self._fields:
            return
        idx = self._fields.index(focused)
        self._fields[(idx + direction) % len(self._fields)].setFocus()

    # ── Picker panel ─────────────────────────────────────────────────────

    def _refresh_picker(self, picker_key: str | None):
        self._active_picker = picker_key

        while self._picker_grid.count():
            item = self._picker_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if picker_key is None:
            self._picker_title.setText("")
            return

        titles = {"tax": "Tax Rate", "unit": "Unit", "category": "Category"}
        self._picker_title.setText(titles[picker_key])

        if picker_key == "tax":
            options = [("0 %", "0"), ("6 %", "6"), ("12 %", "12"), ("21 %", "21")]
            current = self._tax_val
            cols = 4
        elif picker_key == "unit":
            options = [(v, v) for v in ["pcs", "kg", "g", "liter", "ml", "pack", "box"]]
            current = self._unit_val
            cols = 4
        else:  # category
            options = [("— None —", None)] + [(name, cid) for name, cid in self._categories]
            current = self._category_id
            cols = 3

        for i, (label, value) in enumerate(options):
            btn = QPushButton(label)
            btn.setObjectName("pickerBtn")
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setProperty("selected", value == current)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.clicked.connect(lambda _, v=value, l=label: self._pick(v, l))
            self._picker_grid.addWidget(btn, i // cols, i % cols)

    def _pick(self, value, label: str):
        if self._active_picker == "tax":
            self._tax_val = value
            self.tax_display.setText(f"{value} %")
        elif self._active_picker == "unit":
            self._unit_val = value
            self.unit_display.setText(value)
        elif self._active_picker == "category":
            self._category_id = value
            self._category_name = label
            self.category_display.setText(label)
        self._refresh_picker(self._active_picker)

    # ── Mode switching ───────────────────────────────────────────────────

    def _set_edit_mode(self, enabled: bool):
        for widget in self._fields:
            if isinstance(widget, PickerDisplay):
                widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus if enabled else Qt.FocusPolicy.NoFocus)
                if not enabled:
                    widget.clearFocus()
            else:
                widget.setEnabled(enabled)
        self.btn_new.setEnabled(not enabled)
        self.btn_modify.setEnabled(not enabled and self.current_product_id is not None)
        self.btn_delete.setEnabled(not enabled and self.current_product_id is not None)
        self.parent_screen.table.setEnabled(not enabled)
        if not enabled:
            if self._active_row:
                self._active_row.set_active(False)
                self._active_row = None
            self.parent_screen._show_table_page()

    def _reset_fields_to_placeholder(self):
        self.barcode.clear()
        self.name.clear()
        self.price.setSpecialValueText(" ")
        self.price.setValue(self.price.minimum())
        self.stock.setSpecialValueText(" ")
        self.stock.setValue(self.stock.minimum())
        self.min_stock.setValue(5)
        self._tax_val = "0"
        self.tax_display.setText("0 %")
        self._unit_val = "pcs"
        self.unit_display.setText("pcs")
        self._category_id = None
        self._category_name = "—"
        self.category_display.setText(self._category_name)

    def _populate_fields(self, product):
        self.barcode.setText(product.barcode or "")
        self.name.setText(product.name)
        self.price.setValue(product.price)
        self.stock.setValue(product.stock_quantity)
        self.min_stock.setValue(product.min_stock_level)

        self._tax_val = str(product.tax)
        self.tax_display.setText(f"{product.tax} %")

        self._unit_val = product.unit
        self.unit_display.setText(product.unit)

        self._category_id = product.category_id
        self._category_name = "— No Category —"
        if product.category_id:
            for name, cid in self._categories:
                if cid == product.category_id:
                    self._category_name = name
                    break
        self.category_display.setText(self._category_name)

        is_active = getattr(product, "is_active", True)
        self._active_status_label.setText("Active" if is_active else "Inactive")

    # ── Display ──────────────────────────────────────────────────────────

    def show_product(self, product):
        self.current_product_id = product.id
        self._populate_fields(product)
        self._mode = "display"
        self._title_label.setText("Select article")
        self._set_edit_mode(False)
        self.show()

    def _clear(self):
        self.current_product_id = None
        self._mode = "display"
        self._reset_fields_to_placeholder()
        self._active_status_label.setText("—")
        self._title_label.setText("Select article")
        self._set_edit_mode(False)

    # ── Actions ──────────────────────────────────────────────────────────

    def _start_new(self):
        if self._mode != "display":
            return
        self._load_categories()
        self.current_product_id = None
        self._mode = "new"
        self._reset_fields_to_placeholder()
        self._active_status_label.setText("Active")
        self._title_label.setText("New article")
        self._set_edit_mode(True)
        self.barcode.setFocus()

    def _start_edit(self):
        if self.current_product_id is None or self._mode != "display":
            return
        self._load_categories()
        with get_session() as session:
            product = ProductService.get_by_id(session, self.current_product_id)
        if not product:
            return
        self._populate_fields(product)
        self._mode = "edit"
        self._title_label.setText("Modify article")
        self._set_edit_mode(True)
        self.barcode.setFocus()

    def _validate(self) -> bool:
        if not self.name.text().strip():
            self._show_overlay("Product name is required.")
            return False
        if self.price.value() <= 0:
            self._show_overlay("Price must be greater than 0.")
            return False
        return True

    def _collect_data(self) -> dict:
        return {
            "barcode": self.barcode.text().strip() or None,
            "name": self.name.text().strip(),
            "price": self.price.value(),
            "tax": int(self._tax_val),
            "stock_quantity": self.stock.value(),
            "min_stock_level": self.min_stock.value(),
            "unit": self._unit_val,
            "category_id": self._category_id,
        }

    def _on_ok(self):
        if self._mode in ("new", "edit"):
            if not self._validate():
                return
            data = self._collect_data()
            with get_session() as session:
                if self._mode == "new":
                    product = ProductService.create(session, **data)
                    self.current_product_id = product.id
                else:
                    ProductService.update(session, self.current_product_id, **data)
            self._mode = "display"
            self._set_edit_mode(False)
            saved_id = self.current_product_id
            # refresh() rebuilds the table (clearing selection along the way),
            # which resets current_product_id via _on_row_selected -> _clear();
            # saved_id keeps track of what to re-select afterward.
            self.parent_screen.refresh()
            if not self.parent_screen._select_product_row(saved_id):
                # Saved but filtered out of the current view (e.g. category/search
                # filter no longer matches) — still show it instead of going blank.
                with get_session() as session:
                    product = ProductService.get_by_id(session, saved_id)
                if product:
                    self.show_product(product)
                else:
                    self._clear()
        else:
            if self.current_product_id:
                self.parent_screen.selected_product.emit(self.current_product_id)
            self.parent_screen.navigate.emit(0)

    def _on_cancel(self):
        if self._mode == "new":
            self._clear()
        elif self._mode == "edit":
            product_id = self.current_product_id
            self._mode = "display"
            product = None
            if product_id:
                with get_session() as session:
                    product = ProductService.get_by_id(session, product_id)
            if product:
                self.show_product(product)
            else:
                self._clear()
        else:
            self.parent_screen.table.clearSelection()
            self._clear()
        self.parent_screen.search_input.setFocus()

    def _on_delete(self):
        if self.current_product_id is None:
            return
        self.parent_screen._delete_product(self.current_product_id)

    def _on_search_barcode(self):
        self.parent_screen.search_input.setFocus()
        self.parent_screen.search_input.setPlaceholderText("Scan or type barcode…")

    def _on_search_key(self):
        self.parent_screen.search_input.setFocus()
        self.parent_screen.search_input.setPlaceholderText("Search by name or barcode…")

    def _show_overlay(self, message: str, title: str = "", kind: str = "info"):
        self.overlay.show_message(message, title=title, kind=kind)


class InventoryScreen(QWidget):

    navigate = pyqtSignal(int)
    selected_product = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self._build_ui()
        self.refresh()


    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(SPACING_MD)

        # ── Product table (constructed early: ArticleDetailPanel references it) ─
        self.table = QTableWidget(0, 7)
        self.table.setObjectName("inventoryTable")
        self.table.setHorizontalHeaderLabels([
            "Barcode", "Name", "Category", "Price", "Tax", "Stock", "Unit"
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._on_row_selected)

        # ── Article detail panel (always visible) ─────────────────────────────
        self.detail_panel = ArticleDetailPanel(self)
        layout.addWidget(self.detail_panel)

        # ── Search / filter bar ───────────────────────────────────────────────
        toolbar = QHBoxLayout()

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("")
        self.search_input.setFixedHeight(INPUT_HEIGHT)
        self.search_input.returnPressed.connect(self._on_barcode_scan)
        self.search_input.textChanged.connect(self.refresh)
        toolbar.addWidget(self.search_input, stretch=1)

        self.category_filter = QComboBox()
        self.category_filter.setFixedHeight(INPUT_HEIGHT)
        self.category_filter.addItem("All Categories", None)
        self.category_filter.currentIndexChanged.connect(self.refresh)
        toolbar.addWidget(self.category_filter)

        self.low_stock_btn = QPushButton("Low Stock")
        self.low_stock_btn.setCheckable(True)
        self.low_stock_btn.setFixedHeight(INPUT_HEIGHT)
        self.low_stock_btn.toggled.connect(self.refresh)
        toolbar.addWidget(self.low_stock_btn)

        layout.addLayout(toolbar)

        # ── Table / picker-grid swap ────────────────────────────────────────────
        self.table_stack = QStackedWidget()
        self.table_stack.addWidget(self.table)
        self.table_stack.addWidget(self.detail_panel.picker_page)
        layout.addWidget(self.table_stack, stretch=1)

        # ── Summary row ───────────────────────────────────────────────────────
        self.summary_label = QLabel()
        layout.addWidget(self.summary_label)

        self._product_cache = {}

    def _show_picker_page(self):
        if hasattr(self, "table_stack"):
            self.table_stack.setCurrentWidget(self.detail_panel.picker_page)

    def _show_table_page(self):
        if hasattr(self, "table_stack"):
            self.table_stack.setCurrentWidget(self.table)

    def refresh(self):
        with get_session() as session:
            # Refresh category filter
            cats = ProductService.get_all_categories(session)
            current_cat = self.category_filter.currentData()
            self.category_filter.blockSignals(True)
            self.category_filter.clear()
            self.category_filter.addItem("All Categories", None)
            for cat in cats:
                self.category_filter.addItem(cat.name, cat.id)
            if current_cat:
                idx = self.category_filter.findData(current_cat)
                if idx >= 0:
                    self.category_filter.setCurrentIndex(idx)
            self.category_filter.blockSignals(False)

            # Get products
            query = self.search_input.text().strip()
            if query:
                products = ProductService.search(session, query)
            else:
                products = ProductService.get_all(session)

            cat_id = self.category_filter.currentData()
            if cat_id:
                products = [p for p in products if p.category_id == cat_id]

            if self.low_stock_btn.isChecked():
                products = [p for p in products if p.is_low_stock]

            self._populate_table(products, session)
            self.summary_label.setText(
                f"{len(products)} product(s) shown"
                + (f" — {sum(1 for p in products if p.is_low_stock)} low stock" if products else "")
            )
        self.search_input.setFocus()


    def _populate_table(self, products, session):
        self.table.setRowCount(0)
        self._product_cache = {}
        for p in products:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self._product_cache[row] = p.id

            self.table.setItem(row, 0, QTableWidgetItem(p.barcode or ""))
            self.table.setItem(row, 1, QTableWidgetItem(p.name))
            cat_name = p.category.name if p.category else "—"
            self.table.setItem(row, 2, QTableWidgetItem(cat_name))
            self.table.setItem(row, 3, QTableWidgetItem(f"€{p.price:.2f}"))
            self.table.setItem(row, 4, QTableWidgetItem(f"{p.tax}"))
            stock_item = QTableWidgetItem(f"{p.stock_quantity:.1f}")
            if p.is_low_stock:
                stock_item.setForeground(Qt.GlobalColor.red)
            self.table.setItem(row, 5, stock_item)
            self.table.setItem(row, 6, QTableWidgetItem(p.unit))

    # ── Detail panel wiring ─────────────────────────────────────────────────

    def _on_row_selected(self):
        row = self.table.currentRow()
        if row < 0 or row not in self._product_cache:
            self.detail_panel._clear()
            return
        product_id = self._product_cache[row]
        with get_session() as session:
            product = ProductService.get_by_id(session, product_id)
            if product:
                self.detail_panel.show_product(product)
            else:
                self.detail_panel._clear()

    def _add_product(self):
        self.detail_panel._start_new()

    def _edit_product(self, product_id: int):
        self.detail_panel.current_product_id = product_id
        self.detail_panel._start_edit()

    def _adjust_stock(self, product_id: int):
        with get_session() as session:
            product = ProductService.get_by_id(session, product_id)
            if not product:
                return
            dialog = StockAdjustmentDialog(product, self)
            if dialog.exec():
                data = dialog.get_data()
                ProductService.adjust_stock(session, product_id, **data)
        self.refresh()

    def _delete_product(self, product_id: int):
        reply = QMessageBox.question(
            self, "Deactivate Product",
            "This will hide the product from the POS. Sales history is preserved.\nContinue?"
        )
        if reply == QMessageBox.StandardButton.Yes:
            with get_session() as session:
                ProductService.deactivate(session, product_id)
            self.refresh()

    def _clear(self):
        self.navigate.emit(0)

    def _select_product_row(self, product_id: int) -> bool:
        """Selects product_id's row in the table if it's in the current
        (possibly filtered) view. Returns whether it found one."""
        for row, pid in self._product_cache.items():
            if pid == product_id:
                self.table.selectRow(row)
                return True
        return False

    def _on_barcode_scan(self):
        if self.detail_panel._mode != "display":
            return
        barcode = self.search_input.text().strip()
        if not barcode:
            return
        with get_session() as session:
            product = ProductService.get_by_barcode(session, barcode)

        self.search_input.blockSignals(True)
        self.search_input.clear()
        self.search_input.blockSignals(False)
        self.refresh()

        if not product:
            self.detail_panel._show_overlay(f"No product found for barcode '{barcode}'.")
            return
        if not self._select_product_row(product.id):
            self.detail_panel.show_product(product)


