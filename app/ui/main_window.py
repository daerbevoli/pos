"""
Main Window
Persistent V-tab bar — each tab independently tracks its own screen —
with the error badge and a clock / salesperson box at its right end.
"""
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QStackedWidget, QFrame, QButtonGroup
)
from PyQt6.QtCore import Qt, QTimer
from datetime import datetime
import logging

from app.constants.sizes import MAIN_WINDOW_SIZE
from app.core.backup_service import KIND_DAILY, BackupService
from app.core.backup_worker import BackupWorker
from app.core.erp_worker import InvoiceSendWorker
from app.core.settings_service import SettingsService
from app.ui.client_screen import ClientScreen
from app.ui.customer_display import CustomerDisplay
from app.ui.pos_screen import POSScreen, TABS
from app.ui.inventory_screen import InventoryScreen
from app.ui.reports_screen import ReportsScreen
from app.ui.settings_screen import SettingsScreen
from app.core.database import get_session
from app.utils.error_handling import pause_logging
from app.utils.utils import TicketTab
from app.ui.widgets.error_badge import ErrorBadge
from app.constants import (
    SPACING_XS,
    TAB_BAR_MAX_HEIGHT,
    TAB_BAR_MIN_HEIGHT,
)

MAX_VTABS = TABS  # one source of truth: POSScreen keeps a state slot per V-tab

# Checked every minute whether the daily (noon) backup is due — see
# BackupService.daily_backup_due(). Polling rather than one timer aimed at
# noon keeps it right across sleep/hibernate and clock changes, and catches
# up when the POS is started after noon. The check only lists one folder.
BACKUP_CHECK_INTERVAL_MS = 60_000

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SKBC")
        self.setFixedSize(*MAIN_WINDOW_SIZE)

        self._active_vtab = 1
        # Per V-tab: which QStackedWidget index (screen) was last active
        self._vtab_screen = {i: 0 for i in range(1, MAX_VTABS + 1)}
        self._salesperson_name = ""  # "Cashier name" / "Admin", shown top right
        self._rf_cn_mode = False     # active POS ticket is in refund / credit-note mode

        self._backup_worker = None

        self._build_ui()
        self._start_clock()
        self._start_backup_schedule()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Persistent V-tab bar (+ error badge, clock / salesperson box) ────
        tab_bar = QWidget()
        tab_bar.setObjectName("vtabBar")
        tab_bar.setMinimumHeight(TAB_BAR_MIN_HEIGHT)
        tab_bar.setMaximumHeight(TAB_BAR_MAX_HEIGHT)
        tbl = QHBoxLayout(tab_bar)
        tbl.setContentsMargins(8, 4, 8, 4)
        tbl.setSpacing(SPACING_XS)

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

        self.error_badge = ErrorBadge()
        self.error_badge.clicked.connect(self._open_logs)
        tbl.addWidget(self.error_badge)

        clock_frame = QFrame()
        clock_frame.setObjectName("clockFrame")
        info_col = QVBoxLayout(clock_frame)
        info_col.setContentsMargins(0, 0, 0, 0)
        info_col.setSpacing(0)
        self.clock_label = QLabel()
        self.clock_label.setObjectName("clockLabel")
        self.clock_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.salesperson_label = QLabel()
        self.salesperson_label.setObjectName("cashierLabel")
        self.salesperson_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_col.addWidget(self.clock_label)
        info_col.addWidget(self.salesperson_label)
        tbl.addWidget(clock_frame)

        root.addWidget(tab_bar)

        # Thin separator line between tab bar and content
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setObjectName("sidebarDivider")
        root.addWidget(sep)

        # ── Stacked content area ──────────────────────────────────────────────
        self.stack = QStackedWidget()
        self.pos_screen       = POSScreen()             # index 0
        self.inventory_screen = InventoryScreen()       # index 1
        self.client_screen    = ClientScreen()          # index 2
        self.settings_screen  = SettingsScreen()        # index 3
        self.reports_screen   = ReportsScreen()         # index 4

        self.stack.addWidget(self.pos_screen)
        self.stack.addWidget(self.inventory_screen)
        self.stack.addWidget(self.client_screen)
        self.stack.addWidget(self.settings_screen)
        self.stack.addWidget(self.reports_screen)

        self.settings_screen.settings_saved.connect(self._refresh_salesperson)
        self.settings_screen.settings_saved.connect(self.pos_screen.reload_shortcuts)
        self.pos_screen.navigate.connect(self._navigate)
        self.settings_screen.salesperson_changed.connect(self._set_salesperson)
        self.settings_screen.admin_changed.connect(self.pos_screen.set_admin)
        self.settings_screen.rf_cn_requested.connect(self._toggle_rf_cn)
        self.pos_screen.rf_cn_mode_changed.connect(self._set_rf_cn_mode)
        self.pos_screen.tab_updated.connect(self._on_tab_updated)
        self.pos_screen.emit_all_tab_amounts()  # show carts recovered from a crash/close
        self.pos_screen.emit_rf_cn_mode()
        self.client_screen.navigate.connect(self._navigate)
        self.inventory_screen.navigate.connect(self._navigate)
        self.reports_screen.navigate.connect(self._navigate)
        self.settings_screen.navigate.connect(self._navigate)

        self.client_screen.selected_client.connect(self.pos_screen.set_client)
        self.inventory_screen.selected_product.connect(self.pos_screen.add_product_by_id)
        self.reports_screen.sale_selected.connect(self.pos_screen.show_sale)

        # ── Customer display: mirrors the active POS ticket in its own window ──
        self.customer_display = CustomerDisplay(self)
        self.pos_screen.display_changed.connect(self.customer_display.update_ticket)
        self.pos_screen.emit_display()
        self.settings_screen.customer_display_requested.connect(
            lambda: self.customer_display.toggle(self)
        )

        root.addWidget(self.stack, stretch=1)

        # Initialize to POS screen, tab 1
        self.stack.setCurrentIndex(0)
        self._refresh_salesperson()

    def showEvent(self, event):
        """Open the customer display on a second monitor, if one is connected —
        only now is it known which screen the main window landed on."""
        super().showEvent(event)
        if not self.customer_display.isVisible():
            screen = CustomerDisplay.secondary_screen(self)
            if screen is not None:
                self.customer_display.show_on(screen)

    # ── Salesperson ───────────────────────────────────────────────────────────

    def _refresh_salesperson(self):
        if self.settings_screen.is_admin:
            return  # saving settings in admin mode mustn't show the cashier's name
        with get_session() as session:
            name = SettingsService.get(session, "cashier_name", "Cashier")
        self._set_salesperson(name)

    def _set_salesperson(self, name: str):
        self._salesperson_name = name
        self._render_salesperson()

    def _set_rf_cn_mode(self, active: bool):
        self._rf_cn_mode = active
        pause_logging(active)
        self._render_salesperson()

    def _render_salesperson(self):
        suffix = " (RF / CN)" if self._rf_cn_mode else ""
        self.salesperson_label.setText(f"{self._salesperson_name}{suffix}")

    # ── V-tab switching ───────────────────────────────────────────────────────

    def _switch_vtab(self, idx: int):
        if idx == self._active_vtab:
            return
        # Persist current tab's screen
        self._vtab_screen[self._active_vtab] = self.stack.currentIndex()

        self._active_vtab = idx
        self.stack.setCurrentIndex(self._vtab_screen[idx])
        # Always, not only when the restored screen is POS: the Clients,
        # Inventory and Reports screens act on the POS ticket (set_client,
        # add_product_by_id, show_sale) and must hit this tab's, not the last one's.
        self.pos_screen.set_active_tab(idx)

        self._vtab_buttons[idx].setChecked(True)

    # ── Screen navigation (called by child screens) ───────────────────────────

    def _navigate(self, screen_idx: int):
        self._vtab_screen[self._active_vtab] = screen_idx
        self.stack.setCurrentIndex(screen_idx)
        if screen_idx == 0:
            self.pos_screen.set_active_tab(self._active_vtab)

    def _open_logs(self):
        """Error badge tapped: show the log and count the errors as seen."""
        self._navigate(3)
        self.settings_screen.show_logs()
        self.error_badge.acknowledge()

    def _toggle_rf_cn(self):
        """RF / CN is pressed on the Settings screen but acts on a POS ticket,
        so go back to POS first — overlays then show where the cashier is
        looking. The mode can't flip under an open ticket (see
        POSScreen.set_rf_cn()), so if the active V-tab has one, leave it
        untouched and switch the mode on the first free V-tab instead."""
        self._navigate(0)
        entering = not self.pos_screen.cart.is_refund
        if self.pos_screen.tab_has_open_ticket(self._active_vtab):
            free = next(
                (i for i in range(1, MAX_VTABS + 1) if not self.pos_screen.tab_has_open_ticket(i)),
                None,
            )
            if free is None:
                self.pos_screen.overlay.show_message("All V-tabs have an open ticket", kind="error")
                return
            self._switch_vtab(free)
        self.pos_screen.set_rf_cn(entering)

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
        now = datetime.now().strftime("%a %d-%m-%Y  %H:%M")
        self.clock_label.setText(now)

    # ── Automatic backup ──────────────────────────────────────────────────────

    def _start_backup_schedule(self):
        self._backup_timer = QTimer(self)
        self._backup_timer.timeout.connect(self._maybe_daily_backup)
        self._backup_timer.start(BACKUP_CHECK_INTERVAL_MS)
        QApplication.instance().aboutToQuit.connect(BackupWorker.wait_for_all)
        QApplication.instance().aboutToQuit.connect(InvoiceSendWorker.wait_for_all)

    def _maybe_daily_backup(self):
        """Take today's noon backup in the background, if it's due (see
        BackupService.daily_backup_due()). A failure shows up in the error
        badge via the log, and it's tried again on the next check."""
        if self._backup_worker is not None and self._backup_worker.isRunning():
            return
        with get_session() as session:
            destinations = BackupService.destinations(session)
        if not BackupService.daily_backup_due(destinations[0]):
            return
        self._backup_worker = BackupWorker(KIND_DAILY, destinations, parent=self)
        self._backup_worker.failed.connect(
            lambda message: logger.error("Daily backup failed: %s", message))
        self._backup_worker.start()

