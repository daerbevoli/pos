"""Runs blocking ErpService calls off the Qt UI thread.

ErpService methods are synchronous `requests` calls (several sequential
round trips for some flows) — calling them directly from a slot freezes the
UI for as long as Odoo takes to respond. QThread.finished/failed signals are
queued back onto the thread that owns the receiving QObject (the UI thread),
so slots connected to them run safely there.
"""

from PyQt6.QtCore import QThread, pyqtSignal

class InvoiceSendWorker(QThread):
    """Creates + posts the ERP invoice from `invoice_data`, then sends it —
    the full create_post_invoice() + send_invoice() round trip, all off the
    UI thread."""

    succeeded = pyqtSignal(int, str, str)  # invoice_id, inv_num, send message
    duplicate = pyqtSignal(str)            # inv_num already exists as a posted move
    failed = pyqtSignal(str)

    def __init__(self, erp, invoice_data, use_peppol, use_email, parent=None):
        super().__init__(parent)
        self.erp = erp
        self.invoice_data = invoice_data
        self.use_peppol = use_peppol
        self.use_email = use_email

    def run(self):
        try:
            invoice_id, _email, inv_num, _inv_date = (self.erp.create_post_invoice(
                invoice_data=self.invoice_data
            ))
            if not invoice_id:
                self.duplicate.emit(inv_num)
                return
            sent, message = self.erp.send_invoice(
                invoice_id, self.use_peppol, self.use_email
            )
        except Exception as e:
            self.failed.emit(str(e))
            return
        self.succeeded.emit(invoice_id, inv_num, message)
