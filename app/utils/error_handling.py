"""
Global error handling: logs unhandled exceptions to a rotating log file
and shows a dialog instead of letting the app crash silently.
"""
import sys
import logging
import logging.handlers
from collections import deque
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QMessageBox

from app.constants import LOG_PANEL_MAX_LINES

logger = logging.getLogger("pos")

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


class _LogEmitter(QObject):
    record = pyqtSignal(str, int)  # formatted line, levelno


class QtLogHandler(logging.Handler):
    """Feeds log lines to the Settings > Logs panel.

    Keeps a bounded backlog so the panel can show what was logged before it
    was built, and emits each new line as a signal: records logged from worker
    threads (e.g. InvoiceSendWorker) are then queued onto the UI thread.
    """

    def __init__(self):
        super().__init__()
        self.emitter = _LogEmitter()
        self.backlog = deque(maxlen=LOG_PANEL_MAX_LINES)

    def emit(self, record):
        try:
            line = self.format(record)
        except Exception:
            self.handleError(record)
            return
        self.backlog.append((line, record.levelno))
        self.emitter.record.emit(line, record.levelno)


# Installed on the root logger by setup_logging(); the log panel connects to it.
qt_log_handler = QtLogHandler()


def setup_logging():
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    handler = logging.handlers.RotatingFileHandler(
        log_dir / "pos.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    qt_log_handler.setFormatter(logging.Formatter(LOG_FORMAT))

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    root.addHandler(qt_log_handler)


def install_excepthook():
    def handle_exception(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return

        logger.critical("Unhandled exception", exc_info=(exc_type, exc_value, exc_tb))

        QMessageBox.critical(
            None,
            "Unexpected Error",
            "Something went wrong.\n"
            "The error has been logged - please contact support if this keeps happening.\n\n"
            f"{exc_type.__name__}: {exc_value}",
        )

    sys.excepthook = handle_exception
