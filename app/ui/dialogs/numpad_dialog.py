from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLineEdit, QPushButton, QLabel, QSizePolicy
)
from PyQt6.QtCore import Qt


class NumpadDialog(QDialog):
    """Popup numpad for entering a numeric value."""

    def __init__(self, title="Enter value", initial="", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(300)
        self.value = None
        self._build_ui(initial)

    def _build_ui(self, initial: str):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        self.display = QLineEdit(initial)
        self.display.setObjectName("amountInput")
        self.display.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.display.setMinimumHeight(48)
        layout.addWidget(self.display)

        grid = QGridLayout()
        grid.setSpacing(6)

        keys = [
            ("7", 0, 0), ("8", 0, 1), ("9", 0, 2),
            ("4", 1, 0), ("5", 1, 1), ("6", 1, 2),
            ("1", 2, 0), ("2", 2, 1), ("3", 2, 2),
            ("0", 3, 0), (".", 3, 1), ("⌫", 3, 2),
        ]
        for label, r, c in keys:
            btn = QPushButton(label)
            btn.setObjectName("numKey" if label != "⌫" else "numKeyDel")
            btn.setMinimumHeight(48)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            btn.clicked.connect(lambda _, l=label: self._press(l))
            grid.addWidget(btn, r, c)

        for i in range(3):
            grid.setColumnStretch(i, 1)
        for i in range(4):
            grid.setRowStretch(i, 1)

        layout.addLayout(grid)

        btn_row = QHBoxLayout()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(cancel)

        ok = QPushButton("OK")
        ok.setObjectName("okBtn")
        ok.setMinimumHeight(44)
        ok.clicked.connect(self._confirm)
        btn_row.addWidget(ok)

        layout.addLayout(btn_row)

    def _press(self, key: str):
        if key == "⌫":
            self.display.setText(self.display.text()[:-1])
        elif key == "." and "." in self.display.text():
            return  # only one decimal point
        else:
            self.display.insert(key)

    def _confirm(self):
        try:
            self.value = self.display.text()
            self.accept()
        except ValueError:
            self.display.setText("")  # clear bad input
