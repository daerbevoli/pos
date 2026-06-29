"""
Main Window
Persistent header with store logo, clock, and salesperson.
Persistent V-tab bar — each tab independently tracks its own screen.
"""
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QStackedWidget, QFrame, QButtonGroup, QSizePolicy
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
from app.utils.utils import TicketTab

MAX_VTABS = 5


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SKBC")
        self.setMinimumSize(1024, 768)

        self._active_vtab = 1
        # Per V-tab: which QStackedWidget index (screen) was last active
        self._vtab_screen = {i: 0 for i in range(1, MAX_VTABS + 1)}

        self._build_ui()
        self._start_clock()
        self._check_low_stock()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header: logo + clock / salesperson ───────────────────────────────
        header = QWidget()
        header.setObjectName("header")
        header.setMinimumHeight(50)
        header.setMaximumHeight(70)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(20, 0, 20, 0)
        hl.setSpacing(12)

        self.store_label = QLabel()
        self.store_label.setObjectName("storeName")
        self._set_store_label(self.store_label)
        hl.addWidget(self.store_label)
        hl.addStretch()

        info_col = QVBoxLayout()
        info_col.setSpacing(0)
        self.clock_label = QLabel()
        self.clock_label.setObjectName("clockLabel")
        self.clock_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.salesperson_label = QLabel()
        self.salesperson_label.setObjectName("statusLabel")
        self.salesperson_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        info_col.addWidget(self.clock_label)
        info_col.addWidget(self.salesperson_label)
        hl.addLayout(info_col)

        root.addWidget(header)

        # ── Persistent V-tab bar ─────────────────────────────────────────────
        tab_bar = QWidget()
        tab_bar.setObjectName("vtabBar")
        tab_bar.setMinimumHeight(44)
        tab_bar.setMaximumHeight(56)
        tbl = QHBoxLayout(tab_bar)
        tbl.setContentsMargins(8, 4, 8, 4)
        tbl.setSpacing(4)

        self._vtab_group = QButtonGroup(self)
        self._vtab_group.setExclusive(True)
        self._vtab_buttons: dict[int, TicketTab] = {}
        for i in range(1, MAX_VTABS + 1):
            btn = TicketTab(i)
            btn.clicked.connect(lambda _, idx=i: self._switch_vtab(idx))
            self._vtab_group.addButton(btn)
            self._vtab_buttons[i] = btn
            tbl.addWidget(btn, stretch=1)

        self._vtab_buttons[1].setChecked(True)
        root.addWidget(tab_bar)

        # Thin separator line between tab bar and content
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setObjectName("sidebarDivider")
        root.addWidget(sep)

        # ── Stacked content area ──────────────────────────────────────────────
        self.stack = QStackedWidget()
        self.pos_screen       = POSScreen()          # index 0
        self.inventory_screen = InventoryScreen()     # index 1
        self.client_screen    = ClientScreen()        # index 2
        self.settings_screen  = SettingsScreen()      # index 3
        self.reports_screen   = ReportsScreen()       # index 4

        self.stack.addWidget(self.pos_screen)
        self.stack.addWidget(self.inventory_screen)
        self.stack.addWidget(self.client_screen)
        self.stack.addWidget(self.settings_screen)
        self.stack.addWidget(self.reports_screen)

        self.settings_screen.settings_saved.connect(
            lambda: self._set_store_label(self.store_label)
        )
        self.settings_screen.settings_saved.connect(self._refresh_salesperson)
        self.pos_screen.navigate.connect(self._navigate)
        self.pos_screen.salesperson_changed.connect(self.salesperson_label.setText)
        self.pos_screen.tab_updated.connect(self._on_tab_updated)
        self.client_screen.navigate.connect(self._navigate)
        self.inventory_screen.navigate.connect(self._navigate)
        self.reports_screen.navigate.connect(self._navigate)

        self.client_screen.selected_client.connect(self.pos_screen.set_client)
        self.inventory_screen.selected_product.connect(self.pos_screen.add_product_by_id)

        root.addWidget(self.stack, stretch=1)

        # Initialise to POS screen, tab 1
        self.stack.setCurrentIndex(0)
        self._refresh_salesperson()

    # ── Store label ───────────────────────────────────────────────────────────

    def _set_store_label(self, label: QLabel):
        with get_session() as session:
            path = SettingsService.get(session, "logo_path", "")
            if path:
                pixmap = QPixmap(path)
                label.setPixmap(
                    pixmap.scaled(
                        180, 60,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            else:
                store_name = SettingsService.get(session, "store_name", "")
                label.setText(store_name)

    def _refresh_salesperson(self):
        with get_session() as session:
            name = SettingsService.get(session, "cashier_name", "Cashier")
        self.salesperson_label.setText(name)

    # ── V-tab switching ───────────────────────────────────────────────────────

    def _switch_vtab(self, idx: int):
        if idx == self._active_vtab:
            return
        # Persist current tab's screen
        self._vtab_screen[self._active_vtab] = self.stack.currentIndex()

        self._active_vtab = idx
        screen_idx = self._vtab_screen[idx]
        self.stack.setCurrentIndex(screen_idx)
        # If the restored screen is POS, tell POSScreen which tab is now active
        if screen_idx == 0:
            self.pos_screen.set_active_tab(idx)

        self._vtab_buttons[idx].setChecked(True)

    # ── Screen navigation (called by child screens) ───────────────────────────

    def _navigate(self, screen_idx: int):
        self._vtab_screen[self._active_vtab] = screen_idx
        self.stack.setCurrentIndex(screen_idx)
        if screen_idx == 0:
            self.pos_screen.set_active_tab(self._active_vtab)

    # ── Tab label update (from POSScreen when a cart changes) ─────────────────

    def _on_tab_updated(self, tab_idx: int, amount_str: str):
        btn = self._vtab_buttons.get(tab_idx)
        if btn:
            btn._set_label(f"V {tab_idx}", amount_str)

    # ── Clock ─────────────────────────────────────────────────────────────────

    def _start_clock(self):
        self._update_clock()
        timer = QTimer(self)
        timer.timeout.connect(self._update_clock)
        timer.start(1000)

    def _update_clock(self):
        now = datetime.now().strftime("%A, %d %B %Y  %H:%M")
        self.clock_label.setText(now)

    # ── Low-stock warning ─────────────────────────────────────────────────────

    def _check_low_stock(self):
        with get_session() as session:
            low = ProductService.get_low_stock_products(session)
            if low:
                self.statusBar().showMessage(
                    f"⚠  {len(low)} product(s) are low on stock — check Articles tab"
                )
