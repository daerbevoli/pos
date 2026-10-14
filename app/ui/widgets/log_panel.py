"""
Live view of the application log (Settings > Logs tab).
Shows everything sent to Python's `logging` since startup, same lines as logs/pos.log.
"""
import logging

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit, QApplication
from PyQt6.QtGui import QColor, QFontDatabase, QTextCharFormat, QTextCursor

from app.constants import (
    COLOR_LOG_DEBUG, COLOR_LOG_ERROR, COLOR_LOG_WARNING,
    LOG_PANEL_MAX_LINES, SETTINGS_OK_BUTTON_HEIGHT, SPACING_XS,
)
from app.utils.error_handling import qt_log_handler
from app.utils.utils import FunctionButton


def _level_format(color=None) -> QTextCharFormat:
    fmt = QTextCharFormat()
    if color:
        fmt.setForeground(QColor(*color))
    return fmt


class LogPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.view.setMaximumBlockCount(LOG_PANEL_MAX_LINES)
        self.view.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        layout.addWidget(self.view)

        self._default_format = _level_format()
        self._level_formats = {
            logging.DEBUG: _level_format(COLOR_LOG_DEBUG),
            logging.WARNING: _level_format(COLOR_LOG_WARNING),
            logging.ERROR: _level_format(COLOR_LOG_ERROR),
            logging.CRITICAL: _level_format(COLOR_LOG_ERROR),
        }

        btn_row = QHBoxLayout()
        btn_row.setSpacing(SPACING_XS)
        btn_copy = FunctionButton("Copy All")
        btn_copy.clicked.connect(self._copy_all)
        btn_clear = FunctionButton("Clear")
        btn_clear.clicked.connect(self.view.clear)
        for btn in (btn_copy, btn_clear):
            btn.setFixedHeight(SETTINGS_OK_BUTTON_HEIGHT)
            btn_row.addWidget(btn, 1)
        layout.addLayout(btn_row)

        for line, levelno in qt_log_handler.backlog:
            self._write(line, levelno)
        qt_log_handler.emitter.record.connect(self._append)

    def _append(self, line: str, levelno: int):
        # Only follow new lines if the user hasn't scrolled up to read something.
        bar = self.view.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 2
        self._write(line, levelno)
        if at_bottom:
            bar.setValue(bar.maximum())

    def _write(self, line: str, levelno: int):
        # Plain text + char format rather than appendHtml: HTML would collapse
        # the indentation of tracebacks logged via logger.exception().
        cursor = QTextCursor(self.view.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if not self.view.document().isEmpty():
            cursor.insertBlock()
        cursor.insertText(line, self._level_formats.get(levelno, self._default_format))

    def _copy_all(self):
        QApplication.clipboard().setText(self.view.toPlainText())
