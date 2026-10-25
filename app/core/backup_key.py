"""
Backup password store.

Daily and pre-Z backups are taken automatically, so the password that
encrypts them has to be available without anyone typing it. It's kept in
`backup_password.bin` next to the DB, never in the DB itself: a password
inside the DB would end up inside every backup, and restoring an old backup
would silently bring back an old password.

On Windows the file holds a DPAPI blob (CryptProtectData): only the same
Windows user on the same PC can decrypt it, so a copy of the SuperPOS
folder is useless elsewhere. Other platforms (development only) have no
DPAPI; the file then holds the plain password, readable only by its owner.
"""
import logging
import os
import sys
from pathlib import Path

import app.core.database as database

logger = logging.getLogger(__name__)

KEY_FILE_NAME = "backup_password.bin"
# Ties the DPAPI blob to this purpose: another app running as the same user
# can't unprotect it without also knowing this value.
_ENTROPY = b"SuperPOS backup password v1"
_CRYPTPROTECT_UI_FORBIDDEN = 0x01


class BackupKeyError(Exception):
    """The stored password exists but can't be read back (e.g. the Windows
    profile changed). Never treated as "no password": that would silently
    turn encryption off."""


def key_path() -> Path:
    return Path(database.DB_PATH).parent / KEY_FILE_NAME


def load() -> str | None:
    """The stored backup password, or None if none was ever set."""
    path = key_path()
    try:
        blob = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as e:
        raise BackupKeyError(f"Backup password file can't be read: {e}") from e
    try:
        return _unprotect(blob).decode("utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise BackupKeyError(
            "The stored backup password can't be decrypted on this PC / Windows user. "
            "Set the backup password again.") from e


def save(password: str):
    """Store `password`, replacing any previous one atomically."""
    path = key_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as f:
        f.write(_protect(password.encode("utf-8")))
        f.flush()
        os.fsync(f.fileno())
    if sys.platform != "win32":
        os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    logger.info("Backup password set")


# ── DPAPI ────────────────────────────────────────────────────────────────

def _protect(data: bytes) -> bytes:
    if sys.platform != "win32":
        return data
    return _dpapi("CryptProtectData", data)


def _unprotect(blob: bytes) -> bytes:
    if sys.platform != "win32":
        return blob
    return _dpapi("CryptUnprotectData", blob)


def _dpapi(func_name: str, data: bytes) -> bytes:
    import ctypes
    from ctypes import wintypes

    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def to_blob(raw: bytes):
        buf = ctypes.create_string_buffer(raw, len(raw))
        return DataBlob(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    data_in, _keep_in = to_blob(data)
    entropy, _keep_entropy = to_blob(_ENTROPY)
    data_out = DataBlob()
    # Both functions share this signature: (in, description, entropy,
    # reserved, prompt, flags, out).
    ok = getattr(crypt32, func_name)(
        ctypes.byref(data_in), None, ctypes.byref(entropy), None, None,
        _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(data_out))
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(data_out.pbData, data_out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(data_out.pbData, ctypes.c_void_p))
