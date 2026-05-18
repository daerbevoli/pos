"""
Settings Screen
Store info, receipt printer, label printer configuration.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QPushButton, QGroupBox, QLabel, QMessageBox, QFileDialog
)
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt, pyqtSignal
from app.core.database import get_session
from app.core.settings_service import SettingsService


class SettingsScreen(QWidget):
    settings_saved = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._logo_path = ""
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # ── Store info ────────────────────────────────────────────────────────
        store_group = QGroupBox("Store Information")
        store_form = QFormLayout(store_group)

        self.store_name = QLineEdit()
        self.store_address = QLineEdit()
        self.store_phone = QLineEdit()
        self.currency = QLineEdit()
        self.currency.setPlaceholderText("e.g. €")
        self.receipt_footer = QLineEdit()
        self.browse_logo = QPushButton("Browse Logo")
        self.browse_logo.clicked.connect(self._load_logo)

        self.logo_preview = QLabel()
        self.logo_preview.setFixedSize(120, 60)
        self.logo_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logo_preview.setStyleSheet("border: 1px solid #ccc;")

        logo_row = QHBoxLayout()
        logo_row.addWidget(self.browse_logo)
        logo_row.addWidget(self.logo_preview)
        logo_row.addStretch()

        store_form.addRow("Store Name:", self.store_name)
        store_form.addRow("Address:", self.store_address)
        store_form.addRow("Phone:", self.store_phone)
        store_form.addRow("Currency Symbol:", self.currency)
        store_form.addRow("Receipt Footer:", self.receipt_footer)
        store_form.addRow("Logo:", logo_row)
        layout.addWidget(store_group)

        # ── Printer config ────────────────────────────────────────────────────
        printer_group = QGroupBox("Receipt Printer (USB)")
        printer_form = QFormLayout(printer_group)

        self.receipt_vendor = QLineEdit()
        self.receipt_vendor.setPlaceholderText("e.g. 0x04b8")
        self.receipt_product = QLineEdit()
        self.receipt_product.setPlaceholderText("e.g. 0x0202")

        printer_form.addRow("Vendor ID:", self.receipt_vendor)
        printer_form.addRow("Product ID:", self.receipt_product)

        test_btn = QPushButton("🖨 Test Print")
        test_btn.clicked.connect(self._test_print)
        printer_form.addRow("", test_btn)
        layout.addWidget(printer_group)

        # ── Save ──────────────────────────────────────────────────────────────
        save_btn = QPushButton("💾  Save Settings")
        save_btn.setObjectName("primaryBtn")
        save_btn.setFixedHeight(50)
        save_btn.clicked.connect(self._save)
        layout.addWidget(save_btn)
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
        self.store_phone.setText(s.get("store_phone", ""))
        self.currency.setText(s.get("currency_symbol", "€"))
        self.receipt_footer.setText(s.get("receipt_footer", ""))
        self.receipt_vendor.setText(s.get("receipt_printer_vendor_id", ""))
        self.receipt_product.setText(s.get("receipt_printer_product_id", ""))
        self._logo_path = s.get("logo_path", "")
        if self._logo_path:
            self._show_logo_preview(self._logo_path)

    def _save(self):
        with get_session() as session:
            SettingsService.set(session, "store_name", self.store_name.text())
            SettingsService.set(session, "store_address", self.store_address.text())
            SettingsService.set(session, "store_phone", self.store_phone.text())
            SettingsService.set(session, "currency_symbol", self.currency.text())
            SettingsService.set(session, "receipt_footer", self.receipt_footer.text())
            SettingsService.set(session, "receipt_printer_vendor_id", self.receipt_vendor.text())
            SettingsService.set(session, "receipt_printer_product_id", self.receipt_product.text())
            if getattr(self, "_logo_path", ""):
                SettingsService.set(session, "logo_path", self._logo_path)
        QMessageBox.information(self, "Saved", "Settings saved successfully.")
        self.settings_saved.emit()

    def _test_print(self):
        # TODO: send a test page to the receipt printer
        QMessageBox.information(self, "Test Print", "Test print feature coming soon.")
