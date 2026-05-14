"""
Payment Dialog
Shown when operator clicks Cash or Card. Handles cash tendered / change.
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QGridLayout
)
from PyQt6.QtCore import Qt
from app.core.sales_service import Cart


class PaymentDialog(QDialog):
    def __init__(self, cart: Cart, method: str, currency: str, parent=None):
        super().__init__(parent)
        self.cart = cart
        self.method = method
        self.currency = currency
        self.amount_tendered = cart.total  # default: exact amount
        self.setWindowTitle("Payment")
        self.setMinimumWidth(400)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Total
        total_label = QLabel(f"Total Due: {self.currency}{self.cart.total:.2f}")
        total_label.setObjectName("paymentTotal")
        total_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(total_label)

        if self.method == "cash":
            layout.addWidget(QLabel("Amount Tendered:"))
            self.tendered_input = QLineEdit(f"{self.cart.total:.2f}")
            self.tendered_input.setFixedHeight(50)
            self.tendered_input.textChanged.connect(self._update_change)
            layout.addWidget(self.tendered_input)

            # Quick cash buttons
            quick = QGridLayout()
            common_amounts = [5, 10, 20, 50, 100]
            for i, amount in enumerate(common_amounts):
                btn = QPushButton(f"{self.currency}{amount}")
                btn.setFixedHeight(44)
                btn.clicked.connect(lambda _, a=amount: self._set_tendered(a))
                quick.addWidget(btn, 0, i)
            layout.addLayout(quick)

            self.change_label = QLabel(f"Change: {self.currency}0.00")
            self.change_label.setObjectName("changeLabel")
            self.change_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(self.change_label)
            self._update_change()

        else:
            layout.addWidget(QLabel("Process card payment on terminal, then confirm."))

        # Confirm / Cancel
        btn_row = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        confirm_btn = QPushButton("✓ Confirm Payment")
        confirm_btn.setObjectName("primaryBtn")
        confirm_btn.setFixedHeight(54)
        confirm_btn.clicked.connect(self._confirm)
        btn_row.addWidget(confirm_btn)
        layout.addLayout(btn_row)

    def _set_tendered(self, amount: float):
        self.tendered_input.setText(f"{amount:.2f}")

    def _update_change(self):
        try:
            tendered = float(self.tendered_input.text())
            change = tendered - self.cart.total
            self.change_label.setText(
                f"Change: {self.currency}{change:.2f}" if change >= 0
                else f"⚠️ Insufficient: {self.currency}{abs(change):.2f} short"
            )
        except ValueError:
            self.change_label.setText("Change: —")

    def _confirm(self):
        if self.method == "cash":
            try:
                self.amount_tendered = float(self.tendered_input.text())
                if self.amount_tendered < self.cart.total:
                    return  # Don't allow underpayment
            except ValueError:
                return
        self.accept()
