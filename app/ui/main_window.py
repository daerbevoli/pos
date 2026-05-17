"""
Main Window
Sidebar button navigation: POS, Articles, Reports, Settings.
"""
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QStatusBar, QStackedWidget, QFrame
)
from PyQt6.QtCore import Qt, QTimer
from datetime import datetime

from app.ui.client_screen import ClientScreen
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
        self._nav_buttons = []
        self._right_buttons = []
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
        header.setFixedHeight(60)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 0, 20, 0)
        store_label = QLabel()
        store_label.setObjectName("storeName")

        pixmap = QPixmap("./resources/icons/Logo.png")

        store_label.setPixmap(
            pixmap.scaled(
                180, 100,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
        )

        header_layout.addWidget(store_label)
        header_layout.addStretch()

        self.clock_label = QLabel()
        self.clock_label.setObjectName("clockLabel")
        header_layout.addWidget(self.clock_label)

        root.addWidget(header)

        # ── Body: sidebar + content ───────────────────────────────────────────
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        # ── Sidebar ───────────────────────────────────────────────────────────
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(160)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 20, 0, 20)
        sidebar_layout.setSpacing(4)
        sidebar_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        nav_items = [
            ("POS",      0),
            ("Articles", 1),
            ("Clients", 2),
            ("Reports",  3),
            ("Settings", 4)]

        for label, index in nav_items:
            btn = QPushButton(f"{label}")
            btn.setObjectName("navBtn")
            btn.setFixedHeight(80)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _, i=index: self._navigate(i))
            sidebar_layout.addWidget(btn)
            self._nav_buttons.append(btn)

        sidebar_layout.addStretch()
        body.addWidget(sidebar)


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
        self.stack.addWidget(self.reports_screen)
        self.stack.addWidget(self.settings_screen)

        body.addWidget(self.stack, stretch=1)
        root.addLayout(body, stretch=1)

        # ── Status bar ────────────────────────────────────────────────────────
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

        # Start on POS screen
        self._navigate(0)

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