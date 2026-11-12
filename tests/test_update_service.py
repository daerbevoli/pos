import hashlib

import pytest

from app.core import update_service

SETUP = b"fake setup bytes"


class _Response:
    def __init__(self, json=None, body=b""):
        self._json, self._body = json, body

    def raise_for_status(self):
        pass

    def json(self):
        return self._json

    def iter_content(self, chunk_size):
        yield self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def updates(monkeypatch, tmp_path):
    monkeypatch.setattr(update_service.database, "DB_PATH", str(tmp_path / "superpos.db"))
    monkeypatch.setattr(update_service, "__version__", "1.0.0")
    return tmp_path / "updates"


def _release(monkeypatch, tag, body=SETUP, digest=None):
    version = tag.removeprefix("v")
    asset = {
        "name": f"SuperPOS-{version}-setup.exe",
        "browser_download_url": "https://example.invalid/setup.exe",
        "size": len(body),
        "digest": digest or f"sha256:{hashlib.sha256(body).hexdigest()}",
    }
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        if url == update_service.LATEST_RELEASE_URL:
            return _Response(json={"tag_name": tag, "assets": [asset]})
        return _Response(body=body)

    monkeypatch.setattr(update_service.requests, "get", get)
    return calls


def test_up_to_date_downloads_nothing(monkeypatch, updates):
    calls = _release(monkeypatch, "v1.0.0")
    assert update_service.fetch_update() is None
    assert calls == [update_service.LATEST_RELEASE_URL]


def test_newer_release_is_downloaded_and_offered(monkeypatch, updates):
    _release(monkeypatch, "v1.0.10")  # 1.0.10 > 1.0.9: numeric, not text, comparison
    path = update_service.fetch_update()
    assert path.read_bytes() == SETUP
    assert update_service.downloaded_update() == path
    assert not list(updates.glob("*.partial"))


def test_checksum_mismatch_keeps_nothing(monkeypatch, updates):
    _release(monkeypatch, "v1.1.0", digest="sha256:" + "0" * 64)
    with pytest.raises(RuntimeError, match="checksum"):
        update_service.fetch_update()
    assert list(updates.iterdir()) == []
    assert update_service.downloaded_update() is None


def test_aborted_download_keeps_nothing(monkeypatch, updates):
    _release(monkeypatch, "v1.1.0")

    def abort(_fraction):
        raise InterruptedError

    with pytest.raises(InterruptedError):
        update_service.fetch_update(abort)
    assert list(updates.iterdir()) == []


def test_installed_setups_are_cleaned_up(updates):
    updates.mkdir()
    for v in ("0.9.0", "1.0.0", "1.2.0", "1.10.0"):
        (updates / f"SuperPOS-{v}-setup.exe").write_bytes(SETUP)
    assert update_service.downloaded_update().name == "SuperPOS-1.10.0-setup.exe"
    assert sorted(p.name for p in updates.iterdir()) == [
        "SuperPOS-1.10.0-setup.exe", "SuperPOS-1.2.0-setup.exe"]
