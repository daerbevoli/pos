"""
Import Progress Dialog
Runs a CSV import (clients or articles) behind a modal popup with a
progress bar, like the Z report: the rows are added on a worker thread so
the window never freezes on a large file, while the popup (application-
modal, no close button until the end) keeps the cashier from changing the
same list mid-import. It ends with the outcome and a Close button.
"""
import logging
from collections.abc import Callable

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QDialog, QLabel, QProgressBar, QVBoxLayout

from app.constants import (
    COLOR_LOG_ERROR,
    DIALOG_BUTTON_HEIGHT,
    PROGRESS_BAR_HEIGHT,
    PROGRESS_DIALOG_WIDTH,
)
from app.core.database import get_session
from app.ui.dialogs.step_worker import StepWorker
from app.utils.utils import FunctionButton

logger = logging.getLogger(__name__)

ImportFn = Callable[..., tuple[int, int]]  # (session, rows, progress=...) -> (added, skipped)


class ImportProgressDialog(QDialog):
    """Use exec(); afterward `added`/`skipped` are the outcome, or None if
    the import failed (rows imported before the error are still saved:
    import_rows() saves each row as it goes). Delete it (deleteLater())
    once read: it holds the whole file's rows."""

    run_finished = pyqtSignal()

    def __init__(self, what: str, import_fn: ImportFn, rows: list[dict], parent=None):
        """what: "clients"/"articles", for the texts. import_fn: e.g.
        ClientService.import_rows; it runs on the worker thread in a session
        of its own."""
        super().__init__(parent)
        self.setWindowTitle(f"Import {what}")
        self.setModal(True)
        self.setMinimumWidth(PROGRESS_DIALOG_WIDTH)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)

        self._what = what
        self._import_fn = import_fn
        self._rows = rows
        self.added: int | None = None
        self.skipped: int | None = None
        self.is_running = False
        self._worker = None

        root = QVBoxLayout(self)
        self.step_label = QLabel(f"Importing {len(rows)} {what}…")
        root.addWidget(self.step_label)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setFixedHeight(PROGRESS_BAR_HEIGHT)
        root.addWidget(self.bar)
        self.btn_close = FunctionButton("Close", "okBtn")
        self.btn_close.setFixedHeight(DIALOG_BUTTON_HEIGHT)
        self.btn_close.clicked.connect(self.accept)
        self.btn_close.hide()  # only once it's done: a disabled one still looks pressable
        root.addWidget(self.btn_close)

    def exec(self) -> int:
        QTimer.singleShot(0, self.start)
        return super().exec()

    def start(self):
        """Start the import. exec() does this; tests call it directly."""
        if self.is_running:
            return
        self.is_running = True
        self._worker = StepWorker(self._run_import, self)
        self._worker.progress.connect(lambda f: self.bar.setValue(round(f * 100)))
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _run_import(self, progress) -> tuple[int, int]:
        # Worker thread: a session of its own, never the UI thread's.
        with get_session() as session:
            return self._import_fn(session, self._rows, progress=progress)

    def _on_done(self, result: tuple[int, int]):
        self.added, self.skipped = result
        self.bar.setValue(100)
        self._finish(f"Import complete: {self.added} added, {self.skipped} skipped.")

    def _on_failed(self, error: Exception):
        # The exception was caught on the worker thread: pass it on for its traceback.
        logger.error("Import of %s failed: %s", self._what, error, exc_info=error)
        self._finish(f"Import failed: {error}\n{self._what.capitalize()} imported before the error "
                     "are kept; importing the file again skips them.", failed=True)

    def _finish(self, message: str, failed: bool = False):
        self.is_running = False
        self.step_label.setText(message)
        if failed:
            self.step_label.setStyleSheet("color: rgb(%d, %d, %d);" % COLOR_LOG_ERROR)
        self.btn_close.show()
        self.btn_close.setFocus()
        self.run_finished.emit()

    def reject(self):
        # Escape mid-import would leave the worker writing behind a closed popup.
        if self.is_running:
            return
        super().reject()
