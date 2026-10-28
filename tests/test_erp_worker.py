"""
Tests for app.core.erp_worker.InvoiceSendWorker.

run() is called directly (not start()) so the signals fire synchronously on
the test thread; ErpService is replaced by a fake, so no HTTP is made.
"""
import pytest

from app.core.erp_worker import InvoiceSendWorker

INVOICE_DATA = {"inv_num": "I-0001"}


class FakeErp:
    def __init__(self, already_sent=False, send_result=(True, "Invoice sent via email"), error=None):
        self.already_sent = already_sent
        self.send_result = send_result
        self.error = error
        self.send_calls = 0

    def create_post_invoice(self, invoice_data):
        if self.error:
            raise self.error
        return 42, self.already_sent

    def send_invoice(self, invoice_id, use_peppol, use_email):
        self.send_calls += 1
        return self.send_result


@pytest.fixture
def run_worker(qtbot):
    def _run(erp):
        worker = InvoiceSendWorker(erp, INVOICE_DATA, False, True)
        succeeded, failed = [], []
        worker.succeeded.connect(lambda *args: succeeded.append(args))
        worker.failed.connect(failed.append)
        worker.run()
        return succeeded, failed
    return _run


def test_sent_invoice_emits_succeeded(run_worker):
    succeeded, failed = run_worker(FakeErp())
    assert succeeded == [(42, "I-0001", "Invoice sent via email")]
    assert failed == []


def test_nothing_sent_emits_failed_not_succeeded(run_worker):
    """send_invoice() returning False (e.g. no email on the partner) must not
    be reported as success — the POS would lock a sale that never went out."""
    succeeded, failed = run_worker(FakeErp(send_result=(False, "Partner has no email address")))
    assert succeeded == []
    assert failed == ["Partner has no email address"]


def test_invoice_already_sent_in_erp_succeeds_without_resending(run_worker):
    erp = FakeErp(already_sent=True)
    succeeded, failed = run_worker(erp)
    assert erp.send_calls == 0
    assert len(succeeded) == 1 and failed == []


def test_existing_unsent_invoice_is_sent(run_worker):
    """A retry after an earlier attempt created the invoice but failed to
    send it goes on to send it, rather than stopping at 'already exists'."""
    erp = FakeErp(already_sent=False)
    succeeded, failed = run_worker(erp)
    assert erp.send_calls == 1
    assert len(succeeded) == 1


def test_exception_emits_failed(run_worker):
    succeeded, failed = run_worker(FakeErp(error=Exception("HTTP 500")))
    assert succeeded == []
    assert failed == ["HTTP 500"]


def test_wait_for_all_waits_for_a_running_send(qtbot):
    """Quitting mid-send must wait: a destroyed running QThread aborts the app."""
    import threading
    release = threading.Event()

    class SlowErp:
        def create_post_invoice(self, invoice_data):
            release.wait(5)
            return 1, True

    worker = InvoiceSendWorker(SlowErp(), {"inv_num": "I-1"}, use_peppol=False, use_email=True)
    worker.start()
    threading.Timer(0.2, release.set).start()

    InvoiceSendWorker.wait_for_all()

    assert not worker.isRunning()
