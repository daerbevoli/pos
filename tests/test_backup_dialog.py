"""
Tests for the backup UI: app.ui.dialogs.backup_dialog.BackupDialog and the
pre-Z-report backup in ReportsScreen.

patched_db points database.DB_PATH at a nonexistent file under tmp_path, so
BackupService.default_backup_dir() is tmp_path/backups — nothing here
touches the real backups folder. QMessageBox statics are monkeypatched.
"""
import pytest
from PyQt6.QtWidgets import QMessageBox

import app.core.database as database
from app.core.backup_service import BACKUP_SETTING_EXTRA_DIR, BackupError, BackupService
from app.core.database import get_session
from app.core.settings_service import SettingsService
from app.ui.dialogs.backup_dialog import BackupDialog
from tests.test_backup_service import _touch_backup  # noqa: F401  (shared helper)


@pytest.fixture
def overlays(monkeypatch):
    shown = []
    monkeypatch.setattr("app.ui.dialogs.backup_dialog.TapToDismissOverlay.show_message",
                        lambda self, msg, kind="info": shown.append((msg, kind)))
    return shown


def _dialog(qtbot, is_admin=False):
    d = BackupDialog(is_admin=is_admin)
    qtbot.addWidget(d)
    return d


def test_lists_backups_from_every_folder_newest_first(qtbot, patched_db, tmp_path):
    from datetime import datetime
    extra = tmp_path / "usb"
    with get_session() as session:
        SettingsService.set(session, BACKUP_SETTING_EXTRA_DIR, str(extra))
    _touch_backup(BackupService.default_backup_dir(), datetime(2026, 10, 1, 9), "daily")
    _touch_backup(extra, datetime(2026, 10, 2, 9), "manual")

    d = _dialog(qtbot)

    assert d.table.rowCount() == 2
    assert d.table.item(0, 1).text() == "Manual"
    assert d.table.item(0, 3).text() == str(extra)
    assert "02/10/2026" in d.status_label.text()


def test_empty_state(qtbot, patched_db):
    d = _dialog(qtbot)
    assert d.table.rowCount() == 0
    assert "No backup" in d.status_label.text()


def test_restore_is_admin_only(qtbot, patched_db, overlays, monkeypatch):
    called = []
    monkeypatch.setattr(BackupService, "verify_archive", lambda p: called.append(p))
    d = _dialog(qtbot, is_admin=False)
    d._restore("whatever.zip")
    assert overlays == [("Only admin.", "info")] and called == []


def test_changing_extra_folder_is_admin_only(qtbot, patched_db, overlays):
    d = _dialog(qtbot, is_admin=False)
    d._clear_extra_dir()
    assert overlays == [("Only admin.", "info")]


def test_restore_of_unverifiable_backup_shows_error_and_asks_nothing(qtbot, patched_db, overlays, monkeypatch):
    def bad(path):
        raise BackupError("damaged")
    questions = []
    monkeypatch.setattr(BackupService, "verify_archive", bad)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: questions.append(a))
    d = _dialog(qtbot, is_admin=True)

    d._restore("x.zip")

    assert questions == []
    assert overlays and overlays[0][1] == "error"


def test_declined_restore_does_not_restore(qtbot, patched_db, monkeypatch):
    restored = []
    monkeypatch.setattr(BackupService, "verify_archive", lambda p: {"created_at": "2026-10-01T09:00:00"})
    monkeypatch.setattr(BackupService, "restore_warnings", lambda m: [])
    monkeypatch.setattr(BackupService, "restore_backup", lambda *a, **k: restored.append(a))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    d = _dialog(qtbot, is_admin=True)

    d._restore("x.zip")

    assert restored == []


def test_confirmed_restore_restores_then_restarts(qtbot, patched_db, monkeypatch):
    restored, restarted = [], []
    monkeypatch.setattr(BackupService, "verify_archive", lambda p: {"created_at": "2026-10-01T09:00:00"})
    monkeypatch.setattr(BackupService, "restore_warnings", lambda m: [])
    monkeypatch.setattr(BackupService, "restore_backup", lambda path, dests: restored.append(path))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr("app.ui.dialogs.backup_dialog.restart_app", lambda: restarted.append(True))
    d = _dialog(qtbot, is_admin=True)

    d._restore("x.zip")

    assert restored == ["x.zip"] and restarted == [True]


def test_backup_now_reports_failure(qtbot, patched_db, overlays):
    # patched_db's DB_PATH doesn't exist, so the worker fails for real.
    d = _dialog(qtbot)
    d._backup_now()
    qtbot.waitUntil(lambda: bool(overlays), timeout=5000)
    assert overlays[0][1] == "error"
    assert d.btn_backup.isEnabled()


# ── Reports screen: backup before Z report ───────────────────────────────

@pytest.fixture
def reports(qtbot, patched_db):
    from app.ui.reports_screen import ReportsScreen
    s = ReportsScreen()
    qtbot.addWidget(s)
    return s


def test_z_report_is_backed_up_first(reports, monkeypatch):
    kinds = []
    monkeypatch.setattr(BackupService, "create_backup", lambda kind, dests: kinds.append(kind))
    assert reports._backup_before_z() is True
    assert kinds == ["pre-z"]


def test_failed_pre_z_backup_lets_cashier_cancel(reports, monkeypatch):
    def fail(kind, dests):
        raise BackupError("disk full")
    monkeypatch.setattr(BackupService, "create_backup", fail)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    assert reports._backup_before_z() is False


def test_z_report_not_closed_when_backup_fails_and_cashier_declines(reports, monkeypatch):
    answers = iter([QMessageBox.StandardButton.Yes,   # print the Z report?
                    QMessageBox.StandardButton.No])   # backup failed — continue anyway?
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: next(answers))
    monkeypatch.setattr(BackupService, "create_backup",
                        lambda kind, dests: (_ for _ in ()).throw(BackupError("disk full")))
    closed = []
    monkeypatch.setattr("app.ui.reports_screen.XZReportService.close_z_report",
                        lambda session: closed.append(True))

    reports._print_z_report()

    assert closed == []


def test_failed_pre_z_backup_can_be_overridden(reports, monkeypatch):
    def fail(kind, dests):
        raise BackupError("disk full")
    monkeypatch.setattr(BackupService, "create_backup", fail)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    assert reports._backup_before_z() is True


def test_patched_db_keeps_backups_out_of_the_real_folder(patched_db, tmp_path):
    assert BackupService.default_backup_dir() == tmp_path / "backups"
    assert database.DB_PATH == str(tmp_path / "superpos.db")
