"""
Supermarket POS - Entry Point
"""
import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from app.core.database import init_db
from app.ui.main_window import MainWindow


def main():
    # Enable high DPI scaling (important for touch screens)
    app = QApplication(sys.argv)
    app.setApplicationName("POS SKBC")
    app.setOrganizationName("SKBC bv")

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
