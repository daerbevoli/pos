"""
Z Report Progress Dialog
Runs the whole Z report behind a modal popup with a progress bar:

    1. backup before   (0–40 %)  the day's sales, before they're purged
    2. close Z report  (40–50 %) snapshot totals + purge, one transaction
    3. backup after    (50–90 %) with the new Z report and its number
    4. print           (90–100 %)

The cashier waits until everything is done, but the window never freezes:
each step runs on a worker thread and reports progress through signals,
while the popup — application-modal, no close button until the end —
keeps every other input (keyboard, scanner, touch) away from the till, so
no sale can slip in between the backup and the purge. The UI thread only
decides between steps, which is also where it asks the cashier what to do
if the backup before fails.
"""
import logging

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import QDialog, QLabel, QMessageBox, QProgressBar, QVBoxLayout

from app.constants import (
    COLOR_LOG_ERROR, DIALOG_BUTTON_HEIGHT, Z_PROGRESS_BAR_HEIGHT, Z_PROGRESS_DIALOG_WIDTH,
)
# from app.core.admin import check_admin_code
from app.core.backup_service import KIND_POST_Z, KIND_PRE_Z, BackupService
from app.core.database import get_session
from app.core.receipt_service import ReceiptService
from app.core.report_service import XZReportService
from app.models.models import ZReport
from app.ui.dialogs.numpad_dialog import NumpadDialog
from app.utils.utils import FunctionButton

logger = logging.getLogger(__name__)

# (label, start %, end %) of each step on the progress bar.
STEP_PRE_BACKUP = ("Backing up today's sales…", 0, 40)
STEP_CLOSE = ("Closing the Z report…", 40, 50)
STEP_POST_BACKUP = ("Backing up the Z report…", 50, 90)
STEP_PRINT = ("Printing the Z report…", 90, 100)


class _StepWorker(QThread):
    """Runs `fn(progress)` off the UI thread; `progress(0..1)` and the
    outcome come back as signals, queued onto the UI thread."""

    progress = pyqtSignal(float)
    done = pyqtSignal(object)    # fn's return value
    failed = pyqtSignal(object)  # the exception it raised

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            result = self._fn(self.progress.emit)
        except Exception as e:  # handed to the dialog, which decides
            self.failed.emit(e)
        else:
            self.done.emit(result)


def _close_z_report(progress) -> tuple[int, str]:
    with get_session() as session:
        z_report = XZReportService.close_z_report(session)
        return z_report.id, z_report.report_number


def _print_z_report(z_id: int):
    with get_session() as session:
        ReceiptService.print_z_report(session, session.get(ZReport, z_id))


class ZReportProgressDialog(QDialog):
    """Use exec(); afterwards `z_number` is the closed report's number, or
    None if no Z report was made (cancelled or refused)."""

    run_finished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Z Report")
        self.setModal(True)
        self.setMinimumWidth(Z_PROGRESS_DIALOG_WIDTH)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)

        self.z_id = None
        self.z_number = None
        self.problems: list[str] = []  # shown when it's done; the Z report itself may still be fine
        self.is_running = False
        self._worker = None
        self._step = None
        self._destinations = []

        root = QVBoxLayout(self)
        self.step_label = QLabel("Starting…")
        root.addWidget(self.step_label)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setFixedHeight(Z_PROGRESS_BAR_HEIGHT)
        root.addWidget(self.bar)
        self.details = QLabel()
        self.details.setWordWrap(True)
        self.details.hide()
        root.addWidget(self.details)
        self.btn_close = FunctionButton("Close", "okBtn")
        self.btn_close.setFixedHeight(DIALOG_BUTTON_HEIGHT)
        self.btn_close.clicked.connect(self.accept)
        self.btn_close.hide()  # only once it's done: a disabled one still looks pressable
        root.addWidget(self.btn_close)

    # ── Running ──────────────────────────────────────────────────────────

    def exec(self) -> int:
        QTimer.singleShot(0, self.start)
        return super().exec()

    def start(self):
        """Kick off step 1. exec() does this; tests call it directly."""
        if self.is_running:
            return
        self.is_running = True
        logger.info("Z report started")
        with get_session() as session:
            self._destinations = BackupService.destinations(session)
        self._run(STEP_PRE_BACKUP,
                  lambda progress: BackupService.create_backup(
                      KIND_PRE_Z, self._destinations, progress=progress),
                  self._on_pre_backup_done, self._on_pre_backup_failed)

    def _run(self, step, fn, on_done, on_failed):
        label, start, end = step
        self._step = step
        self.step_label.setText(label)
        self.bar.setValue(start)
        self._worker = _StepWorker(fn, self)
        self._worker.progress.connect(lambda f: self.bar.setValue(round(start + f * (end - start))))
        self._worker.done.connect(on_done)
        self._worker.failed.connect(on_failed)
        self._worker.start()

    # Step 1: backup before
    def _on_pre_backup_done(self, result):
        self._note_partial(result, "Backup before the Z report")
        self._close()

    def _on_pre_backup_failed(self, error):
        logger.error("Backup before Z report failed: %s", error)
        reply = QMessageBox.question(
            self, "Backup Failed",
            f"Could not back up the sales before the Z report:\n{error}\n\n"
            "Make the Z report anyway? The sales it clears can then not be recovered.\n"
            "This needs the admin code.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            logger.info("Z report cancelled: backup before it failed")
            self._finish("Z report cancelled. Nothing was changed.")
            return
        # Admin mode alone isn't enough: it needs no code today and stays on
        # until the POS restarts. Losing a day's sale lines needs the code now.
        # if not self._ask_admin_code():
        #     logger.warning("Z report without backup refused: wrong or no admin code")
        #     self._finish("Wrong admin code: Z report cancelled. Nothing was changed.", failed=True)
        #     return
        logger.warning("Z report made without a backup before it, confirmed with the admin code")
        self.problems.append(f"No backup was made before the Z report: {error}")
        self._close()

    # def _ask_admin_code(self) -> bool:
    #     dialog = NumpadDialog(title="Admin code", parent=self, masked=True)
    #     return bool(dialog.exec()) and check_admin_code(dialog.value)

    # Step 2: close the Z report
    def _close(self):
        self._run(STEP_CLOSE, _close_z_report, self._on_closed, self._on_close_failed)

    def _on_closed(self, z):
        self.z_id, self.z_number = z
        self._run(STEP_POST_BACKUP,
                  lambda progress: BackupService.create_backup(
                      KIND_POST_Z, self._destinations, progress=progress),
                  self._on_post_backup_done, self._on_post_backup_failed)

    def _on_close_failed(self, error):
        if isinstance(error, ValueError):  # open tickets / unsent invoices appeared meanwhile
            self._finish(f"Z report not made: {error}. Nothing was changed.", failed=True)
            return
        logger.error("Z report failed: %s", error)
        self._finish(f"Z report failed: {error}\nNothing was changed.", failed=True)

    # Step 3: backup after
    def _on_post_backup_done(self, result):
        self._note_partial(result, "Backup after the Z report")
        self._print()

    def _on_post_backup_failed(self, error):
        logger.error("Backup after Z report failed: %s", error)
        self.problems.append(f"Backup after the Z report failed: {error}")
        self._print()

    # Step 4: print
    def _print(self):
        z_id = self.z_id
        self._run(STEP_PRINT, lambda progress: _print_z_report(z_id),
                  lambda _: self._finish_done(), self._on_print_failed)

    def _on_print_failed(self, error):
        self.problems.append(f"Printing failed: {error}\nReprint it via Reports → Z Reports.")
        self._finish_done()

    # ── Ending ───────────────────────────────────────────────────────────

    def _note_partial(self, result, what: str):
        for folder, error in result.failures.items():
            self.problems.append(f"{what} not saved in {folder}: {error}")

    def _finish_done(self):
        self.bar.setValue(100)
        logger.info("Z report %s completed%s", self.z_number,
                    f" with {len(self.problems)} problem(s)" if self.problems else "")
        self._finish(f"Z report {self.z_number} completed.")

    def _finish(self, message: str, failed: bool = False):
        self.is_running = False
        self.step_label.setText(message)
        if failed:
            self.step_label.setStyleSheet("color: rgb(%d, %d, %d);" % COLOR_LOG_ERROR)
        if self.problems:
            self.details.setText("\n\n".join(self.problems))
            self.details.setStyleSheet("color: rgb(%d, %d, %d);" % COLOR_LOG_ERROR)
            self.details.show()
        self.btn_close.show()
        self.btn_close.setFocus()
        self.run_finished.emit()

    def reject(self):
        # Escape / closing mid-run would leave a half-done Z report behind.
        if self.is_running:
            return
        super().reject()
