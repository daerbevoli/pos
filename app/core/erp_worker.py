"""Runs blocking ErpService calls off the Qt UI thread.

ErpService methods are synchronous `requests` calls (several sequential
round trips for some flows) — calling them directly from a slot freezes the
UI for as long as Odoo takes to respond. QThread.finished/failed signals are
queued back onto the thread that owns the receiving QObject (the UI thread),
so slots connected to them run safely there.
"""

import logging

from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)

class InvoiceSendWorker(QThread):
    """Creates + posts the ERP invoice from `invoice_data`, then sends it —
    the full create_post_invoice() + send_invoice() round trip, all off the
    UI thread. `succeeded` only fires once the invoice has actually gone out
    (now, or by an earlier attempt), since the slot locks the sale on it."""

    succeeded = pyqtSignal(int, str, str)  # invoice_id, inv_num, send message
    failed = pyqtSignal(str)

    # Every started worker, so quitting can wait for them (see wait_for_all).
    _started: "set[InvoiceSendWorker]" = set()

    def __init__(self, erp, invoice_data, use_peppol, use_email, parent=None):
        super().__init__(parent)
        self.erp = erp
        self.invoice_data = invoice_data
        self.use_peppol = use_peppol
        self.use_email = use_email
        self.finished.connect(lambda: InvoiceSendWorker._started.discard(self))

    def start(self, *args, **kwargs):
        InvoiceSendWorker._started.add(self)
        super().start(*args, **kwargs)

    @staticmethod
    def wait_for_all():
        """Block until every running send is done. Called on quit: a
        destroyed running QThread aborts the process. Its result slot no
        longer runs then, so a sent invoice isn't locked in the POS yet;
        sending it again picks it up as already sent and locks it."""
        for worker in list(InvoiceSendWorker._started):
            try:
                running = worker.isRunning()
            except RuntimeError:  # the QThread is already gone
                InvoiceSendWorker._started.discard(worker)
                continue
            if running:
                logger.info("Waiting for invoice %s to finish sending", worker.invoice_data.get("inv_num"))
                worker.wait()

    def run(self):
        inv_num = self.invoice_data.get("inv_num")
        logger.info("Sending invoice %s to ERP (peppol=%s, email=%s)",
                    inv_num, self.use_peppol, self.use_email)
        try:
            invoice_id, already_sent = self.erp.create_post_invoice(
                invoice_data=self.invoice_data
            )
            if already_sent:
                sent, message = True, "Invoice was already sent from the ERP"
            else:
                sent, message = self.erp.send_invoice(
                    invoice_id, self.use_peppol, self.use_email
                )
        except Exception as e:
            logger.exception("Invoice %s: ERP create/post/send raised", inv_num)
            self.failed.emit(str(e))
            return
        if not sent:
            logger.error("Invoice %s: ERP did not send it: %s", inv_num, message)
            self.failed.emit(message)
            return
        logger.info("Invoice %s sent (ERP id %s): %s", inv_num, invoice_id, message)
        self.succeeded.emit(invoice_id, self.invoice_data["inv_num"], message)
