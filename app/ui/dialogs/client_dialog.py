"""
Client Dialog
Add or edit a client.
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit,
    QPushButton, QHBoxLayout, QMessageBox
)

from app.models.models import Client

class ClientDialog(QDialog):
    def __init__(self, parent=None, client: Client = None):
        super().__init__(parent)
        self.client = client
        self.setWindowTitle("Edit Client" if client else "Add Client")
        self.setMinimumWidth(480)
        self._build_ui()
        if client:
            self._populate(client)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.name = QLineEdit()
        self.name.setPlaceholderText("Name")
        form.addRow("Name:", self.name)

        self.address = QLineEdit()
        self.address.setPlaceholderText("Address")
        form.addRow("Address:", self.address)

        self.vatNumber = QLineEdit()
        self.vatNumber.setPlaceholderText("VAT Number")
        form.addRow("VAT Number:", self.vatNumber)

        self.email = QLineEdit()
        self.email.setPlaceholderText("Email")
        form.addRow("Email:", self.email)

        self.phone = QLineEdit()
        self.phone.setPlaceholderText("Phone")
        form.addRow("Phone:", self.phone)

        layout.addLayout(form)

        btn_row = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        save_btn = QPushButton("Save")
        save_btn.setObjectName("primaryBtn")
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)



    def _populate(self, client: Client):
        self.name.setText(client.name)
        self.address.setText(client.address)
        self.vatNumber.setText(client.vatNumber)
        self.email.setText(client.email)
        self.phone.setText(client.phone)

    def _save(self):
        if not self.name.text().strip():
            QMessageBox.warning(self, "Validation", "Client name is required.")
            return
        if not self.vatNumber.text().strip():
            QMessageBox.warning(self, "Validation", "VAT number is required.")
            return
        self.accept()

    def get_data(self) -> dict:
        return {
            "name": self.name.text(),
            "address": self.address.text(),
            "vatNumber": self.vatNumber.text(),
            "email": self.email.text(),
            "phone": self.phone.text()
        }
