from pathlib import Path

from PyQt6.QtWidgets import QWidget, QLineEdit, QPushButton, QHBoxLayout, QFileDialog, QDialog

from app.constants import DIALOG_WIDTH_SM


class FileDialog(QDialog):


    def __init__(self, parent=None):
        super().__init__(parent)
        self.path = None
        self.setFixedSize(400, 200)
        self.line_edit = QLineEdit()
        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.clicked.connect(self.browse)
        self.ok_btn = QPushButton("OK")
        self.ok_btn.clicked.connect(self.on_ok)

        layout = QHBoxLayout(self)
        layout.addWidget(self.line_edit)
        layout.addWidget(self.browse_btn)
        layout.addWidget(self.ok_btn)

    def browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select File")
        if path:
            self.line_edit.setText(path)

    def on_ok(self):
        path = self.line_edit.text()
        if not Path(path).is_file():
            # show a warning instead of accepting
            return
        self.path = path
        self.accept()
