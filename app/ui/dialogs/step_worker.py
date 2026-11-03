"""
StepWorker: runs one blocking step off the UI thread for a progress dialog
(ZReportProgressDialog, ImportProgressDialog).
"""
from PyQt6.QtCore import QThread, pyqtSignal


class StepWorker(QThread):
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
