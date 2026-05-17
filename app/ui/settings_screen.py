"""
Settings Screen
Store info, receipt printer, label printer configuration.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QPushButton, QGroupBox, QLabel, QMessageBox
)
from app.core.database import get_session
from app.core.settings_service import SettingsService


class SettingsScreen(QWidget):
    def __init__(self):
        super().__init__()
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
        self.tax_rate = QLineEdit()
        self.tax_rate.setPlaceholderText("e.g. 0.21 for 21%")
        self.currency = QLineEdit()
        self.currency.setPlaceholderText("e.g. €")
        self.receipt_footer = QLineEdit()

        store_form.addRow("Store Name:", self.store_name)
        store_form.addRow("Address:", self.store_address)
        store_form.addRow("Phone:", self.store_phone)
        store_form.addRow("Tax Rate:", self.tax_rate)
        store_form.addRow("Currency Symbol:", self.currency)
        store_form.addRow("Receipt Footer:", self.receipt_footer)
        store_form.addRow("Logo")
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

    def _load(self):
        with get_session() as session:
            s = SettingsService.get_all(session)
        self.store_name.setText(s.get("store_name", ""))
        self.store_address.setText(s.get("store_address", ""))
        self.store_phone.setText(s.get("store_phone", ""))
        self.tax_rate.setText(s.get("tax_rate", "0.0"))
        self.currency.setText(s.get("currency_symbol", "€"))
        self.receipt_footer.setText(s.get("receipt_footer", ""))
        self.receipt_vendor.setText(s.get("receipt_printer_vendor_id", ""))
        self.receipt_product.setText(s.get("receipt_printer_product_id", ""))

    def _save(self):
        with get_session() as session:
            SettingsService.set(session, "store_name", self.store_name.text())
            SettingsService.set(session, "store_address", self.store_address.text())
            SettingsService.set(session, "store_phone", self.store_phone.text())
            SettingsService.set(session, "tax_rate", self.tax_rate.text())
            SettingsService.set(session, "currency_symbol", self.currency.text())
            SettingsService.set(session, "receipt_footer", self.receipt_footer.text())
            SettingsService.set(session, "receipt_printer_vendor_id", self.receipt_vendor.text())
            SettingsService.set(session, "receipt_printer_product_id", self.receipt_product.text())
        QMessageBox.information(self, "Saved", "Settings saved successfully.")

    def _test_print(self):
        # TODO: send a test page to the receipt printer
        QMessageBox.information(self, "Test Print", "Test print feature coming soon.")
