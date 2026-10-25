"""
Backup Service
Consistent, verified snapshots of the SQLite database, and restoring them.

Why not just copy superpos.db: the DB runs in WAL mode, so recent commits
live in superpos.db-wal until SQLite checkpoints them — a plain file copy
can miss them, or catch a page halfway through being written. Snapshots go
through SQLite's online backup API instead, which copies a transactionally
consistent image while the till keeps selling (WAL readers never block
writers).

Every backup is a single zip archive, easy to copy to a USB stick:
    superpos.db     the snapshot
    manifest.json   when/why it was taken, SHA-256 + size of superpos.db,
                    row count per table

Writing one: snapshot to a temp dir → PRAGMA integrity_check → zip into
`<name>.partial` → fsync → re-read it from disk and check the hash → atomic
rename to `<name>.zip`. A crash, full disk or yanked USB stick at any point
leaves at most a `.partial` file (cleaned up later), never a `.zip` that
looks fine but isn't.

Restoring one never swaps files under the running app: the archive is fully
verified first, a "pre-restore" safety backup of the current data is taken,
then the snapshot is copied into the live DB with the same backup API, as a
single transaction — if it fails halfway, SQLite rolls it back and the
current data is left as it was. The app must restart afterwards, since every
screen still holds data read from the old DB.
"""
import hashlib
import json
import logging
import os
import platform
import re
import shutil
import sqlite3
import tempfile
import threading
import zipfile
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

import app.core.database as database
from app.core.settings_service import SettingsService

logger = logging.getLogger(__name__)

KIND_MANUAL = "manual"            # "Backup now" in the Backup dialog
KIND_DAILY = "daily"              # automatic, once a day while the POS runs
KIND_PRE_Z = "pre-z"              # right before a Z report purges the sales
KIND_PRE_RESTORE = "pre-restore"  # the data a restore is about to replace
KINDS = (KIND_MANUAL, KIND_DAILY, KIND_PRE_Z, KIND_PRE_RESTORE)

# How many of each kind to keep per backup folder; older ones are deleted
# after each successful backup. None = never deleted automatically: manual
# and pre-restore backups are rare and each one was taken for a reason.
RETENTION = {
    KIND_DAILY: 14,
    KIND_PRE_Z: 90,   # the only remaining copy of each day's purged sale lines
    KIND_MANUAL: None,
    KIND_PRE_RESTORE: None,
}

# A newer backup of any kind than this counts as "today's" daily backup.
DAILY_INTERVAL = timedelta(hours=24)

BACKUP_SETTING_EXTRA_DIR = "backup_extra_dir"  # optional second folder (USB / network share)

ARCHIVE_FORMAT = 1
DB_MEMBER = "superpos.db"
MANIFEST_MEMBER = "manifest.json"
PARTIAL_SUFFIX = ".partial"
# A .partial this old can't still be in progress — it's left over from a crash.
STALE_PARTIAL_AGE = timedelta(hours=1)
# Tables a file must have to be a SuperPOS database at all.
REQUIRED_TABLES = frozenset({"settings", "products", "sales", "z_reports", "invoices"})

_NAME_RE = re.compile(
    r"^superpos-(?P<stamp>\d{8}-\d{6})(?:_(?P<n>\d+))?-(?P<kind>" +
    "|".join(re.escape(k) for k in KINDS) + r")\.zip$"
)
_STAMP_FORMAT = "%Y%m%d-%H%M%S"
_CHUNK = 1024 * 1024

# One backup/restore at a time, whichever thread asked: the daily worker, a
# manual backup and a pre-Z backup must not race on the same folder. An RLock
# because restore_backup() takes its safety backup while holding it.
_lock = threading.RLock()


class BackupError(Exception):
    """A backup couldn't be written or verified, or a restore was refused.
    The message is meant to be shown to the user."""


@dataclass(frozen=True)
class BackupInfo:
    """One backup archive as found on disk, read from its file name alone
    (listing a folder doesn't open every zip). verify_archive() checks it."""
    path: Path
    created_at: datetime
    kind: str
    size: int


@dataclass
class BackupResult:
    """`archives` were written and verified; `failures` maps each folder that
    couldn't be written to why. create_backup() raises instead when nothing
    was written at all, so a result always holds at least one archive."""
    manifest: dict
    archives: list[Path] = field(default_factory=list)
    failures: dict[str, str] = field(default_factory=dict)


class BackupService:

    # ── Locations ─────────────────────────────────────────────────────────

    @staticmethod
    def default_backup_dir() -> Path:
        """`backups/` next to the live DB — always written, even when the
        extra folder (USB stick) isn't plugged in."""
        return Path(database.DB_PATH).parent / "backups"

    @staticmethod
    def destinations(session: Session) -> list[Path]:
        """Every folder a backup is written to: the local one first, then
        the extra one from Settings, if set."""
        dests = [BackupService.default_backup_dir()]
        extra = (SettingsService.get(session, BACKUP_SETTING_EXTRA_DIR) or "").strip()
        if extra and Path(extra).resolve() != dests[0].resolve():
            dests.append(Path(extra))
        return dests

    # ── Creating ──────────────────────────────────────────────────────────

    @staticmethod
    def create_backup(kind: str, destinations: list[Path], db_path=None) -> BackupResult:
        """Snapshot the DB and write a verified archive into each destination.

        A destination that fails (USB stick missing, disk full...) is logged
        and reported in the result's `failures`; the others still get their
        copy. Raises BackupError if the snapshot itself fails or no
        destination could be written."""
        if kind not in KINDS:
            raise ValueError(f"Unknown backup kind {kind!r}")
        db_path = Path(db_path or database.DB_PATH)
        with _lock:
            if not db_path.is_file():
                raise BackupError(f"Database not found: {db_path}")
            created_at = datetime.now()
            with tempfile.TemporaryDirectory(prefix="superpos-backup-") as tmp:
                snapshot = Path(tmp) / DB_MEMBER
                try:
                    _snapshot(db_path, snapshot)
                    manifest = _build_manifest(snapshot, kind, created_at)
                except sqlite3.Error as e:
                    logger.exception("Backup (%s): snapshot of %s failed", kind, db_path)
                    raise BackupError(f"Could not read the database: {e}") from e

                result = BackupResult(manifest=manifest)
                name = archive_name(created_at, kind)
                for dest in destinations:
                    dest = Path(dest)
                    try:
                        path = _write_archive(snapshot, manifest, dest, name)
                    except (OSError, BackupError) as e:
                        logger.error("Backup (%s) to %s failed: %s", kind, dest, e)
                        result.failures[str(dest)] = str(e)
                        continue
                    result.archives.append(path)
                    logger.info("Backup (%s) written: %s (%d bytes)",
                                kind, path, path.stat().st_size)
                    try:
                        BackupService.prune(dest)
                    except OSError as e:  # the backup itself is fine; just log it
                        logger.warning("Pruning old backups in %s failed: %s", dest, e)

        if not result.archives:
            raise BackupError("Backup failed for every folder:\n" + "\n".join(
                f"{d}: {err}" for d, err in result.failures.items()))
        return result

    # ── Listing / retention ───────────────────────────────────────────────

    @staticmethod
    def list_backups(directory) -> list[BackupInfo]:
        """Backups in `directory`, newest first. Files that aren't named
        like one of ours (including in-progress .partial files) are ignored;
        a missing folder simply has none."""
        directory = Path(directory)
        try:
            entries = list(directory.iterdir())
        except OSError:
            return []
        infos = []
        for path in entries:
            m = _NAME_RE.match(path.name)
            if not m or not path.is_file():
                continue
            try:
                created_at = datetime.strptime(m["stamp"], _STAMP_FORMAT)
                size = path.stat().st_size
            except (ValueError, OSError):
                continue
            infos.append(BackupInfo(path, created_at, m["kind"], size))
        infos.sort(key=lambda i: (i.created_at, i.path.name), reverse=True)
        return infos

    @staticmethod
    def latest_backup(directory) -> BackupInfo | None:
        backups = BackupService.list_backups(directory)
        return backups[0] if backups else None

    @staticmethod
    def is_backup_due(directory, now: datetime = None) -> bool:
        """True if `directory` holds no backup taken within DAILY_INTERVAL.
        Any kind counts: a manual or pre-Z backup an hour ago is just as good."""
        latest = BackupService.latest_backup(directory)
        now = now or datetime.now()
        return latest is None or now - latest.created_at >= DAILY_INTERVAL

    @staticmethod
    def prune(directory, now: datetime = None) -> list[Path]:
        """Apply RETENTION to `directory`, and clear .partial files left by a
        crash. Returns what was deleted."""
        directory = Path(directory)
        now = now or datetime.now()
        deleted = []
        backups = BackupService.list_backups(directory)
        for kind, keep in RETENTION.items():
            if keep is None:
                continue
            for info in [b for b in backups if b.kind == kind][keep:]:
                info.path.unlink(missing_ok=True)
                deleted.append(info.path)
        for path in directory.glob(f"superpos-*{PARTIAL_SUFFIX}"):
            try:
                age = now - datetime.fromtimestamp(path.stat().st_mtime)
            except OSError:
                continue
            if age >= STALE_PARTIAL_AGE:
                path.unlink(missing_ok=True)
                deleted.append(path)
        for path in deleted:
            logger.info("Old backup removed: %s", path)
        return deleted

    # ── Verifying ─────────────────────────────────────────────────────────

    @staticmethod
    def verify_archive(path) -> dict:
        """Check an archive end to end, without touching the live DB: it's a
        readable zip, the manifest is ours, and the stored DB matches the
        manifest's hash and passes SQLite's integrity check. Returns the
        manifest; raises BackupError saying what's wrong otherwise."""
        with tempfile.TemporaryDirectory(prefix="superpos-verify-") as tmp:
            return _extract_verified(Path(path), Path(tmp) / DB_MEMBER)

    @staticmethod
    def restore_warnings(manifest: dict, db_path=None) -> list[str]:
        """Things the user must know before replacing the current data with
        this backup — both can cause numbers to be issued twice."""
        db_path = Path(db_path or database.DB_PATH)
        try:
            with closing(sqlite3.connect(db_path)) as conn:
                current = _row_counts(conn)
        except sqlite3.Error:
            return []
        backup = manifest.get("row_counts", {})
        warnings = []
        z_lost = current.get("z_reports", 0) - backup.get("z_reports", 0)
        if z_lost > 0:
            warnings.append(
                f"{z_lost} Z report(s) were closed after this backup. Restoring brings "
                f"back sales those Z reports already counted, and the next Z report "
                f"will reuse their numbers.")
        inv_lost = current.get("invoices", 0) - backup.get("invoices", 0)
        if inv_lost > 0:
            warnings.append(
                f"{inv_lost} invoice(s) were made after this backup. They will be "
                f"removed here (not in the ERP), and their invoice numbers issued again.")
        return warnings

    # ── Restoring ─────────────────────────────────────────────────────────

    @staticmethod
    def restore_backup(archive, destinations: list[Path], db_path=None, engine=None) -> BackupResult:
        """Replace the live DB's contents with the archive's snapshot.

        Order matters: verify the archive fully → take a pre-restore safety
        backup of the current data → copy the snapshot in as one transaction.
        Nothing is changed if any step before the copy fails, and a failed
        copy is rolled back by SQLite. Returns the safety backup's result.
        The caller must restart the app afterwards."""
        archive = Path(archive)
        db_path = Path(db_path or database.DB_PATH)
        engine = engine if engine is not None else database.ENGINE
        if not db_path.is_file():
            raise BackupError(f"Database not found: {db_path}")
        with _lock,tempfile.TemporaryDirectory(prefix="superpos-restore-") as tmp:
            candidate = Path(tmp) / DB_MEMBER
            manifest = _extract_verified(archive, candidate)
            _check_page_size(candidate, db_path)

            try:
                safety = BackupService.create_backup(KIND_PRE_RESTORE, destinations, db_path)
            except BackupError as e:
                raise BackupError(
                    "Restore cancelled: could not back up the current data first.\n" + str(e)
                ) from e

            # Hand pooled connections back so none is mid-transaction while the
            # pages underneath it are replaced. Sessions reconnect on next use.
            engine.dispose()
            logger.warning("Restoring database from %s (taken %s, %s)",
                           archive, manifest.get("created_at"), manifest.get("kind"))
            try:
                with closing(sqlite3.connect(candidate)) as src, \
                        closing(sqlite3.connect(db_path, timeout=30)) as dst:
                    src.backup(dst)
                    _check_integrity(dst)
                    restored = _row_counts(dst)
            except (sqlite3.Error, BackupError) as e:
                logger.exception("Restore from %s failed", archive)
                raise BackupError(
                    f"Restore failed: {e}\nThe safety backup taken just before is at:\n"
                    + "\n".join(str(p) for p in safety.archives)
                ) from e

            expected = manifest.get("row_counts", {})
            if restored != expected:
                # Integrity is fine, so the data is usable, but not what the
                # manifest promised — keep a trace of it.
                logger.error("Restored row counts %s differ from the manifest's %s",
                             restored, expected)
            logger.warning("Database restored from %s; safety backup: %s",
                           archive, ", ".join(str(p) for p in safety.archives))
            return safety


def archive_name(created_at: datetime, kind: str) -> str:
    return f"superpos-{created_at.strftime(_STAMP_FORMAT)}-{kind}.zip"


# ── Internals ────────────────────────────────────────────────────────────

def _snapshot(src_path: Path, dst_path: Path):
    """Consistent copy of the live DB (WAL contents included) via SQLite's
    online backup API, made standalone (no -wal file) and integrity-checked."""
    with closing(sqlite3.connect(src_path, timeout=30)) as src, \
            closing(sqlite3.connect(dst_path)) as dst:
        src.backup(dst)
        dst.execute("PRAGMA journal_mode=DELETE")
        _check_integrity(dst)


def _check_integrity(conn: sqlite3.Connection):
    rows = conn.execute("PRAGMA integrity_check").fetchall()
    if rows != [("ok",)]:
        problems = "; ".join(r[0] for r in rows[:5])
        raise BackupError(f"Database integrity check failed: {problems}")


def _row_counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _build_manifest(snapshot: Path, kind: str, created_at: datetime) -> dict:
    with closing(sqlite3.connect(snapshot)) as conn:
        row_counts = _row_counts(conn)
        page_size = conn.execute("PRAGMA page_size").fetchone()[0]
    missing = REQUIRED_TABLES - row_counts.keys()
    if missing:
        raise BackupError(f"Not a SuperPOS database (missing tables: {', '.join(sorted(missing))})")
    return {
        "format": ARCHIVE_FORMAT,
        "app": "SuperPOS",
        "kind": kind,
        "created_at": created_at.isoformat(timespec="seconds"),
        "host": platform.node(),
        "sqlite_version": sqlite3.sqlite_version,
        "page_size": page_size,
        "db_size": snapshot.stat().st_size,
        "db_sha256": _sha256(snapshot),
        "row_counts": row_counts,
    }


def _unique_path(path: Path) -> Path:
    """`path`, or `<stamp>_2`, `_3`... if a backup was already taken this second."""
    if not path.exists() and not path.with_name(path.name + PARTIAL_SUFFIX).exists():
        return path
    m = _NAME_RE.match(path.name)
    n = 2
    while True:
        candidate = path.with_name(f"superpos-{m['stamp']}_{n}-{m['kind']}.zip")
        if not candidate.exists() and not candidate.with_name(candidate.name + PARTIAL_SUFFIX).exists():
            return candidate
        n += 1


def _write_archive(snapshot: Path, manifest: dict, dest_dir: Path, name: str) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    needed = manifest["db_size"] * 2  # generous: the zip is usually far smaller
    if shutil.disk_usage(dest_dir).free < needed:
        raise BackupError(f"Not enough free space in {dest_dir}")

    final = _unique_path(dest_dir / name)
    partial = final.with_name(final.name + PARTIAL_SUFFIX)
    try:
        with open(partial, "wb") as fh:
            with zipfile.ZipFile(fh, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(MANIFEST_MEMBER, json.dumps(manifest, indent=2))
                zf.write(snapshot, DB_MEMBER)
            fh.flush()
            os.fsync(fh.fileno())
        _verify_zip(partial)  # read back what actually reached the disk
        os.replace(partial, final)
        _fsync_dir(dest_dir)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return final


def _fsync_dir(directory: Path):
    """Make the rename itself durable. POSIX only — Windows can't open a
    directory for fsync, and NTFS journals the rename anyway."""
    if os.name == "nt":
        return
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _verify_zip(path: Path, extract_to: Path = None) -> dict:
    """Cheap check: zip readable, manifest ours, stored DB matches its hash
    (zipfile also checks each member's CRC while reading). Optionally writes
    the DB out to `extract_to` in the same pass."""
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            if not {MANIFEST_MEMBER, DB_MEMBER} <= names:
                raise BackupError("Not a SuperPOS backup (manifest or database missing).")
            manifest = json.loads(zf.read(MANIFEST_MEMBER))
            if not isinstance(manifest, dict) or manifest.get("app") != "SuperPOS":
                raise BackupError("Not a SuperPOS backup.")
            if manifest.get("format", 0) > ARCHIVE_FORMAT:
                raise BackupError("This backup was made by a newer version of the POS.")
            h = hashlib.sha256()
            out = open(extract_to, "wb") if extract_to else None
            try:
                with zf.open(DB_MEMBER) as f:
                    for chunk in iter(lambda: f.read(_CHUNK), b""):
                        h.update(chunk)
                        if out:
                            out.write(chunk)
            finally:
                if out:
                    out.close()
    except BackupError:
        raise
    except (zipfile.BadZipFile, OSError, ValueError, EOFError) as e:
        raise BackupError(f"Backup file is damaged or unreadable: {e}") from e
    if h.hexdigest() != manifest.get("db_sha256"):
        raise BackupError("Backup file is damaged: the database doesn't match its checksum.")
    return manifest


def _extract_verified(archive: Path, dest: Path) -> dict:
    """_verify_zip() plus opening the extracted DB: integrity check and the
    tables a SuperPOS DB must have."""
    if not archive.is_file():
        raise BackupError(f"Backup file not found: {archive}")
    manifest = _verify_zip(archive, extract_to=dest)
    try:
        with closing(sqlite3.connect(dest)) as conn:
            _check_integrity(conn)
            tables = set(_row_counts(conn))
    except sqlite3.Error as e:
        raise BackupError(f"Backup database can't be opened: {e}") from e
    missing = REQUIRED_TABLES - tables
    if missing:
        raise BackupError(f"Not a SuperPOS database (missing tables: {', '.join(sorted(missing))})")
    return manifest


def _check_page_size(candidate: Path, db_path: Path):
    """The backup API can't change a WAL-mode database's page size, so a
    mismatch would fail midway — refuse up front instead."""
    with closing(sqlite3.connect(candidate)) as a, closing(sqlite3.connect(db_path)) as b:
        src_size = a.execute("PRAGMA page_size").fetchone()[0]
        dst_size = b.execute("PRAGMA page_size").fetchone()[0]
    if src_size != dst_size:
        raise BackupError(
            f"Backup page size ({src_size}) differs from the current database's ({dst_size}); "
            f"it can't be restored in place.")
