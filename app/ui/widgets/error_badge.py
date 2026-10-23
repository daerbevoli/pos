"""
Header badge that lights up when an ERROR or CRITICAL line is logged.
Never blocks the cashier: it just sits in the header with a running count
until someone taps it (MainWindow then opens Settings > Logs) to acknowledge.
With no errors it stays in place as a blank, untappable box of the same fixed
width, so the V-tabs beside it don't resize every time it fills or empties.
"""
import logging

from PyQt6.QtWidgets import QPushButton

from app.constants import ERROR_BADGE_WIDTH
from app.utils.error_handling import qt_log_handler


class ErrorBadge(QPushButton):
    def __init__(self, handler=qt_log_handler, parent=None):
        super().__init__(parent)
        self.setObjectName("errorBadge")
        self.setFixedWidth(ERROR_BADGE_WIDTH)
        self.count = 0
        self._set_active(False)
        # Errors logged at startup, before the window existed, count too.
        for line, levelno in handler.backlog:
            self._on_record(line, levelno)
        # Queued onto the UI thread for records logged from worker threads.
        handler.emitter.record.connect(self._on_record)

    @property
    def active(self) -> bool:
        """True while there are unacknowledged errors (red, tappable)."""
        return self.count > 0

    def _set_active(self, active: bool):
        self.setEnabled(active)
        self.setProperty("active", active)
        self.style().unpolish(self)
        self.style().polish(self)

    def _on_record(self, line: str, levelno: int):
        if levelno < logging.ERROR:
            return
        self.count += 1
        # Capped so the text always fits the fixed width.
        shown = "99+" if self.count > 99 else self.count
        self.setText(f"⚠ {shown} error{'s' if self.count > 1 else ''}")
        self.setToolTip(line)
        self._set_active(True)

    def acknowledge(self):
        self.count = 0
        self.setText("")
        self.setToolTip("")
        self._set_active(False)
