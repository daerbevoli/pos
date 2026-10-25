"""
Tests for app.core.backup_service.

Each test builds a real WAL-mode SQLite file under tmp_path (the backup API
needs a file, not :memory:) and passes it explicitly — nothing here reads
the real per-user database or writes into its backups folder.
"""
import json
import os
import sqlite3
import zipfile
from contextlib import closing
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

import app.core.database as database
from app.core import backup_key
from app.core.backup_service import (
    DB_MEMBER, ENC_MEMBER, KIND_DAILY, KIND_MANUAL, KIND_POST_Z, KIND_PRE_RESTORE, KIND_PRE_Z,
    MANIFEST_MEMBER, RETENTION, BackupError, BackupPasswordError, BackupService, archive_name,
)
from app.models.models import Base, Category, ZReport


@pytest.fixture(autouse=True)
def isolated_key_store(monkeypatch, tmp_path):
    """The backup password file lives next to DB_PATH: point that at
    tmp_path so no test reads or writes the real one."""
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "superpos.db"))


@pytest.fixture
def live_db(tmp_path):
    """A WAL-mode DB file with the full schema, like the app's real one."""
    path = tmp_path / "superpos.db"
    engine = create_engine(f"sqlite:///{path}")

    @event.listens_for(engine, "connect")
    def _wal(dbapi_connection, _):
        dbapi_connection.execute("PRAGMA journal_mode=WAL")

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as s:
        s.add(Category(name="Dairy"))
        s.commit()
    yield path, engine, Session
    engine.dispose()


def _categories(path):
    with closing(sqlite3.connect(path)) as conn:
        return sorted(r[0] for r in conn.execute("SELECT name FROM categories"))


def _backup(live_db, dests, kind=KIND_MANUAL, password=None):
    return BackupService.create_backup(kind, dests, db_path=live_db[0], password=password)


def _add_z_report(Session, number):
    with Session() as s:
        now = datetime.now()
        s.add(ZReport(report_number=number, period_start=now, period_end=now))
        s.commit()


# ── Creating ─────────────────────────────────────────────────────────────

def test_backup_writes_verified_archive_with_manifest(live_db, tmp_path):
    dest = tmp_path / "backups"
    result = _backup(live_db, [dest])

    assert result.failures == {}
    [archive] = result.archives
    assert archive.parent == dest and archive.suffix == ".zip"
    with zipfile.ZipFile(archive) as zf:
        assert set(zf.namelist()) == {DB_MEMBER, MANIFEST_MEMBER}
        manifest = json.loads(zf.read(MANIFEST_MEMBER))
    assert manifest["kind"] == KIND_MANUAL
    assert manifest["row_counts"]["categories"] == 1
    assert BackupService.verify_archive(archive) == manifest


def test_backup_includes_commits_still_in_the_wal(live_db, tmp_path):
    path, engine, Session = live_db
    # Keep a connection open so SQLite can't checkpoint on close: the row
    # lives only in superpos.db-wal, which a plain file copy would miss.
    with engine.connect():
        with Session() as s:
            s.add(Category(name="Bakery"))
            s.commit()
        assert (tmp_path / "superpos.db-wal").stat().st_size > 0
        archive = _backup(live_db, [tmp_path / "backups"]).archives[0]

    restored = tmp_path / "restored.db"
    with zipfile.ZipFile(archive) as zf:
        restored.write_bytes(zf.read(DB_MEMBER))
    assert _categories(restored) == ["Bakery", "Dairy"]


def test_backup_leaves_no_partial_files(live_db, tmp_path):
    dest = tmp_path / "backups"
    _backup(live_db, [dest])
    assert [p.name for p in dest.iterdir() if p.name.endswith(".partial")] == []


def test_two_backups_in_the_same_second_get_distinct_names(live_db, tmp_path, monkeypatch):
    fixed = datetime(2026, 10, 24, 10, 0, 0)

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed

    monkeypatch.setattr("app.core.backup_service.datetime", _Frozen)
    dest = tmp_path / "backups"
    first = _backup(live_db, [dest]).archives[0]
    second = _backup(live_db, [dest]).archives[0]
    assert first != second
    assert len(BackupService.list_backups(dest)) == 2


def test_one_failing_folder_does_not_stop_the_others(live_db, tmp_path):
    good = tmp_path / "backups"
    bad = tmp_path / "not-a-folder"
    bad.write_text("I'm a file")

    result = _backup(live_db, [good, bad])

    assert len(result.archives) == 1 and result.archives[0].parent == good
    assert str(bad) in result.failures


def test_backup_raises_when_every_folder_fails(live_db, tmp_path):
    bad = tmp_path / "not-a-folder"
    bad.write_text("I'm a file")
    with pytest.raises(BackupError):
        _backup(live_db, [bad])


def test_backup_of_missing_database_raises(tmp_path):
    with pytest.raises(BackupError):
        BackupService.create_backup(KIND_MANUAL, [tmp_path], db_path=tmp_path / "nope.db")


def test_unknown_kind_is_rejected(live_db, tmp_path):
    with pytest.raises(ValueError):
        _backup(live_db, [tmp_path], kind="weekly")


# ── Verifying ────────────────────────────────────────────────────────────

def test_verify_detects_a_tampered_database(live_db, tmp_path):
    archive = _backup(live_db, [tmp_path / "backups"]).archives[0]
    with zipfile.ZipFile(archive) as zf:
        manifest, db = zf.read(MANIFEST_MEMBER), bytearray(zf.read(DB_MEMBER))
    db[-1] ^= 0xFF
    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(tampered, "w") as zf:
        zf.writestr(MANIFEST_MEMBER, manifest)
        zf.writestr(DB_MEMBER, bytes(db))

    with pytest.raises(BackupError, match="checksum"):
        BackupService.verify_archive(tampered)


def test_verify_rejects_truncated_archive(live_db, tmp_path):
    archive = _backup(live_db, [tmp_path / "backups"]).archives[0]
    truncated = tmp_path / "truncated.zip"
    truncated.write_bytes(archive.read_bytes()[:200])
    with pytest.raises(BackupError):
        BackupService.verify_archive(truncated)


def test_verify_rejects_a_zip_that_is_not_ours(tmp_path):
    other = tmp_path / "other.zip"
    with zipfile.ZipFile(other, "w") as zf:
        zf.writestr("readme.txt", "hello")
    with pytest.raises(BackupError, match="Not a SuperPOS backup"):
        BackupService.verify_archive(other)


# ── Listing / retention ──────────────────────────────────────────────────

def _touch_backup(directory, created_at, kind):
    directory.mkdir(exist_ok=True)
    path = directory / archive_name(created_at, kind)
    path.write_bytes(b"x")
    return path


def test_list_backups_newest_first_and_ignores_strangers(tmp_path):
    old = _touch_backup(tmp_path, datetime(2026, 10, 1, 9), KIND_DAILY)
    new = _touch_backup(tmp_path, datetime(2026, 10, 2, 9), KIND_PRE_Z)
    (tmp_path / "holiday.jpg").write_bytes(b"x")
    (tmp_path / (new.name + ".partial")).write_bytes(b"x")

    infos = BackupService.list_backups(tmp_path)

    assert [i.path for i in infos] == [new, old]
    assert [i.kind for i in infos] == [KIND_PRE_Z, KIND_DAILY]


def test_list_backups_of_missing_folder_is_empty(tmp_path):
    assert BackupService.list_backups(tmp_path / "nope") == []


def test_prune_keeps_newest_daily_and_never_touches_manual(tmp_path):
    keep = RETENTION[KIND_DAILY]
    start = datetime(2026, 1, 1)
    daily = [_touch_backup(tmp_path, start + timedelta(days=i), KIND_DAILY) for i in range(keep + 3)]
    manual = [_touch_backup(tmp_path, start + timedelta(days=i, hours=1), KIND_MANUAL) for i in range(keep + 3)]

    deleted = BackupService.prune(tmp_path)

    assert sorted(deleted) == sorted(daily[:3])
    assert all(p.exists() for p in daily[3:] + manual)


def test_prune_clears_only_stale_partial_files(tmp_path):
    stale = tmp_path / "superpos-20260101-000000-daily.zip.partial"
    stale.write_bytes(b"x")
    fresh_now = datetime.fromtimestamp(stale.stat().st_mtime)

    assert BackupService.prune(tmp_path, now=fresh_now) == []
    assert BackupService.prune(tmp_path, now=fresh_now + timedelta(hours=2)) == [stale]


def test_daily_backup_is_due_from_noon_until_taken(tmp_path):
    day = datetime(2026, 10, 24)
    assert not BackupService.daily_backup_due(tmp_path, day.replace(hour=11, minute=59))
    assert BackupService.daily_backup_due(tmp_path, day.replace(hour=12))
    assert BackupService.daily_backup_due(tmp_path, day.replace(hour=17))  # POS started late: catch up

    _touch_backup(tmp_path, day.replace(hour=12, second=5), KIND_DAILY)
    assert not BackupService.daily_backup_due(tmp_path, day.replace(hour=18))
    # Next day: not before noon, then due again.
    assert not BackupService.daily_backup_due(tmp_path, day.replace(day=25, hour=9))
    assert BackupService.daily_backup_due(tmp_path, day.replace(day=25, hour=12))


def test_other_kinds_or_a_morning_daily_do_not_count_as_the_noon_backup(tmp_path):
    day = datetime(2026, 10, 24)
    _touch_backup(tmp_path, day.replace(hour=13), KIND_MANUAL)
    _touch_backup(tmp_path, day.replace(hour=13, minute=1), KIND_PRE_Z)
    _touch_backup(tmp_path, day.replace(hour=13, minute=2), KIND_POST_Z)
    _touch_backup(tmp_path, day.replace(hour=11), KIND_DAILY)
    assert BackupService.daily_backup_due(tmp_path, day.replace(hour=14))


def test_post_z_backups_are_pruned_to_their_retention(tmp_path):
    keep = RETENTION[KIND_POST_Z]
    start = datetime(2026, 1, 1, 20)
    made = [_touch_backup(tmp_path, start + timedelta(days=i), KIND_POST_Z) for i in range(keep + 2)]
    assert sorted(BackupService.prune(tmp_path)) == sorted(made[:2])


# ── Restoring ────────────────────────────────────────────────────────────

def test_restore_brings_back_old_data_and_keeps_a_safety_backup(live_db, tmp_path):
    path, engine, Session = live_db
    dest = tmp_path / "backups"
    archive = _backup(live_db, [dest]).archives[0]
    with Session() as s:
        s.add(Category(name="Added after backup"))
        s.commit()

    safety = BackupService.restore_backup(archive, [dest], db_path=path, engine=engine)

    assert _categories(path) == ["Dairy"]
    [safety_archive] = safety.archives
    assert BackupService.list_backups(dest)[0].kind == KIND_PRE_RESTORE
    with zipfile.ZipFile(safety_archive) as zf:
        (tmp_path / "safety.db").write_bytes(zf.read(DB_MEMBER))
    assert _categories(tmp_path / "safety.db") == ["Added after backup", "Dairy"]

    # The app's engine keeps working on the restored data.
    with Session() as s:
        assert [c.name for c in s.query(Category).all()] == ["Dairy"]


def test_restore_of_damaged_archive_changes_nothing(live_db, tmp_path):
    path, engine, Session = live_db
    dest = tmp_path / "backups"
    damaged = tmp_path / "superpos-20260101-000000-manual.zip"
    damaged.write_bytes(b"not a zip at all")
    with Session() as s:
        s.add(Category(name="Bakery"))
        s.commit()

    with pytest.raises(BackupError):
        BackupService.restore_backup(damaged, [dest], db_path=path, engine=engine)

    assert _categories(path) == ["Bakery", "Dairy"]
    assert BackupService.list_backups(dest) == []  # no safety backup either


def test_restore_is_cancelled_if_the_safety_backup_fails(live_db, tmp_path):
    path, engine, Session = live_db
    archive = _backup(live_db, [tmp_path / "backups"]).archives[0]
    with Session() as s:
        s.add(Category(name="Bakery"))
        s.commit()
    bad = tmp_path / "not-a-folder"
    bad.write_text("I'm a file")

    with pytest.raises(BackupError, match="Restore cancelled"):
        BackupService.restore_backup(archive, [bad], db_path=path, engine=engine)

    assert _categories(path) == ["Bakery", "Dairy"]


def test_restore_warns_when_z_reports_would_be_lost(live_db, tmp_path):
    path, engine, Session = live_db
    archive = _backup(live_db, [tmp_path / "backups"]).archives[0]
    manifest = BackupService.verify_archive(archive)
    assert BackupService.restore_warnings(manifest, db_path=path) == []

    _add_z_report(Session, "Z-0001")

    [warning] = BackupService.restore_warnings(manifest, db_path=path)
    assert "Z report" in warning


# ── Encryption ───────────────────────────────────────────────────────────

PASSWORD = "correct horse battery"


def _rewrite_archive(src, dst, manifest=None, payload=None):
    """Copy an archive, optionally replacing its manifest / encrypted member."""
    with zipfile.ZipFile(src) as zf:
        m = manifest if manifest is not None else zf.read(MANIFEST_MEMBER)
        data = payload if payload is not None else zf.read(ENC_MEMBER)
    with zipfile.ZipFile(dst, "w") as zf:
        zf.writestr(MANIFEST_MEMBER, m)
        zf.writestr(ENC_MEMBER, data)
    return dst


def test_encrypted_archive_reveals_no_data(live_db, tmp_path):
    archive = _backup(live_db, [tmp_path / "backups"], password=PASSWORD).archives[0]

    with zipfile.ZipFile(archive) as zf:
        assert set(zf.namelist()) == {MANIFEST_MEMBER, ENC_MEMBER}
        manifest = json.loads(zf.read(MANIFEST_MEMBER))
    assert manifest["format"] == 2
    assert "row_counts" not in manifest and "db_sha256" not in manifest and "host" not in manifest
    raw = archive.read_bytes()
    assert b"Dairy" not in raw and b"SQLite format" not in raw


def test_encrypted_archive_verifies_only_with_its_password(live_db, tmp_path):
    archive = _backup(live_db, [tmp_path / "backups"], password=PASSWORD).archives[0]

    manifest = BackupService.verify_archive(archive, PASSWORD)
    assert manifest["row_counts"]["categories"] == 1
    with pytest.raises(BackupPasswordError):
        BackupService.verify_archive(archive)
    with pytest.raises(BackupPasswordError):
        BackupService.verify_archive(archive, "wrong password")


def test_unicode_password_matches_however_it_was_typed(live_db, tmp_path):
    composed, decomposed = "café-secret", "café-secret"
    archive = _backup(live_db, [tmp_path / "backups"], password=composed).archives[0]
    BackupService.verify_archive(archive, decomposed)


def test_edited_manifest_is_detected(live_db, tmp_path):
    archive = _backup(live_db, [tmp_path / "backups"], password=PASSWORD).archives[0]
    manifest = BackupService.read_manifest(archive)
    manifest["created_at"] = "2020-01-01T00:00:00"
    forged = _rewrite_archive(archive, tmp_path / "forged.zip", manifest=json.dumps(manifest))
    with pytest.raises(BackupPasswordError):
        BackupService.verify_archive(forged, PASSWORD)


def test_flipped_ciphertext_byte_is_detected(live_db, tmp_path):
    archive = _backup(live_db, [tmp_path / "backups"], password=PASSWORD).archives[0]
    with zipfile.ZipFile(archive) as zf:
        data = bytearray(zf.read(ENC_MEMBER))
    data[len(data) // 2] ^= 0x01
    damaged = _rewrite_archive(archive, tmp_path / "damaged.zip", payload=bytes(data))
    with pytest.raises(BackupError):
        BackupService.verify_archive(damaged, PASSWORD)


def test_restore_encrypted_backup(live_db, tmp_path):
    path, engine, Session = live_db
    dest = tmp_path / "backups"
    archive = _backup(live_db, [dest], password=PASSWORD).archives[0]
    with Session() as s:
        s.add(Category(name="Bakery"))
        s.commit()

    with pytest.raises(BackupPasswordError):
        BackupService.restore_backup(archive, [dest], db_path=path, engine=engine)
    assert _categories(path) == ["Bakery", "Dairy"]

    BackupService.restore_backup(archive, [dest], db_path=path, engine=engine, password=PASSWORD)
    assert _categories(path) == ["Dairy"]


# ── Stored password ──────────────────────────────────────────────────────

def test_backups_use_the_stored_password(live_db, tmp_path):
    assert not BackupService.has_password()
    BackupService.set_password(PASSWORD)
    assert BackupService.has_password()

    result = BackupService.create_backup(KIND_DAILY, [tmp_path / "backups"], db_path=live_db[0])

    assert result.encrypted
    BackupService.verify_archive(result.archives[0], PASSWORD)


def test_safety_backup_before_restore_is_encrypted_too(live_db, tmp_path):
    path, engine, _ = live_db
    dest = tmp_path / "backups"
    BackupService.set_password(PASSWORD)
    archive = BackupService.create_backup(KIND_MANUAL, [dest], db_path=path).archives[0]

    safety = BackupService.restore_backup(archive, [dest], db_path=path, engine=engine, password=PASSWORD)

    assert safety.encrypted


def test_password_rules(live_db):
    with pytest.raises(BackupError, match="at least"):
        BackupService.set_password("short")
    BackupService.set_password(PASSWORD)
    assert BackupService.check_password(PASSWORD)
    assert not BackupService.check_password("something else")

    with pytest.raises(BackupPasswordError):
        BackupService.set_password("a new password", current_password="not it")
    BackupService.set_password("a new password", current_password=PASSWORD)
    assert BackupService.check_password("a new password")


def test_unreadable_stored_password_fails_instead_of_writing_plaintext(live_db, tmp_path):
    backup_key.key_path().write_bytes(b"\xff\xff\xff not a valid blob")
    dest = tmp_path / "backups"

    with pytest.raises(BackupError):
        BackupService.create_backup(KIND_DAILY, [dest], db_path=live_db[0])
    assert BackupService.list_backups(dest) == []


def test_stored_password_is_not_kept_in_plain_text_on_windows(live_db):
    if os.name != "nt":
        pytest.skip("DPAPI is Windows-only")
    BackupService.set_password(PASSWORD)
    assert PASSWORD.encode() not in backup_key.key_path().read_bytes()
    assert backup_key.load() == PASSWORD


def test_backup_progress_only_goes_up_and_ends_complete(live_db, tmp_path):
    seen = []
    BackupService.create_backup(KIND_MANUAL, [tmp_path / "a", tmp_path / "b"],
                                db_path=live_db[0], password=PASSWORD, progress=seen.append)
    assert seen == sorted(seen)
    assert seen[-1] == 1.0 and 0 < seen[0] < 1
