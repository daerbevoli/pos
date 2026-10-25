"""
Tests for app.ui.dialogs.z_report_progress_dialog.ZReportProgressDialog:
the Z report run step by step (backup before → close → backup after →
print) behind a progress bar.

patched_db isolates the DB; backups and printing are faked per test, and
QMessageBox statics are monkeypatched. start() is called instead of exec()
so the test isn't blocked by the modal loop.
"""
import pytest
from PyQt6.QtWidgets import QMessageBox

from app.core.backup_service import BackupError, BackupResult, BackupService
from app.core.database import get_session
from app.core.receipt_service import PrinterError, ReceiptService
from app.models.models import ZReport
from app.ui.dialogs.z_report_progress_dialog import ZReportProgressDialog


@pytest.fixture
def backups(monkeypatch):
    """Fake create_backup: records kinds, reports progress, succeeds unless
    the kind is listed in `fail`."""
    state = {"kinds": [], "fail": set(), "partial": set()}

    def create_backup(kind, destinations, progress=None, **kwargs):
        state["kinds"].append(kind)
        if progress:
            progress(0.5)
            progress(1.0)
        if kind in state["fail"]:
            raise BackupError("disk full")
        result = BackupResult(manifest={})
        result.archives.append("local.zip")
        if kind in state["partial"]:
            result.failures["G:/My Drive"] = "not reachable"
        return result
    monkeypatch.setattr(BackupService, "create_backup", create_backup)
    return state


@pytest.fixture
def printed(monkeypatch):
    calls = []
    monkeypatch.setattr(ReceiptService, "print_z_report",
                        lambda session, z, reprint=False: calls.append(z.report_number))
    return calls


def _run(qtbot, answer=QMessageBox.StandardButton.No, monkeypatch=None):
    if monkeypatch is not None:
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: answer)
    d = ZReportProgressDialog()
    qtbot.addWidget(d)
    with qtbot.waitSignal(d.run_finished, timeout=10000):
        d.start()
    return d


def _z_count():
    with get_session() as session:
        return session.query(ZReport).count()


def test_runs_backup_close_backup_print_in_order(qtbot, patched_db, backups, printed):
    progress_seen = []
    d = ZReportProgressDialog()
    qtbot.addWidget(d)
    d.bar.valueChanged.connect(progress_seen.append)
    with qtbot.waitSignal(d.run_finished, timeout=10000):
        d.start()

    assert backups["kinds"] == ["pre-z", "post-z"]
    assert printed == ["Z-0001"] and d.z_number == "Z-0001" and _z_count() == 1
    assert d.bar.value() == 100
    assert progress_seen == sorted(progress_seen)  # only ever fills up
    assert d.problems == [] and d.details.isHidden()
    assert "Z-0001 completed" in d.step_label.text()


def test_cannot_be_closed_while_running(qtbot, patched_db, backups, printed):
    d = ZReportProgressDialog()
    qtbot.addWidget(d)
    d.is_running = True
    d.reject()
    assert d.btn_close.isHidden()
    assert d.result() == 0 and d.is_running  # still open, nothing done


def test_failed_backup_before_and_cashier_declines_changes_nothing(qtbot, patched_db, backups, printed, monkeypatch):
    backups["fail"].add("pre-z")

    d = _run(qtbot, QMessageBox.StandardButton.No, monkeypatch)

    assert _z_count() == 0 and printed == [] and backups["kinds"] == ["pre-z"]
    assert d.z_number is None and "cancelled" in d.step_label.text()
    assert not d.btn_close.isHidden()


def _typed_code(monkeypatch, code):
    """The admin-code numpad: `code` typed and OK pressed, or None = Cancel."""
    from app.ui.dialogs.numpad_dialog import NumpadDialog
    asked = []

    def exec_(self):
        asked.append(self.display.echoMode())
        self.value = code
        return code is not None
    monkeypatch.setattr(NumpadDialog, "exec", exec_)
    return asked


def test_failed_backup_before_can_be_overridden_with_the_admin_code(qtbot, patched_db, backups, printed, monkeypatch):
    from PyQt6.QtWidgets import QLineEdit
    from app.core.admin import ADMIN_CODE
    backups["fail"].add("pre-z")
    asked = _typed_code(monkeypatch, ADMIN_CODE)

    d = _run(qtbot, QMessageBox.StandardButton.Yes, monkeypatch)

    assert asked == [QLineEdit.EchoMode.Password]  # asked once, digits hidden
    assert _z_count() == 1 and printed == ["Z-0001"]
    assert backups["kinds"] == ["pre-z", "post-z"]
    assert any("No backup was made before" in p for p in d.problems)
    assert not d.details.isHidden()


@pytest.mark.parametrize("code", ["1234", "", None])
def test_continue_anyway_without_the_right_code_changes_nothing(qtbot, patched_db, backups, printed, monkeypatch, code):
    backups["fail"].add("pre-z")
    _typed_code(monkeypatch, code)

    d = _run(qtbot, QMessageBox.StandardButton.Yes, monkeypatch)

    assert _z_count() == 0 and printed == [] and backups["kinds"] == ["pre-z"]
    assert d.z_number is None and "Wrong admin code" in d.step_label.text()


def test_admin_code_is_only_asked_when_the_backup_fails(qtbot, patched_db, backups, printed, monkeypatch):
    asked = _typed_code(monkeypatch, "anything")
    _run(qtbot)
    assert asked == []


def test_check_admin_code():
    from app.core.admin import ADMIN_CODE, check_admin_code
    assert check_admin_code(ADMIN_CODE)
    assert not check_admin_code(ADMIN_CODE + "0")
    assert not check_admin_code("")
    assert not check_admin_code(None)


def test_failed_backup_after_is_reported_but_z_is_done(qtbot, patched_db, backups, printed):
    backups["fail"].add("post-z")

    d = _run(qtbot)

    assert _z_count() == 1 and printed == ["Z-0001"]
    assert any("Backup after the Z report failed" in p for p in d.problems)


def test_folder_that_failed_is_listed(qtbot, patched_db, backups, printed):
    backups["partial"].add("pre-z")
    d = _run(qtbot)
    assert any("G:/My Drive" in p for p in d.problems)


def test_printer_failure_keeps_the_z_report(qtbot, patched_db, backups, monkeypatch):
    def fail(*a, **k):
        raise PrinterError("no paper")
    monkeypatch.setattr(ReceiptService, "print_z_report", fail)

    d = _run(qtbot)

    assert _z_count() == 1 and d.z_number == "Z-0001"
    assert any("no paper" in p and "Z Reports" in p for p in d.problems)


def test_refused_z_report_takes_no_backup_after(qtbot, patched_db, backups, printed, monkeypatch):
    def refuse(session):
        raise ValueError("Open tickets on V 2")
    monkeypatch.setattr("app.ui.dialogs.z_report_progress_dialog.XZReportService.close_z_report", refuse)

    d = _run(qtbot)

    assert backups["kinds"] == ["pre-z"] and printed == []
    assert d.z_number is None and "Open tickets on V 2" in d.step_label.text()


def test_reports_screen_opens_the_dialog_after_confirmation(qtbot, patched_db, monkeypatch):
    from app.ui.reports_screen import ReportsScreen
    screen = ReportsScreen()
    qtbot.addWidget(screen)
    opened = []
    monkeypatch.setattr(ZReportProgressDialog, "exec", lambda self: opened.append(self))

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    screen._print_z_report()
    assert opened == []

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    screen._print_z_report()
    assert len(opened) == 1
