"""
Supermarket POS - Entry Point
"""
import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from app.core.database import init_db
from app.ui.main_window import MainWindow
from app.utils.error_handling import setup_logging, install_excepthook


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

    # Launch main window
    window = MainWindow()
    window.showMaximized()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
