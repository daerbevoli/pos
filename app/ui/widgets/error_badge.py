"""
Header badge that lights up when an ERROR or CRITICAL line is logged.
Never blocks the cashier: it just sits in the header with a running count
until someone taps it (MainWindow then opens Settings > Logs) to acknowledge.
"""
import logging

from PyQt6.QtWidgets import QPushButton

from app.utils.error_handling import qt_log_handler


class ErrorBadge(QPushButton):
    def __init__(self, handler=qt_log_handler, parent=None):
        super().__init__(parent)
        self.setObjectName("errorBadge")
        self.count = 0
        self.hide()
        # Errors logged at startup, before the window existed, count too.
        for line, levelno in handler.backlog:
            self._on_record(line, levelno)
        # Queued onto the UI thread for records logged from worker threads.
        handler.emitter.record.connect(self._on_record)

    def _on_record(self, line: str, levelno: int):
        if levelno < logging.ERROR:
            return
        self.count += 1
        self.setText(f"⚠ {self.count} error{'s' if self.count > 1 else ''}")
        self.setToolTip(line)
        self.show()

    def acknowledge(self):
        self.count = 0
        self.hide()
