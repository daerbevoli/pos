from pathlib import Path

from PyQt6.QtWidgets import QLineEdit, QPushButton, QHBoxLayout, QFileDialog, QDialog, QLabel, QVBoxLayout

from app.constants import BUTTON_HEIGHT
from app.utils.utils import FunctionButton


class FileDialog(QDialog):


    def __init__(self, parent=None):
        super().__init__(parent)
        self.path = None
        self.setFixedSize(400, 200)
        self.line_edit = QLineEdit()
        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.clicked.connect(self.browse)
        self.ok_btn = FunctionButton("OK", "okBtn")
        self.ok_btn.setFixedHeight(BUTTON_HEIGHT)
        self.ok_btn.clicked.connect(self.on_ok)

        label = QLabel("Select File to import: ")

        layoutV = QVBoxLayout(self)
        layoutH = QHBoxLayout()
        layoutV.addWidget(label)
        layoutV.addLayout(layoutH)
        layoutH.addWidget(self.line_edit)
        layoutH.addWidget(self.browse_btn)
        layoutV.addWidget(self.ok_btn)

    def browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select File", "", "CSV/Text Files (*.csv *.txt)"
        )
        if path:
            self.line_edit.setText(path)

    def on_ok(self):
        path = self.line_edit.text()
        if not Path(path).is_file():
            # show a warning instead of accepting
            return
        self.path = path
        self.accept()
