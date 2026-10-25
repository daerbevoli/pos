"""
Tests for the backup UI: app.ui.dialogs.backup_dialog.BackupDialog and
BackupWorker. The Z report's backups are tested with its progress dialog
(test_z_report_progress_dialog.py).

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


def _plain_archive(monkeypatch, encrypted=False):
    """Make the dialog see "x.zip" as an archive of the given kind."""
    monkeypatch.setattr(BackupService, "read_manifest",
                        lambda p: {"format": 2 if encrypted else 1})


def test_restore_of_unverifiable_backup_shows_error_and_asks_nothing(qtbot, patched_db, overlays, monkeypatch):
    def bad(path, password=None):
        raise BackupError("damaged")
    questions = []
    _plain_archive(monkeypatch)
    monkeypatch.setattr(BackupService, "verify_archive", bad)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: questions.append(a))
    d = _dialog(qtbot, is_admin=True)

    d._restore("x.zip")

    assert questions == []
    assert overlays and overlays[0][1] == "error"


def test_declined_restore_does_not_restore(qtbot, patched_db, monkeypatch):
    restored = []
    _plain_archive(monkeypatch)
    monkeypatch.setattr(BackupService, "verify_archive",
                        lambda p, password=None: {"created_at": "2026-10-01T09:00:00"})
    monkeypatch.setattr(BackupService, "restore_warnings", lambda m: [])
    monkeypatch.setattr(BackupService, "restore_backup", lambda *a, **k: restored.append(a))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    d = _dialog(qtbot, is_admin=True)

    d._restore("x.zip")

    assert restored == []


def test_confirmed_restore_restores_then_restarts(qtbot, patched_db, monkeypatch):
    restored, restarted = [], []
    _plain_archive(monkeypatch)
    monkeypatch.setattr(BackupService, "verify_archive",
                        lambda p, password=None: {"created_at": "2026-10-01T09:00:00"})
    monkeypatch.setattr(BackupService, "restore_warnings", lambda m: [])
    monkeypatch.setattr(BackupService, "restore_backup",
                        lambda path, dests, password=None: restored.append(path))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr("app.ui.dialogs.backup_dialog.restart_app", lambda: restarted.append(True))
    d = _dialog(qtbot, is_admin=True)

    d._restore("x.zip")

    assert restored == ["x.zip"] and restarted == [True]


# ── Encryption ───────────────────────────────────────────────────────────

def test_encrypted_restore_asks_password_retries_wrong_one_and_passes_it_on(qtbot, patched_db, monkeypatch):
    from app.core.backup_service import BackupPasswordError
    _plain_archive(monkeypatch, encrypted=True)
    typed = iter(["wrong one", "right one"])
    prompts = []
    monkeypatch.setattr(BackupDialog, "_ask_archive_password",
                        lambda self, wrong: prompts.append(wrong) or next(typed))

    def verify(path, password=None):
        if password != "right one":
            raise BackupPasswordError("Wrong password")
        return {"created_at": "2026-10-01T09:00:00"}
    restored = []
    monkeypatch.setattr(BackupService, "verify_archive", verify)
    monkeypatch.setattr(BackupService, "restore_warnings", lambda m: [])
    monkeypatch.setattr(BackupService, "restore_backup",
                        lambda path, dests, password=None: restored.append(password))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr("app.ui.dialogs.backup_dialog.restart_app", lambda: None)

    _dialog(qtbot, is_admin=True)._restore("x.zip")

    assert prompts == [False, True]
    assert restored == ["right one"]


def test_cancelling_the_password_prompt_cancels_the_restore(qtbot, patched_db, monkeypatch):
    _plain_archive(monkeypatch, encrypted=True)
    monkeypatch.setattr(BackupDialog, "_ask_archive_password", lambda self, wrong: None)
    verified = []
    monkeypatch.setattr(BackupService, "verify_archive", lambda *a, **k: verified.append(a))

    _dialog(qtbot, is_admin=True)._restore("x.zip")

    assert verified == []


def test_setting_the_password_is_admin_only(qtbot, patched_db, overlays):
    _dialog(qtbot, is_admin=False)._set_password()
    assert overlays == [("Only admin.", "info")]
    assert not BackupService.has_password()


def test_encryption_status_follows_the_password(qtbot, patched_db):
    d = _dialog(qtbot)
    assert "NOT encrypted" in d.encryption_label.text()
    BackupService.set_password("a long enough password")
    d._reload()
    assert "are encrypted" in d.encryption_label.text()
    assert d.btn_password.text() == "Change password…"


def test_password_dialog_rejects_mismatch_and_saves_match(qtbot, patched_db):
    from app.ui.dialogs.backup_dialog import BackupPasswordDialog
    shown = []
    d = BackupPasswordDialog(changing=False)
    qtbot.addWidget(d)
    d.overlay.show_message = lambda msg, kind="info": shown.append(msg)

    d.new.setText("a long enough password")
    d.confirm.setText("a different password")
    d._on_ok()
    assert shown == ["The new passwords don't match."] and not BackupService.has_password()

    d.confirm.setText("a long enough password")
    d._on_ok()
    assert BackupService.check_password("a long enough password")


def test_backup_now_reports_failure(qtbot, patched_db, overlays):
    # patched_db's DB_PATH doesn't exist, so the worker fails for real.
    d = _dialog(qtbot)
    d._backup_now()
    qtbot.waitUntil(lambda: bool(overlays), timeout=5000)
    assert overlays[0][1] == "error"
    assert d.btn_backup.isEnabled()


# ── Backup workers ───────────────────────────────────────────────────────

def test_wait_for_all_waits_for_every_running_backup(qtbot, patched_db, monkeypatch):
    import threading
    from app.core.backup_worker import BackupWorker
    release = threading.Event()
    monkeypatch.setattr(BackupService, "create_backup",
                        lambda *a, **k: release.wait(5))
    workers = [BackupWorker("daily", []), BackupWorker("post-z", [])]
    for w in workers:
        w.start()
    threading.Timer(0.2, release.set).start()

    BackupWorker.wait_for_all()

    assert not any(w.isRunning() for w in workers)


def test_patched_db_keeps_backups_out_of_the_real_folder(patched_db, tmp_path):
    assert BackupService.default_backup_dir() == tmp_path / "backups"
    assert database.DB_PATH == str(tmp_path / "superpos.db")
