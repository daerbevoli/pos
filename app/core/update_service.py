"""
In-app updater: finds the newest GitHub Release, downloads its setup .exe
and runs it.

Only `v*` tags publish a release (see .github/workflows/build.yml), so a plain
push never reaches the shop. Downloads go to <db dir>/updates and are kept
there until installed: the cashier is only asked at a quiet moment (startup,
after a Z report), which may be days after the download. Installing runs the
Inno Setup installer silently; it closes the POS and starts the new version
(see installer/superpos.iss).
"""
import hashlib
import logging
import os
import re
import sys
from pathlib import Path

import requests

from app.__version__ import __version__
from app.core import database

logger = logging.getLogger(__name__)

LATEST_RELEASE_URL = "https://api.github.com/repos/daerbevoli/pos/releases/latest"
SETUP_NAME = re.compile(r"SuperPOS-(\d+\.\d+\.\d+)-setup\.exe")
INSTALL_ARGS = "/SILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS"


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(n) for n in text.removeprefix("v").split("."))


def enabled() -> bool:
    """Only the installed Windows build updates itself; `python main.py` never does."""
    return sys.platform == "win32" and getattr(sys, "frozen", False)


def updates_dir() -> Path:
    return Path(database.DB_PATH).parent / "updates"


def downloaded_update() -> Path | None:
    """The newest fully downloaded setup newer than this version, if any.
    Setups for this version or older are deleted: they are installed already."""
    newest = None
    for path in updates_dir().glob("SuperPOS-*-setup.exe"):
        m = SETUP_NAME.fullmatch(path.name)
        if not m:
            continue
        if _version(m.group(1)) <= _version(__version__):
            path.unlink(missing_ok=True)
        elif newest is None or _version(m.group(1)) > _version(SETUP_NAME.fullmatch(newest.name).group(1)):
            newest = path
    return newest


def fetch_update(progress=lambda fraction: None) -> Path | None:
    """Downloads the latest release's setup if it is newer than this version.
    Returns its path (also when it was already downloaded), or None when up to
    date. Raises on network errors or a corrupt download; `progress(0..1)` is
    called per chunk and may raise to abort."""
    res = requests.get(LATEST_RELEASE_URL, timeout=15,
                       headers={"Accept": "application/vnd.github+json"})
    res.raise_for_status()
    release = res.json()
    version = release["tag_name"].removeprefix("v")
    if _version(version) <= _version(__version__):
        return None

    name = f"SuperPOS-{version}-setup.exe"
    asset = next((a for a in release.get("assets", []) if a["name"] == name), None)
    if asset is None:
        raise RuntimeError(f"release {version} has no {name}")
    dest = updates_dir() / name
    if dest.exists():
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(".partial")
    sha256, done = hashlib.sha256(), 0
    try:
        with requests.get(asset["browser_download_url"], stream=True, timeout=30) as dl:
            dl.raise_for_status()
            with open(partial, "wb") as f:
                for chunk in dl.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
                    sha256.update(chunk)
                    done += len(chunk)
                    progress(done / asset["size"] if asset.get("size") else 0)
        if done != asset.get("size", done):
            raise RuntimeError(f"{name}: got {done} of {asset['size']} bytes")
        # GitHub publishes each asset's SHA-256; a mismatch means a broken download.
        digest = asset.get("digest")
        if digest and digest != f"sha256:{sha256.hexdigest()}":
            raise RuntimeError(f"{name}: checksum mismatch")
        os.replace(partial, dest)
    finally:
        partial.unlink(missing_ok=True)
    logger.info("Update %s downloaded to %s", version, dest)
    return dest


def install(setup: Path):
    """Starts the setup (asking for admin rights through UAC) and returns at
    once; the caller then quits the POS. Raises OSError if Windows refuses,
    e.g. when the UAC prompt is cancelled."""
    logger.info("Installing update %s", setup.name)
    # ShellExecute (not CreateProcess/QProcess): only it triggers the UAC prompt the admin-only setup needs.
    os.startfile(setup, "open", INSTALL_ARGS)
