"""
Supermarket POS - Entry Point
"""
import logging
import platform
import sys
from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR
from PyQt6.QtWidgets import QApplication
from app.core.database import DB_PATH, get_session, init_db
from app.core.settings_service import SettingsService
from app.ui.main_window import MainWindow
from app.utils.error_handling import setup_logging, install_excepthook

logger = logging.getLogger("pos")


def _log_startup_banner():
    """Which machine, build and hardware config a log came from."""
    logger.info("=" * 60)
    logger.info("POS starting: Python %s, Qt %s / PyQt %s, %s, frozen=%s",
                platform.python_version(), QT_VERSION_STR, PYQT_VERSION_STR,
                platform.platform(), getattr(sys, "frozen", False))
    logger.info("Database: %s", DB_PATH)
    with get_session() as session:
        get = lambda key: SettingsService.get(session, key) or "-"
        logger.info("Receipt printer USB %s:%s, label printer USB %s:%s, ERP %s",
                    get("receipt_printer_vendor_id"), get("receipt_printer_product_id"),
                    get("label_printer_vendor_id"), get("label_printer_product_id"),
                    get("erp_url"))


def main():
    setup_logging()

    # Enable high DPI scaling (important for touch screens)
    app = QApplication(sys.argv)
    app.setApplicationName("POS SKBC")
    app.setOrganizationName("SKBC bv")

    # From here on, unhandled exceptions get logged and shown to the user
    # instead of crashing the app.
    install_excepthook()

    # Load global stylesheet
    with open("resources/styles/main.qss", "r") as f:
        app.setStyleSheet(f.read())

    # Initialize database (creates tables if they don't exist)
    init_db()
    _log_startup_banner()

    # Launch main window
    window = MainWindow()
    # if "--windowed" in sys.argv:
    window.show()            # development: normal window with title bar
    # else:
    #     window.showFullScreen()  # till: no title bar / close buttons, covers the taskbar

    exit_code = app.exec()
    logger.info("POS exiting (code %s)", exit_code)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
