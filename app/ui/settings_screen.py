"""
Settings Screen
Store info, receipt printer, label printer configuration.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QPushButton, QGroupBox, QLabel, QMessageBox, QFileDialog,
    QListWidget, QListWidgetItem, QTabWidget
)
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt, pyqtSignal
from app.core.database import get_session
from app.core.label_service import LabelPrinterService
from app.core.product_service import ProductService
from app.core.receipt_service import PrinterError, ReceiptService
from app.core.settings_service import SettingsService
from app.constants import BUTTON_HEIGHT_LG, COLOR_BORDER_LIGHT, LOGO_PREVIEW_SIZE
from app.ui.dialogs.category_dialog import CategoryDialog
from app.ui.dialogs.promo_dialog import PromoDialog
from app.ui.dialogs.shortcut_dialog import ShortcutDialog
from app.utils.utils import FunctionButton


class SettingsScreen(QWidget):
    settings_saved = pyqtSignal()
    navigate = pyqtSignal(int)


    def __init__(self):
        super().__init__()
        self._logo_path = ""
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        tabs = QTabWidget()
        layout.addWidget(tabs)

        general_tab = QWidget()
        left_col = QVBoxLayout(general_tab)

        printers_tab = QWidget()
        printers_row = QHBoxLayout(printers_tab)
        printers_row.setSpacing(15)

        catalog_tab = QWidget()
        catalog_row = QHBoxLayout(catalog_tab)
        catalog_row.setSpacing(15)
        sc_col = QVBoxLayout()
        cats_col = QVBoxLayout()
        promos_col = QVBoxLayout()
        catalog_row.addLayout(sc_col, 1)
        catalog_row.addLayout(cats_col, 1)
        catalog_row.addLayout(promos_col, 1)

        tabs.addTab(general_tab, "General")
        tabs.addTab(printers_tab, "Printers")
        tabs.addTab(catalog_tab, "Catalog")

        # ── Store info ────────────────────────────────────────────────────────
        store_group = QGroupBox("Store Information")
        store_form = QFormLayout(store_group)

        self.store_name = QLineEdit()
        self.store_address = QLineEdit()
        self.store_vat = QLineEdit()
        self.store_phone = QLineEdit()
        self.store_email = QLineEdit()
        self.currency = QLineEdit()
        self.currency.setPlaceholderText("e.g. €")
        self.receipt_footer = QLineEdit()
        self.browse_logo = QPushButton("Browse Logo")
        self.browse_logo.clicked.connect(self._load_logo)

        self.logo_preview = QLabel()
        self.logo_preview.setFixedSize(*LOGO_PREVIEW_SIZE)
        self.logo_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logo_preview.setStyleSheet(f"border: 1px solid {COLOR_BORDER_LIGHT};")

        logo_row = QHBoxLayout()
        logo_row.addWidget(self.browse_logo)
        logo_row.addWidget(self.logo_preview)
        logo_row.addStretch()

        store_form.addRow("Store Name:", self.store_name)
        store_form.addRow("Address:", self.store_address)
        store_form.addRow("Phone:", self.store_phone)
        store_form.addRow("Vat Number:", self.store_vat)
        store_form.addRow("Email: ", self.store_email)
        store_form.addRow("Currency Symbol:", self.currency)
        store_form.addRow("Receipt Footer:", self.receipt_footer)
        store_form.addRow("Logo:", logo_row)
        left_col.addWidget(store_group)
        left_col.addStretch()

        sc_group = QGroupBox("Shortcuts")
        sc_layout = QVBoxLayout(sc_group)
        self.shortcuts_list = QListWidget()
        self.shortcuts_list.setSelectionBehavior(QListWidget.SelectionBehavior.SelectRows)
        sc_layout.addWidget(self.shortcuts_list)
        sc_col.addWidget(sc_group)
        self._reload_shortcuts()
        btn_add_sc = FunctionButton("Add")
        btn_add_sc.clicked.connect(self._on_add_sc)
        btn_edit_sc = FunctionButton("Edit")
        btn_edit_sc.clicked.connect(self._on_edit_sc)
        btn_remove_sc = FunctionButton("Remove")
        btn_remove_sc.clicked.connect(self._on_remove_sc)
        sc_btn_layout = QHBoxLayout()
        sc_btn_layout.addWidget(btn_add_sc)
        sc_btn_layout.addWidget(btn_edit_sc)
        sc_btn_layout.addWidget(btn_remove_sc)
        sc_col.addLayout(sc_btn_layout)

        # ── Printer config ────────────────────────────────────────────────────
        printer_group = QGroupBox("Receipt Printer (USB)")
        printer_form = QFormLayout(printer_group)

        self.receipt_vendor = QLineEdit()
        self.receipt_vendor.setPlaceholderText("e.g. 0x04b8")
        self.receipt_product = QLineEdit()
        self.receipt_product.setPlaceholderText("e.g. 0x0202")

        printer_form.addRow("Vendor ID:", self.receipt_vendor)
        printer_form.addRow("Product ID:", self.receipt_product)

        test_btn = QPushButton("Test Print")
        test_btn.clicked.connect(self._test_print)
        printer_form.addRow("", test_btn)
        printers_row.addWidget(printer_group)

        # ── Label printer config ─────────────────────────────────────────────
        label_group = QGroupBox("Label Printer (USB)")
        label_form = QFormLayout(label_group)

        self.label_vendor = QLineEdit()
        self.label_vendor.setPlaceholderText("e.g. 0x1504")
        self.label_product = QLineEdit()
        self.label_product.setPlaceholderText("e.g. 0x0037")

        label_form.addRow("Vendor ID:", self.label_vendor)
        label_form.addRow("Product ID:", self.label_product)

        label_test_btn = QPushButton("Test Print")
        label_test_btn.clicked.connect(self._test_print_label)
        label_form.addRow("", label_test_btn)
        printers_row.addWidget(label_group)

        # ── Categories ─────────────────────────────────────────────
        cats_group = QGroupBox("Categories")
        cats_layout = QVBoxLayout(cats_group)
        self.categories_list = QListWidget()
        self.categories_list.setSelectionBehavior(QListWidget.SelectionBehavior.SelectRows)
        cats_layout.addWidget(self.categories_list)
        cats_col.addWidget(cats_group)
        self._reload_categories()
        btn_add = FunctionButton("Add")
        btn_add.clicked.connect(self._on_add)
        btn_remove = FunctionButton("Remove")
        btn_remove.clicked.connect(self._on_remove)
        btn_edit = FunctionButton("Edit")
        btn_edit.clicked.connect(self._on_edit)
        cats_btn_layout = QHBoxLayout()
        cats_btn_layout.addWidget(btn_add)
        cats_btn_layout.addWidget(btn_edit)
        cats_btn_layout.addWidget(btn_remove)
        cats_col.addLayout(cats_btn_layout)

        # ── Promos ─────────────────────────────────────────────────
        promos_group = QGroupBox("Promos")
        promos_layout = QVBoxLayout(promos_group)
        self.promos_list = QListWidget()
        self.promos_list.setSelectionBehavior(QListWidget.SelectionBehavior.SelectRows)
        promos_layout.addWidget(self.promos_list)
        promos_col.addWidget(promos_group)
        self._reload_promos()
        btn_add_promo = FunctionButton("Add")
        btn_add_promo.clicked.connect(self._on_add_promo)
        btn_edit_promo = FunctionButton("Edit")
        btn_edit_promo.clicked.connect(self._on_edit_promo)
        btn_remove_promo = FunctionButton("Remove")
        btn_remove_promo.clicked.connect(self._on_remove_promo)
        promos_btn_layout = QHBoxLayout()
        promos_btn_layout.addWidget(btn_add_promo)
        promos_btn_layout.addWidget(btn_edit_promo)
        promos_btn_layout.addWidget(btn_remove_promo)
        promos_col.addLayout(promos_btn_layout)


        # # ── Save ──────────────────────────────────────────────────────────────
        # save_btn = QPushButton("Save Information")
        # save_btn.setObjectName("primaryBtn")
        # save_btn.setFixedHeight(BUTTON_HEIGHT_LG)
        # save_btn.clicked.connect(self._save)

        ok_btn = FunctionButton("OK", "okBtn")
        ok_btn.setFixedHeight(BUTTON_HEIGHT_LG)
        ok_btn.clicked.connect(self._on_ok)
        # layout.addWidget(save_btn)
        layout.addWidget(ok_btn)
        layout.addStretch()


    def _show_logo_preview(self, path: str):
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            pixmap = pixmap.scaled(
                self.logo_preview.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.logo_preview.setPixmap(pixmap)

    def _load_logo(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Logo",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp)"
        )
        if path:
            self._logo_path = path
            self._show_logo_preview(path)

    def _load(self):
        with get_session() as session:
            s = SettingsService.get_all(session)
        self.store_name.setText(s.get("store_name", ""))
        self.store_address.setText(s.get("store_address", ""))
        self.store_vat.setText(s.get("store_vat", ""))
        self.store_phone.setText(s.get("store_phone", ""))
        self.store_email.setText(s.get("store_email", ""))
        self.currency.setText(s.get("currency_symbol", "€"))
        self.receipt_footer.setText(s.get("receipt_footer", ""))
        self.receipt_vendor.setText(s.get("receipt_printer_vendor_id", ""))
        self.receipt_product.setText(s.get("receipt_printer_product_id", ""))
        self.label_vendor.setText(s.get("label_printer_vendor_id", ""))
        self.label_product.setText(s.get("label_printer_product_id", ""))
        self._logo_path = s.get("logo_path", "")
        if self._logo_path:
            self._show_logo_preview(self._logo_path)

    def _reload_categories(self):
        """Repopulate the list from the DB, stashing each category id on its item."""
        self.categories_list.clear()
        with get_session() as session:
            for cat in ProductService.get_all_categories(session):
                item = QListWidgetItem(cat.name)
                item.setData(Qt.ItemDataRole.UserRole, cat.id)
                self.categories_list.addItem(item)

    def _reload_promos(self):
        """Repopulate the list from the DB, stashing each promo id on its item."""
        self.promos_list.clear()
        with get_session() as session:
            for promo in ProductService.get_all_promos(session):
                count = len(ProductService.get_promo_items(session, promo.id))
                products_text = f"{count} product{'s' if count != 1 else ''}"
                dates_text = f"{promo.start_date } → {promo.end_date}" if promo.end_date else "Indefinite"
                label = f"{promo.name} — {products_text} — {dates_text}"
                if not promo.is_active:
                    label += " (inactive)"
                elif not promo.is_current:
                    label += " (finished)"
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, promo.id)
                self.promos_list.addItem(item)

    def _reload_shortcuts(self):
        """Repopulate the list from the DB, stashing each shortcut id on its item."""
        self.shortcuts_list.clear()
        with get_session() as session:
            for sc in ProductService.get_all_shortcuts(session):
                item = QListWidgetItem(sc.name)
                item.setData(Qt.ItemDataRole.UserRole, sc.id)
                self.shortcuts_list.addItem(item)

    def _selected_category(self):
        """Return (id, name) of the selected category, or (None, None)."""
        item = self.categories_list.currentItem()
        if item is None:
            return None, None
        return item.data(Qt.ItemDataRole.UserRole), item.text()

    def _category_names(self):
        return [self.categories_list.item(i).text() for i in range(self.categories_list.count())]

    def _selected_promo_id(self):
        item = self.promos_list.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _promo_names(self, exclude_id=None):
        """Raw promo names for uniqueness checks — the list widget shows a
        formatted label (with discount/active info), not the bare name."""
        with get_session() as session:
            return [p.name for p in ProductService.get_all_promos(session) if p.id != exclude_id]

    def _shortcut_names(self):
        return [self.shortcuts_list.item(i).text() for i in range(self.shortcuts_list.count())]

    def _on_add(self):
        dialog = CategoryDialog(parent=self, existing_names=self._category_names())
        if not dialog.exec():
            return
        with get_session() as session:
            created = ProductService.create_category(session, dialog.cat_name)
        if created is None:
            QMessageBox.warning(self, "Category", "Could not add category — Category already exists.")
        self._reload_categories()

    def _selected_shortcut(self):
        """Return (id, name) of the selected shortcut, or (None, None)."""
        item = self.shortcuts_list.currentItem()
        if item is None:
            return None, None
        return item.data(Qt.ItemDataRole.UserRole), item.text()

    def _on_add_sc(self):
        dialog = ShortcutDialog(parent=self, existing_names=self._shortcut_names())
        if not dialog.exec():
            return
        with get_session() as session:
            created = ProductService.create_shortcut(session, dialog.sc_name)
            if created is None:
                QMessageBox.warning(self, "Shortcut", "Could not add shortcut — that name is already in use.")
            else:
                ProductService.set_shortcut_items(session, created.id, dialog.product_ids)
        self._reload_shortcuts()

    def _on_edit_sc(self):
        sc_id, sc_name = self._selected_shortcut()
        if sc_id is None:
            QMessageBox.information(self, "Shortcut", "Select a shortcut to edit.")
            return
        with get_session() as session:
            product_ids = ProductService.get_shortcut_product_ids(session, sc_id)
        dialog = ShortcutDialog(
            parent=self,
            sc_name=sc_name,
            product_ids=product_ids,
            existing_names=self._shortcut_names(),
        )
        if not dialog.exec():
            return
        with get_session() as session:
            if dialog.sc_name != sc_name:
                renamed = ProductService.rename_shortcut(session, sc_id, dialog.sc_name)
                if renamed is None:
                    QMessageBox.warning(self, "Shortcut", "Could not rename shortcut — that name is already in use.")
                    return
            ProductService.set_shortcut_items(session, sc_id, dialog.product_ids)
        self._reload_shortcuts()

    def _on_remove_sc(self):
        sc_id, sc_name = self._selected_shortcut()
        if sc_id is None:
            QMessageBox.information(self, "Shortcut", "Select a shortcut to remove.")
            return
        confirm = QMessageBox.question(
            self,
            "Remove Shortcut",
            f"Remove “{sc_name}”?\nThe products themselves are not affected.",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        with get_session() as session:
            ProductService.delete_shortcut(session, sc_id)
        self._reload_shortcuts()

    def _on_edit(self):
        cat_id, cat_name = self._selected_category()
        if cat_id is None:
            QMessageBox.information(self, "Category", "Select a category to edit.")
            return
        dialog = CategoryDialog(parent=self, cat_name=cat_name, existing_names=self._category_names())
        if not dialog.exec() or dialog.cat_name == cat_name:
            return
        with get_session() as session:
            renamed = ProductService.rename_category(session, cat_id, dialog.cat_name)
        if renamed is None:
            QMessageBox.warning(self, "Category", "Could not rename category — that name is already in use.")
        self._reload_categories()

    def _on_remove(self):
        cat_id, cat_name = self._selected_category()
        if cat_id is None:
            QMessageBox.information(self, "Category", "Select a category to remove.")
            return
        confirm = QMessageBox.question(
            self,
            "Remove Category",
            f"Remove “{cat_name}”?\nProducts in this category will be left uncategorized.",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        with get_session() as session:
            ProductService.delete_category(session, cat_id)
        self._reload_categories()

    def _on_add_promo(self):
        dialog = PromoDialog(parent=self, existing_names=self._promo_names())
        if not dialog.exec():
            return
        with get_session() as session:
            created = ProductService.create_promo(
                session, dialog.promo_name, dialog.start_date,
                dialog.end_date, dialog.is_active,
            )
            if created is None:
                QMessageBox.warning(self, "Promo", "Could not add promo — that name is already in use.")
            else:
                ProductService.set_promo_items(session, created.id, dialog.items)
        self._reload_promos()

    def _on_edit_promo(self):
        promo_id = self._selected_promo_id()
        if promo_id is None:
            QMessageBox.information(self, "Promo", "Select a promo to edit.")
            return
        with get_session() as session:
            promo = next((p for p in ProductService.get_all_promos(session) if p.id == promo_id), None)
            if not promo:
                return
            items = [
                {
                    "product_id": pi.product_id,
                    "discount_type": pi.discount_type,
                    "discount_value": pi.discount_value,
                }
                for pi in ProductService.get_promo_items(session, promo_id)
            ]
            promo_name, start_date, end_date, is_active = (
                promo.name, promo.start_date, promo.end_date, promo.is_active,
            )
        dialog = PromoDialog(
            parent=self, promo_name=promo_name, start_date=start_date,
            end_date=end_date, is_active=is_active,
            existing_names=self._promo_names(exclude_id=promo_id), items=items,
        )
        if not dialog.exec():
            return
        with get_session() as session:
            updated = ProductService.update_promo(
                session, promo_id, dialog.promo_name, dialog.start_date,
                dialog.end_date, dialog.is_active,
            )
            if updated is None:
                QMessageBox.warning(self, "Promo", "Could not update promo — that name is already in use.")
            else:
                ProductService.set_promo_items(session, promo_id, dialog.items)
        self._reload_promos()

    def _on_remove_promo(self):
        promo_id = self._selected_promo_id()
        if promo_id is None:
            QMessageBox.information(self, "Promo", "Select a promo to remove.")
            return
        confirm = QMessageBox.question(
            self,
            "Remove Promo",
            "Remove this promo?",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        with get_session() as session:
            ProductService.delete_promo(session, promo_id)
        self._reload_promos()

    def _save(self):
        with get_session() as session:
            SettingsService.set(session, "store_name", self.store_name.text())
            SettingsService.set(session, "store_address", self.store_address.text())
            SettingsService.set(session, "store_phone", self.store_phone.text())
            SettingsService.set(session, "store_vat", self.store_vat.text())
            SettingsService.set(session, "store_email", self.store_email.text())
            SettingsService.set(session, "currency_symbol", self.currency.text())
            SettingsService.set(session, "receipt_footer", self.receipt_footer.text())
            SettingsService.set(session, "receipt_printer_vendor_id", self.receipt_vendor.text())
            SettingsService.set(session, "receipt_printer_product_id", self.receipt_product.text())
            SettingsService.set(session, "label_printer_vendor_id", self.label_vendor.text())
            SettingsService.set(session, "label_printer_product_id", self.label_product.text())
            if getattr(self, "_logo_path", ""):
                SettingsService.set(session, "logo_path", self._logo_path)
        QMessageBox.information(self, "Saved", "Settings saved successfully.")
        self.settings_saved.emit()

    def _on_ok(self):
        self._save()
        self.navigate.emit(0)

    def _test_print(self):
        try:
            ReceiptService.test_print(self.receipt_vendor.text(), self.receipt_product.text())
        except PrinterError as e:
            QMessageBox.warning(self, "Test Print Failed", str(e))
        else:
            QMessageBox.information(self, "Test Print", "Test page sent to the printer.")

    def _test_print_label(self):
        try:
            LabelPrinterService.test_print(self.label_vendor.text(), self.label_product.text())
        except PrinterError as e:
            QMessageBox.warning(self, "Test Print Failed", str(e))
        else:
            QMessageBox.information(self, "Test Print", "Test label sent to the printer.")
