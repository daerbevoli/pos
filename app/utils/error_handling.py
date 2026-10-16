"""
Global error handling: logs unhandled exceptions to a rotating log file
and shows a dialog instead of letting the app crash silently.
"""
import sys
import logging
import logging.handlers
from collections import deque
from pathlib import Path

from PyQt6.QtCore import QObject, QtMsgType, pyqtSignal, qInstallMessageHandler
from PyQt6.QtWidgets import QMessageBox

from app.constants import LOG_PANEL_MAX_LINES

logger = logging.getLogger("pos")

# pos.log gets everything (DEBUG+) with thread + line number for tracing;
# the Settings > Logs panel gets INFO+ in the shorter format.
FILE_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(threadName)s %(name)s:%(lineno)d: %(message)s"
PANEL_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

# Third-party loggers that flood DEBUG output; only their warnings are kept.
_NOISY_LOGGERS = ("urllib3", "requests", "sqlalchemy", "PIL", "usb", "escpos")

_QT_LOG_LEVELS = {
    QtMsgType.QtDebugMsg: logging.DEBUG,
    QtMsgType.QtInfoMsg: logging.INFO,
    QtMsgType.QtWarningMsg: logging.WARNING,
    QtMsgType.QtCriticalMsg: logging.ERROR,
    QtMsgType.QtFatalMsg: logging.CRITICAL,
}


class _PauseFilter(logging.Filter):
    """Drops DEBUG/INFO records while logging is paused — see pause_logging().
    Warnings and errors always get through."""

    paused = False

    def filter(self, record):
        return not self.paused or record.levelno >= logging.WARNING


# Shared by the file and panel handlers, so one switch silences both.
_pause_filter = _PauseFilter()


def pause_logging(paused: bool):
    """Silences DEBUG and INFO logging — pos.log and the Logs panel alike,
    from every thread warnings and errors are still logged so failures
    stay diagnosable."""
    if paused == _pause_filter.paused:
        return
    if paused:
        _pause_filter.paused = True
    else:
        _pause_filter.paused = False


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
        self.addFilter(_pause_filter)

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
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter(FILE_LOG_FORMAT))
    handler.addFilter(_pause_filter)
    qt_log_handler.setLevel(logging.INFO)
    qt_log_handler.setFormatter(logging.Formatter(PANEL_LOG_FORMAT))

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)
    root.addHandler(qt_log_handler)

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    # Qt's own warnings (layout/stylesheet/signal problems) normally only go
    # to stderr, which the windowed .exe doesn't have — route them in here.
    qt_logger = logging.getLogger("qt")

    def _qt_message_handler(mode, context, message):
        qt_logger.log(_QT_LOG_LEVELS.get(mode, logging.WARNING), message)

    qInstallMessageHandler(_qt_message_handler)


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
