"""
Backup Service
Consistent, verified, encrypted snapshots of the SQLite database, and
restoring them.

Why not just copy superpos.db: the DB runs in WAL mode, so recent commits
live in superpos.db-wal until SQLite checkpoints them — a plain file copy
can miss them, or catch a page halfway through being written. Snapshots go
through SQLite's online backup API instead, which copies a transactionally
consistent image while the till keeps selling (WAL readers never block
writers).

Every backup is a single zip archive, easy to copy to a USB stick or cloud
folder. Encrypted (format 2, whenever a backup password is set):
    manifest.json     only what's needed to decrypt: kind, date, KDF salt,
                      nonce — no client data, no row counts
    superpos.db.enc   zlib-compressed snapshot, AES-256-GCM encrypted with a
                      key derived from the backup password (scrypt, random
                      salt per archive). GCM authenticates it together with
                      the manifest, so changing either byte is detected.
Unencrypted (format 1, no password set yet; still readable for older ones):
    manifest.json     also SHA-256 of the DB and row counts
    superpos.db       the snapshot

Writing one: snapshot to a temp dir → PRAGMA integrity_check → (encrypt) →
zip into `<name>.partial` → fsync → re-read it from disk and verify (decrypt
/ hash) → atomic rename to `<name>.zip`. A crash, full disk or yanked USB
stick at any point leaves at most a `.partial` file (cleaned up later),
never a `.zip` that looks fine but isn't.

Restoring one never swaps files under the running app: the archive is fully
verified first (which, for an encrypted one, needs its password), a
"pre-restore" safety backup of the current data is taken, then the snapshot
is copied into the live DB with the same backup API, as a single
transaction — if it fails halfway, SQLite rolls it back and the current
data is left as it was. The app must restart afterwards, since every screen
still holds data read from the old DB.
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import platform
import re
import shutil
import sqlite3
import tempfile
import threading
import unicodedata
import zipfile
import zlib
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.orm import Session

import app.core.database as database
from app.core import backup_key
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

FORMAT_PLAIN = 1
FORMAT_ENCRYPTED = 2
DB_MEMBER = "superpos.db"
ENC_MEMBER = "superpos.db.enc"
MANIFEST_MEMBER = "manifest.json"
PARTIAL_SUFFIX = ".partial"
# A .partial this old can't still be in progress — it's left over from a crash.
STALE_PARTIAL_AGE = timedelta(hours=1)
# Tables a file must have to be a SuperPOS database at all.
REQUIRED_TABLES = frozenset({"settings", "products", "sales", "z_reports", "invoices"})

MIN_PASSWORD_LENGTH = 8
# scrypt cost: ~0.1–0.3 s and 32 MiB per derivation — negligible once per
# backup, but makes guessing the password from a stolen archive slow.
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2 ** 15, 8, 1
_SCRYPT_MAXMEM = 64 * 1024 * 1024

# Pass as `password` to use the password stored on this PC (backup_key).
STORED_PASSWORD = object()

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


class BackupPasswordError(BackupError):
    """An encrypted archive needs a password and none / the wrong one was
    given. Separate so the UI can ask for the password and try again."""


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

    @property
    def encrypted(self) -> bool:
        return self.manifest.get("format") == FORMAT_ENCRYPTED


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

    # ── Password ──────────────────────────────────────────────────────────

    @staticmethod
    def has_password() -> bool:
        """Whether backups get encrypted. A stored password that can't be
        read still counts — create_backup() then fails loudly rather than
        falling back to writing unencrypted backups."""
        return backup_key.key_path().exists()

    @staticmethod
    def check_password(password: str) -> bool:
        """Whether `password` is the one stored on this PC."""
        try:
            stored = backup_key.load()
        except backup_key.BackupKeyError:
            return False
        return stored is not None and hmac.compare_digest(
            _normalize(stored).encode("utf-8"), _normalize(password).encode("utf-8"))

    @staticmethod
    def set_password(new_password: str, current_password: str = None):
        """Set or change the backup password. Changing it needs the current
        one — admin mode alone shouldn't be enough to lock the owner out of
        future backups. Only backups made from now on use the new password;
        older ones still open with the one they were made with."""
        if len(new_password) < MIN_PASSWORD_LENGTH:
            raise BackupError(f"The password must be at least {MIN_PASSWORD_LENGTH} characters.")
        if BackupService.has_password():
            try:
                stored = backup_key.load()
            except backup_key.BackupKeyError:
                stored = None  # unreadable: the only way out is setting a new one
                logger.warning("Backup password replaced without checking the old one: "
                               "the stored one can't be read")
            if stored is not None and not BackupService.check_password(current_password or ""):
                raise BackupPasswordError("The current backup password is wrong.")
        backup_key.save(new_password)

    # ── Creating ──────────────────────────────────────────────────────────

    @staticmethod
    def create_backup(kind: str, destinations: list[Path], db_path=None,
                      password=STORED_PASSWORD) -> BackupResult:
        """Snapshot the DB and write a verified archive into each destination,
        encrypted if a password is set (or given; None = unencrypted).

        A destination that fails (USB stick missing, disk full...) is logged
        and reported in the result's `failures`; the others still get their
        copy. Raises BackupError if the snapshot itself fails, the stored
        password can't be read, or no destination could be written."""
        if kind not in KINDS:
            raise ValueError(f"Unknown backup kind {kind!r}")
        db_path = Path(db_path or database.DB_PATH)
        if password is STORED_PASSWORD:
            try:
                password = backup_key.load()
            except backup_key.BackupKeyError as e:
                logger.error("Backup (%s) not taken: %s", kind, e)
                raise BackupError(str(e)) from e
        if password is None:
            logger.warning("Backup (%s) is not encrypted: no backup password is set", kind)

        with _lock:
            if not db_path.is_file():
                raise BackupError(f"Database not found: {db_path}")
            created_at = datetime.now()
            with tempfile.TemporaryDirectory(prefix="superpos-backup-") as tmp:
                snapshot = Path(tmp) / DB_MEMBER
                try:
                    _snapshot(db_path, snapshot)
                    if password is None:
                        manifest = _plain_manifest(snapshot, kind, created_at)
                        payload, member = snapshot, DB_MEMBER
                    else:
                        payload = Path(tmp) / ENC_MEMBER
                        manifest = _encrypt(snapshot, payload, password, kind, created_at)
                        member = ENC_MEMBER
                except sqlite3.Error as e:
                    logger.exception("Backup (%s): snapshot of %s failed", kind, db_path)
                    raise BackupError(f"Could not read the database: {e}") from e

                result = BackupResult(manifest=manifest)
                name = archive_name(created_at, kind)
                for dest in destinations:
                    dest = Path(dest)
                    try:
                        path = _write_archive(payload, member, manifest, dest, name, password)
                    except (OSError, BackupError) as e:
                        logger.error("Backup (%s) to %s failed: %s", kind, dest, e)
                        result.failures[str(dest)] = str(e)
                        continue
                    result.archives.append(path)
                    logger.info("Backup (%s, %s) written: %s (%d bytes)", kind,
                                "encrypted" if password else "NOT encrypted",
                                path, path.stat().st_size)
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
    def read_manifest(path) -> dict:
        """The archive's manifest, without checking the database inside or
        needing its password — e.g. to see whether it's encrypted."""
        try:
            with zipfile.ZipFile(path) as zf:
                return _read_manifest(zf)
        except BackupError:
            raise
        except (zipfile.BadZipFile, OSError, ValueError, KeyError) as e:
            raise BackupError(f"Backup file is damaged or unreadable: {e}") from e

    @staticmethod
    def is_encrypted(manifest: dict) -> bool:
        return manifest.get("format") == FORMAT_ENCRYPTED

    @staticmethod
    def verify_archive(path, password: str = None) -> dict:
        """Check an archive end to end, without touching the live DB: it's a
        readable zip of ours, the database decrypts (GCM tag) / matches its
        hash, and passes SQLite's integrity check. Returns the manifest with
        `row_counts` read from the database itself. Raises
        BackupPasswordError for a missing or wrong password, BackupError
        for anything else."""
        with tempfile.TemporaryDirectory(prefix="superpos-verify-") as tmp:
            return _extract_verified(Path(path), Path(tmp) / DB_MEMBER, password)

    @staticmethod
    def restore_warnings(manifest: dict, db_path=None) -> list[str]:
        """Things the user must know before replacing the current data with
        this backup — both can cause numbers to be issued twice. Needs the
        `row_counts` that verify_archive() fills in."""
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
    def restore_backup(archive, destinations: list[Path], db_path=None, engine=None,
                       password: str = None) -> BackupResult:
        """Replace the live DB's contents with the archive's snapshot.
        `password` is the archive's own (typed by the user), needed only if
        it's encrypted.

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
        with _lock, tempfile.TemporaryDirectory(prefix="superpos-restore-") as tmp:
            candidate = Path(tmp) / DB_MEMBER
            manifest = _extract_verified(archive, candidate, password)
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

            if restored != manifest["row_counts"]:
                # Integrity is fine, so the data is usable, but not what was
                # just verified — keep a trace of it.
                logger.error("Restored row counts %s differ from the backup's %s",
                             restored, manifest["row_counts"])
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
        missing = REQUIRED_TABLES - set(_row_counts(dst))
    if missing:
        raise BackupError(f"Not a SuperPOS database (missing tables: {', '.join(sorted(missing))})")


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


def _base_manifest(kind: str, created_at: datetime, db_size: int) -> dict:
    return {
        "app": "SuperPOS",
        "kind": kind,
        "created_at": created_at.isoformat(timespec="seconds"),
        "db_size": db_size,
    }


def _plain_manifest(snapshot: Path, kind: str, created_at: datetime) -> dict:
    with closing(sqlite3.connect(snapshot)) as conn:
        row_counts = _row_counts(conn)
    return {
        "format": FORMAT_PLAIN,
        **_base_manifest(kind, created_at, snapshot.stat().st_size),
        "host": platform.node(),
        "sqlite_version": sqlite3.sqlite_version,
        "db_sha256": _sha256(snapshot),
        "row_counts": row_counts,
    }


# ── Encryption ───────────────────────────────────────────────────────────

def _normalize(password: str) -> str:
    """The same password typed on another keyboard/OS can arrive as other
    Unicode code points (é as one or two); NFC makes them the same key."""
    return unicodedata.normalize("NFC", password)


def _derive_key(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(_normalize(password).encode("utf-8"), salt=salt,
                          n=n, r=r, p=p, maxmem=_SCRYPT_MAXMEM, dklen=32)


def _aad(manifest: dict) -> bytes:
    """The manifest, canonically serialized, is authenticated along with the
    ciphertext: editing its kind/date (or any KDF parameter) breaks the tag."""
    return json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _encrypt(snapshot: Path, out: Path, password: str, kind: str, created_at: datetime) -> dict:
    """Compress then encrypt `snapshot` into `out` (encrypted data doesn't
    compress, so it has to happen first). Returns the manifest. Holds the
    DB in memory a few times over — fine at the sizes this DB reaches."""
    salt, nonce = os.urandom(16), os.urandom(12)
    manifest = {
        "format": FORMAT_ENCRYPTED,
        **_base_manifest(kind, created_at, snapshot.stat().st_size),
        "encryption": {
            "cipher": "AES-256-GCM",
            "compression": "zlib",
            "kdf": "scrypt",
            "n": _SCRYPT_N, "r": _SCRYPT_R, "p": _SCRYPT_P,
            "salt": base64.b64encode(salt).decode("ascii"),
            "nonce": base64.b64encode(nonce).decode("ascii"),
        },
    }
    key = _derive_key(password, salt, _SCRYPT_N, _SCRYPT_R, _SCRYPT_P)
    ciphertext = AESGCM(key).encrypt(nonce, zlib.compress(snapshot.read_bytes(), 6), _aad(manifest))
    out.write_bytes(ciphertext)
    return manifest


def _decrypt(ciphertext: bytes, manifest: dict, password: str) -> bytes:
    enc = manifest.get("encryption") or {}
    if enc.get("cipher") != "AES-256-GCM" or enc.get("kdf") != "scrypt" \
            or enc.get("compression") != "zlib":
        raise BackupError("Backup uses an unknown encryption scheme.")
    try:
        salt, nonce = base64.b64decode(enc["salt"]), base64.b64decode(enc["nonce"])
        n, r, p = int(enc["n"]), int(enc["r"]), int(enc["p"])
    except (KeyError, ValueError, TypeError) as e:
        raise BackupError(f"Backup manifest is damaged: {e}") from e
    if not (2 ** 10 <= n <= 2 ** 20 and 1 <= r <= 32 and 1 <= p <= 16):
        raise BackupError("Backup manifest is damaged (encryption parameters).")
    key = _derive_key(password, salt, n, r, p)
    try:
        compressed = AESGCM(key).decrypt(nonce, ciphertext, _aad(manifest))
    except InvalidTag:
        # Wrong password and tampered/damaged data are indistinguishable
        # here, by design of authenticated encryption.
        raise BackupPasswordError(
            "Wrong password, or the backup file is damaged.") from None
    try:
        return zlib.decompress(compressed)
    except zlib.error as e:
        raise BackupError(f"Backup file is damaged: {e}") from e


# ── Archive I/O ──────────────────────────────────────────────────────────

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


def _write_archive(payload: Path, member: str, manifest: dict, dest_dir: Path,
                   name: str, password: str | None) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    needed = manifest["db_size"] * 2  # generous: the archive is usually far smaller
    if shutil.disk_usage(dest_dir).free < needed:
        raise BackupError(f"Not enough free space in {dest_dir}")

    final = _unique_path(dest_dir / name)
    partial = final.with_name(final.name + PARTIAL_SUFFIX)
    # Encrypted data is already compressed (and incompressible).
    compression = zipfile.ZIP_STORED if member == ENC_MEMBER else zipfile.ZIP_DEFLATED
    try:
        with open(partial, "wb") as fh:
            with zipfile.ZipFile(fh, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(MANIFEST_MEMBER, json.dumps(manifest, indent=2))
                zf.write(payload, member, compress_type=compression)
            fh.flush()
            os.fsync(fh.fileno())
        _verify_zip(partial, password=password)  # read back what actually reached the disk
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


def _read_manifest(zf: zipfile.ZipFile) -> dict:
    names = set(zf.namelist())
    if MANIFEST_MEMBER not in names:
        raise BackupError("Not a SuperPOS backup (manifest missing).")
    manifest = json.loads(zf.read(MANIFEST_MEMBER))
    if not isinstance(manifest, dict) or manifest.get("app") != "SuperPOS":
        raise BackupError("Not a SuperPOS backup.")
    fmt = manifest.get("format")
    if isinstance(fmt, int) and fmt > FORMAT_ENCRYPTED:
        raise BackupError("This backup was made by a newer version of the POS.")
    member = {FORMAT_PLAIN: DB_MEMBER, FORMAT_ENCRYPTED: ENC_MEMBER}.get(fmt)
    if member is None or member not in names:
        raise BackupError("Not a SuperPOS backup (database missing).")
    return manifest


def _verify_zip(path: Path, extract_to: Path = None, password: str = None) -> dict:
    """Zip readable, manifest ours, and the stored DB authentic: decrypts
    under the password (GCM tag) or matches its SHA-256 (zipfile also checks
    each member's CRC while reading). Optionally writes the DB out to
    `extract_to`."""
    try:
        with zipfile.ZipFile(path) as zf:
            manifest = _read_manifest(zf)
            if manifest["format"] == FORMAT_ENCRYPTED:
                if not password:
                    raise BackupPasswordError("This backup is encrypted: enter its password.")
                db = _decrypt(zf.read(ENC_MEMBER), manifest, password)
                if len(db) != manifest.get("db_size"):
                    raise BackupError("Backup file is damaged: unexpected database size.")
                if extract_to:
                    extract_to.write_bytes(db)
                return manifest
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
    except (zipfile.BadZipFile, OSError, ValueError, KeyError, EOFError) as e:
        raise BackupError(f"Backup file is damaged or unreadable: {e}") from e
    if h.hexdigest() != manifest.get("db_sha256"):
        raise BackupError("Backup file is damaged: the database doesn't match its checksum.")
    return manifest


def _extract_verified(archive: Path, dest: Path, password: str = None) -> dict:
    """_verify_zip() plus opening the extracted DB: integrity check and the
    tables a SuperPOS DB must have. The returned manifest's `row_counts` come
    from the DB itself (an encrypted archive's manifest has none)."""
    if not archive.is_file():
        raise BackupError(f"Backup file not found: {archive}")
    manifest = dict(_verify_zip(archive, extract_to=dest, password=password))
    try:
        with closing(sqlite3.connect(dest)) as conn:
            _check_integrity(conn)
            row_counts = _row_counts(conn)
    except sqlite3.Error as e:
        raise BackupError(f"Backup database can't be opened: {e}") from e
    missing = REQUIRED_TABLES - row_counts.keys()
    if missing:
        raise BackupError(f"Not a SuperPOS database (missing tables: {', '.join(sorted(missing))})")
    manifest["row_counts"] = row_counts
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
