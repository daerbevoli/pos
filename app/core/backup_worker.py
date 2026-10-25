"""Runs a BackupService.create_backup() off the Qt UI thread.

Snapshotting is quick, but writing and re-reading the archive on a slow USB
stick or network share isn't — the till shouldn't freeze for it. As with
InvoiceSendWorker, the signals are queued back onto the UI thread.
"""

import logging

from PyQt6.QtCore import QThread, pyqtSignal

from app.core.backup_service import BackupError, BackupService

logger = logging.getLogger(__name__)


class BackupWorker(QThread):
    """`succeeded` carries the BackupResult (which may still list folders
    that failed); `failed` fires only when no archive was written at all."""

    succeeded = pyqtSignal(object)  # BackupResult
    failed = pyqtSignal(str)

    # Every worker that was started, whichever screen started it (daily,
    # manual, after-Z), so quitting can wait for all of them.
    _started: "set[BackupWorker]" = set()

    def __init__(self, kind, destinations, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.destinations = destinations
        self.finished.connect(lambda: BackupWorker._started.discard(self))

    def start(self, *args, **kwargs):
        BackupWorker._started.add(self)
        super().start(*args, **kwargs)

    @staticmethod
    def wait_for_all():
        """Block until every running backup is done. Called on quit: a
        destroyed running QThread aborts the process, and an interrupted
        backup would only leave a .partial file behind anyway."""
        for worker in list(BackupWorker._started):
            try:
                running = worker.isRunning()
            except RuntimeError:  # its parent widget (and so the QThread) is already gone
                BackupWorker._started.discard(worker)
                continue
            if running:
                logger.info("Waiting for the running %s backup to finish", worker.kind)
                worker.wait()

    def run(self):
        try:
            result = BackupService.create_backup(self.kind, self.destinations)
        except BackupError as e:
            self.failed.emit(str(e))
        except Exception as e:  # never let a worker thread die silently
            logger.exception("Backup (%s) raised", self.kind)
            self.failed.emit(str(e))
        else:
            self.succeeded.emit(result)
