"""
Global error handling: logs unhandled exceptions to a rotating log file
and shows a friendly dialog instead of letting the app crash silently.
"""
import sys
import logging
import logging.handlers
from pathlib import Path

from PyQt6.QtWidgets import QMessageBox

logger = logging.getLogger("pos")


def setup_logging():
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    handler = logging.handlers.RotatingFileHandler(
        log_dir / "pos.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


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
