"""
Backup Dialog
Lists the backups in every backup folder, takes one on demand, sets the
extra backup folder (USB stick / network share) and restores a backup.
All file and DB work goes through BackupService; a manual backup runs on a
BackupWorker so the dialog stays responsive while it's written.
"""
import logging
import sys

from PyQt6.QtCore import Qt, QProcess
from PyQt6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QAbstractItemView, QFormLayout,
)

from app.constants import BACKUP_DIALOG_MIN_SIZE, DIALOG_BUTTON_HEIGHT
from app.core.backup_service import (
    BACKUP_SETTING_EXTRA_DIR, KIND_MANUAL, BackupError, BackupService,
)
from app.core.backup_worker import BackupWorker
from app.core.database import get_session
from app.core.settings_service import SettingsService
from app.utils.utils import FunctionButton, TapToDismissOverlay

logger = logging.getLogger(__name__)

_KIND_LABELS = {
    "manual": "Manual",
    "daily": "Daily (automatic)",
    "pre-z": "Before Z report",
    "pre-restore": "Before restore",
}


def _format_size(size: int) -> str:
    return f"{size / 1024:.0f} KB" if size < 1024 * 1024 else f"{size / 1024 / 1024:.1f} MB"


def restart_app():
    """Start a fresh POS process, then quit this one — after a restore every
    screen still holds data read from the old database."""
    args = sys.argv[1:] if getattr(sys, "frozen", False) else sys.argv
    QProcess.startDetached(sys.executable, args)
    QApplication.quit()


class BackupDialog(QDialog):

    def __init__(self, parent=None, is_admin: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Backup")
        self.setMinimumSize(*BACKUP_DIALOG_MIN_SIZE)
        self.overlay = TapToDismissOverlay(self)
        self.is_admin = is_admin
        self._worker = None
        self._row_paths: dict[int, str] = {}
        self._build_ui()
        self._reload()

    # ── UI ───────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)

        self.status_label = QLabel()
        self.status_label.setObjectName("backupStatus")
        root.addWidget(self.status_label)

        folders = QGroupBox("Backup folders")
        form = QFormLayout(folders)
        self.local_dir_label = QLabel(str(BackupService.default_backup_dir()))
        self.local_dir_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow("On this PC:", self.local_dir_label)

        self.extra_dir = QLineEdit()
        self.extra_dir.setReadOnly(True)
        self.extra_dir.setPlaceholderText("None — choose a USB stick or network folder")
        self.btn_browse = QPushButton("Choose…")
        self.btn_browse.clicked.connect(self._choose_extra_dir)
        self.btn_clear_dir = QPushButton("Clear")
        self.btn_clear_dir.clicked.connect(self._clear_extra_dir)
        extra_row = QHBoxLayout()
        extra_row.addWidget(self.extra_dir, 1)
        extra_row.addWidget(self.btn_browse)
        extra_row.addWidget(self.btn_clear_dir)
        form.addRow("Extra copy:", extra_row)
        root.addWidget(folders)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Date", "Type", "Size", "Folder"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 1)

        self.btn_restore_file = QPushButton("Restore from file…")
        self.btn_restore = QPushButton("Restore selected")
        self.btn_close = QPushButton("Close")
        self.btn_backup = FunctionButton("Backup now", "okBtn")
        self.btn_restore_file.clicked.connect(self._restore_from_file)
        self.btn_restore.clicked.connect(self._restore_selected)
        self.btn_close.clicked.connect(self.reject)
        self.btn_backup.clicked.connect(self._backup_now)
        buttons = QHBoxLayout()
        for btn in (self.btn_restore_file, self.btn_restore, self.btn_close, self.btn_backup):
            btn.setFixedHeight(DIALOG_BUTTON_HEIGHT)
            buttons.addWidget(btn)
        root.addLayout(buttons)

    def _destinations(self):
        with get_session() as session:
            return BackupService.destinations(session)

    def _reload(self):
        with get_session() as session:
            self.extra_dir.setText(SettingsService.get(session, BACKUP_SETTING_EXTRA_DIR) or "")
        backups = []
        for dest in self._destinations():
            backups.extend(BackupService.list_backups(dest))
        backups.sort(key=lambda b: b.created_at, reverse=True)

        self.table.setRowCount(len(backups))
        self._row_paths = {}
        for row, info in enumerate(backups):
            cells = (
                info.created_at.strftime("%d/%m/%Y %H:%M:%S"),
                _KIND_LABELS.get(info.kind, info.kind),
                _format_size(info.size),
                str(info.path.parent),
            )
            for col, text in enumerate(cells):
                self.table.setItem(row, col, QTableWidgetItem(text))
            self._row_paths[row] = str(info.path)

        if backups:
            latest = backups[0]
            self.status_label.setText(
                f"Last backup: {latest.created_at:%d/%m/%Y %H:%M} "
                f"({_KIND_LABELS.get(latest.kind, latest.kind).lower()})")
        else:
            self.status_label.setText("No backup has been made yet.")

    def _set_busy(self, busy: bool):
        for btn in (self.btn_backup, self.btn_restore, self.btn_restore_file,
                    self.btn_browse, self.btn_clear_dir, self.btn_close):
            btn.setEnabled(not busy)
        if busy:
            self.status_label.setText("Backing up…")

    # ── Backup ───────────────────────────────────────────────────────────

    def _backup_now(self):
        if self._worker is not None and self._worker.isRunning():
            return
        self._set_busy(True)
        self._worker = BackupWorker(KIND_MANUAL, self._destinations(), parent=self)
        self._worker.succeeded.connect(self._on_backup_succeeded)
        self._worker.failed.connect(self._on_backup_failed)
        self._worker.start()

    def _on_backup_succeeded(self, result):
        self._set_busy(False)
        self._reload()
        if result.failures:
            failed = "\n".join(f"{d}: {e}" for d, e in result.failures.items())
            self.overlay.show_message(f"Backup saved, but not everywhere:\n{failed}", kind="error")
        else:
            self.overlay.show_message("Backup saved.")

    def _on_backup_failed(self, message: str):
        self._set_busy(False)
        self._reload()
        logger.error("Manual backup failed: %s", message)
        self.overlay.show_message(f"Backup failed:\n{message}", kind="error")

    def reject(self):
        # Closing mid-backup would destroy the running QThread with the dialog.
        if self._worker is not None and self._worker.isRunning():
            return
        super().reject()

    # ── Extra folder ─────────────────────────────────────────────────────

    def _choose_extra_dir(self):
        if not self.is_admin:
            self.overlay.show_message("Only admin.")
            return
        path = QFileDialog.getExistingDirectory(self, "Choose backup folder", self.extra_dir.text())
        if path:
            self._save_extra_dir(path)

    def _clear_extra_dir(self):
        if not self.is_admin:
            self.overlay.show_message("Only admin.")
            return
        self._save_extra_dir("")

    def _save_extra_dir(self, path: str):
        with get_session() as session:
            SettingsService.set(session, BACKUP_SETTING_EXTRA_DIR, path)
        self._reload()

    # ── Restore ──────────────────────────────────────────────────────────

    def _restore_selected(self):
        row = self.table.currentRow()
        if row == -1:
            self.overlay.show_message("Select a backup first.")
            return
        self._restore(self._row_paths[row])

    def _restore_from_file(self):
        if not self.is_admin:
            self.overlay.show_message("Only admin.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Select backup", self.extra_dir.text(), "POS backups (superpos-*.zip)")
        if path:
            self._restore(path)

    def _restore(self, path: str):
        if not self.is_admin:
            self.overlay.show_message("Only admin.")
            logger.info("Restore refused: not in admin mode")
            return
        try:
            manifest = BackupService.verify_archive(path)
        except BackupError as e:
            logger.error("Restore: %s failed verification: %s", path, e)
            self.overlay.show_message(f"This backup can't be used:\n{e}", kind="error")
            return

        taken = manifest.get("created_at", "?").replace("T", " ")
        text = (f"Restore the backup taken {taken}?\n\n"
                "Everything entered since then — sales, products, clients, invoices, "
                "settings — is replaced by the backup. A safety backup of the current "
                "data is made first.\n\nThe POS restarts afterwards.")
        warnings = BackupService.restore_warnings(manifest)
        if warnings:
            text += "\n\nWARNING:\n" + "\n\n".join(warnings)
        if QMessageBox.question(
                self, "Restore Backup", text,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return

        # Blocking on purpose: nothing else may touch the DB meanwhile.
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            BackupService.restore_backup(path, self._destinations())
        except BackupError as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Restore Failed", str(e))
            return
        QApplication.restoreOverrideCursor()
        QMessageBox.information(self, "Restore Backup",
                                "The backup was restored. The POS will now restart.")
        restart_app()
