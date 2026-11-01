"""
Supermarket POS - Entry Point
"""
import logging
import platform
import sys
from pathlib import Path
from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication
from app.__version__ import __version__
from app.core.database import DB_PATH, get_session, init_db
from app.core.settings_service import SettingsService
from app.ui.main_window import MainWindow
from app.utils.error_handling import setup_logging, install_excepthook

logger = logging.getLogger("pos")

# In the PyInstaller build, bundled files (see superpos.spec's datas) live in
# sys._MEIPASS (the _internal folder); when running from source they sit next
# to main.py.
# Never rely on the working directory: a shortcut may start the .exe elsewhere.
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
LOG_DIR = Path(DB_PATH).parent / "logs"


def _log_startup_banner():
    """Which machine, build and hardware config a log came from."""
    logger.info("=" * 60)
    logger.info("POS %s starting: Python %s, Qt %s / PyQt %s, %s, frozen=%s",
                __version__, platform.python_version(), QT_VERSION_STR, PYQT_VERSION_STR,
                platform.platform(), getattr(sys, "frozen", False))
    logger.info("Database: %s, logs: %s", DB_PATH, LOG_DIR)
    with get_session() as session:
        get = lambda key: SettingsService.get(session, key) or "-"
        logger.info("Receipt printer USB %s:%s, label printer USB %s:%s, ERP %s",
                    get("receipt_printer_vendor_id"), get("receipt_printer_product_id"),
                    get("label_printer_vendor_id"), get("label_printer_product_id"),
                    get("erp_url"))


def main():
    setup_logging(LOG_DIR)

    if "--self-test" in sys.argv:
        from app.utils.self_test import run_self_test
        logger.info("POS %s self-test, frozen=%s", __version__, getattr(sys, "frozen", False))
        sys.exit(run_self_test())

    # Enable high DPI scaling (important for touch screens)
    app = QApplication(sys.argv)
    app.setApplicationName("POS")
    app.setOrganizationName("SKBC bv")
    app.setApplicationVersion(__version__)
    app.setWindowIcon(QIcon(str(BUNDLE_DIR / "resources" / "icons" / "kassa.ico")))

    # From here on, unhandled exceptions get logged and shown to the user
    # instead of crashing the app.
    install_excepthook()

    # Load global stylesheet
    with open(BUNDLE_DIR / "resources" / "styles" / "main.qss", "r", encoding="utf-8") as f:
        app.setStyleSheet(f.read())

    # Initialize database (creates tables if they don't exist)
    init_db()
    _log_startup_banner()

    # Launch main window
    window = MainWindow()
    # if "--windowed" in sys.argv:
    window.showFullScreen()            # development: normal window with title bar
    # else:
    #     window.showFullScreen()  # till: no title bar / close buttons, covers the taskbar

    exit_code = app.exec()
    logger.info("POS exiting (code %s)", exit_code)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
