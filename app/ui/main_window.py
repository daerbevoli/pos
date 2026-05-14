"""
Main Window
The root window with tab navigation: POS, Inventory, Reports, Settings.
"""
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QPushButton, QStatusBar
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from datetime import datetime

from app.ui.pos_screen import POSScreen
from app.ui.inventory_screen import InventoryScreen
from app.ui.reports_screen import ReportsScreen
from app.ui.settings_screen import SettingsScreen
from app.core.database import get_session
from app.core.product_service import ProductService


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SKBC")
        self.setMinimumSize(1024, 768)

        self._build_ui()
        self._start_clock()
        self._check_low_stock()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Header bar ────────────────────────────────────────────────────────
        header = QWidget()
        header.setObjectName("header")
        header.setFixedHeight(60)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 0, 20, 0)

        store_label = QLabel("SKBC")
        store_label.setObjectName("skbc")
        header_layout.addWidget(store_label)
        header_layout.addStretch()

        self.clock_label = QLabel()
        self.clock_label.setObjectName("clockLabel")
        header_layout.addWidget(self.clock_label)

        layout.addWidget(header)

        # ── Tab navigation ────────────────────────────────────────────────────
        self.tabs = QTabWidget()
        self.tabs.setObjectName("mainTabs")
        self.tabs.setTabPosition(QTabWidget.TabPosition.West)

        self.pos_screen = POSScreen()
        self.inventory_screen = InventoryScreen()
        self.reports_screen = ReportsScreen()
        self.settings_screen = SettingsScreen()

        self.tabs.addTab(self.pos_screen, "🛒  POS")
        self.tabs.addTab(self.inventory_screen, "📦  Articles")
        self.tabs.addTab(self.reports_screen, "📊  Reports")
        self.tabs.addTab(self.settings_screen, "⚙️  Settings")

        layout.addWidget(self.tabs)

        # ── Status bar ────────────────────────────────────────────────────────
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

    def _start_clock(self):
        self._update_clock()
        timer = QTimer(self)
        timer.timeout.connect(self._update_clock)
        timer.start(1000)

    def _update_clock(self):
        now = datetime.now().strftime("%A, %d %B %Y  %H:%M")
        self.clock_label.setText(now)

    def _check_low_stock(self):
        with get_session() as session:
            low = ProductService.get_low_stock_products(session)
            if low:
                self.status_bar.showMessage(
                    f"⚠️  {len(low)} product(s) are low on stock — check Inventory tab"
                )
