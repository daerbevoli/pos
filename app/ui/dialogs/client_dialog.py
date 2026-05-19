"""
Client Dialog
Add or edit a client.
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit,
    QPushButton, QHBoxLayout, QMessageBox
)
from PyQt6.QtCore import Qt, QEvent

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

        self._fields = [self.name, self.address, self.vatNumber, self.email, self.phone]
        for field in self._fields:
            field.installEventFilter(self)

        up_btn = QPushButton("↑")
        down_btn = QPushButton("↓")
        up_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        down_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        up_btn.clicked.connect(lambda: self._navigate(-1))
        down_btn.clicked.connect(lambda: self._navigate(1))

        up_down_col = QVBoxLayout()
        up_down_col.addStretch()
        up_down_col.addWidget(up_btn)
        up_down_col.addWidget(down_btn)
        up_down_col.addStretch()

        form_row = QHBoxLayout()
        form_row.addLayout(form)
        form_row.addLayout(up_down_col)
        layout.addLayout(form_row)

        btn_row = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        save_btn = QPushButton("Save")
        save_btn.setObjectName("primaryBtn")
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Up:
                self._navigate(-1)
                return True
            elif key == Qt.Key.Key_Down:
                self._navigate(1)
                return True
        return super().eventFilter(obj, event)

    def _navigate(self, direction: int):
        focused = self.focusWidget()
        idx = self._fields.index(focused) if focused in self._fields else 0
        self._fields[(idx + direction) % len(self._fields)].setFocus()

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
