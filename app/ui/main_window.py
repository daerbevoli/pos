"""
Main Window
Sidebar button navigation: POS, Articles, Reports, Settings.
"""
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QStatusBar, QStackedWidget, QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer
from datetime import datetime

from app.core.settings_service import SettingsService
from app.ui.client_screen import ClientScreen
from app.ui.pos_screen import POSScreen
from app.ui.inventory_screen import InventoryScreen
from app.ui.reports_screen import ReportsScreen
from app.ui.settings_screen import SettingsScreen
from app.core.database import get_session
from app.core.product_service import ProductService

from app.utils.utils import FunctionButton


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SKBC")
        self.setMinimumSize(1024, 768)
        self._nav_buttons = []
        self._build_ui()
        self._start_clock()
        self._check_low_stock()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────────────
        header = QWidget()
        header.setObjectName("header")
        header.setMinimumHeight(50)
        header.setMaximumHeight(70)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 0, 20, 0)

        self.store_label = QLabel()
        self.store_label.setObjectName("storeName")

        self._set_store_label(self.store_label)

        header_layout.addWidget(self.store_label)
        header_layout.addStretch()

        self.clock_label = QLabel()
        self.clock_label.setObjectName("clockLabel")
        header_layout.addWidget(self.clock_label)

        root.addWidget(header)

        # ── Body: sidebar + content ───────────────────────────────────────────
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)


        # ── Vertical divider ──────────────────────────────────────────────────
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.VLine)
        divider.setObjectName("sidebarDivider")
        body.addWidget(divider)

        # ── Stacked content area ──────────────────────────────────────────────
        self.stack = QStackedWidget()
        self.pos_screen       = POSScreen()
        self.inventory_screen = InventoryScreen()
        self.client_screen = ClientScreen()
        self.reports_screen   = ReportsScreen()
        self.settings_screen  = SettingsScreen()

        self.stack.addWidget(self.pos_screen)
        self.stack.addWidget(self.inventory_screen)
        self.stack.addWidget(self.client_screen)
        self.stack.addWidget(self.settings_screen)
        self.stack.addWidget(self.reports_screen)
        self.settings_screen.settings_saved.connect(
            lambda: self._set_store_label(self.store_label)
        )

        self.pos_screen.navigate.connect(self._navigate)
        self.client_screen.navigate.connect(self._navigate)

        body.addWidget(self.stack, stretch=1)
        root.addLayout(body, stretch=1)

        # Start on POS screen
        self._navigate(0)

    def _set_store_label(self, label):
        with get_session() as session:
            path = SettingsService.get(session, "logo_path", "")

            if path:
                pixmap = QPixmap(path)
                label.setPixmap(
                    pixmap.scaled(
                        180, 100,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )
                )
            else:
                store_name = SettingsService.get(session, "store_name", "")
                label.setText(store_name)

    def _navigate(self, index: int):
        self.stack.setCurrentIndex(index)
        for i, btn in enumerate(self._nav_buttons):
            btn.setChecked(i == index)

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
                    f"⚠️  {len(low)} product(s) are low on stock — check Articles tab"
                )