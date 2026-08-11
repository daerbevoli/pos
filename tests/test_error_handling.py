"""Tests for app.utils.error_handling: logging setup and global excepthook."""
import logging
import sys

import pytest

from app.utils import error_handling


@pytest.fixture(autouse=True)
def _restore_root_logger_and_excepthook():
    """setup_logging()/install_excepthook() mutate process-global state
    (root logger handlers, sys.excepthook) — restore both after each test
    so tests don't bleed into each other or the rest of the suite."""
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level
    original_excepthook = sys.excepthook
    yield
    root.handlers = original_handlers
    root.level = original_level
    sys.excepthook = original_excepthook


def test_setup_logging_creates_log_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    error_handling.setup_logging()

    log_file = tmp_path / "logs" / "pos.log"
    assert log_file.parent.is_dir()
    # RotatingFileHandler creates the file lazily on first emit, but the dir must exist.
    logging.getLogger("pos").info("hello")
    assert log_file.exists()


def test_setup_logging_sets_root_level_info(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    error_handling.setup_logging()
    assert logging.getLogger().level == logging.INFO


def test_install_excepthook_passes_through_keyboard_interrupt(monkeypatch):
    calls = []
    monkeypatch.setattr(sys, "__excepthook__", lambda *a: calls.append(a))

    error_handling.install_excepthook()

    exc = KeyboardInterrupt()
    sys.excepthook(KeyboardInterrupt, exc, None)

    assert len(calls) == 1
    assert calls[0][0] is KeyboardInterrupt


def test_install_excepthook_logs_and_shows_dialog(monkeypatch):
    logged = []
    monkeypatch.setattr(error_handling.logger, "critical", lambda *a, **kw: logged.append((a, kw)))

    shown = []
    monkeypatch.setattr(
        error_handling.QMessageBox, "critical",
        staticmethod(lambda *a, **kw: shown.append((a, kw)))
    )

    error_handling.install_excepthook()

    try:
        raise ValueError("boom")
    except ValueError:
        exc_type, exc_value, exc_tb = sys.exc_info()
        sys.excepthook(exc_type, exc_value, exc_tb)

    assert len(logged) == 1
    assert logged[0][1]["exc_info"] == (exc_type, exc_value, exc_tb)
    assert len(shown) == 1
    assert "ValueError: boom" in shown[0][0][-1]


def test_install_excepthook_does_not_call_dunder_excepthook_for_normal_exceptions(monkeypatch):
    calls = []
    monkeypatch.setattr(sys, "__excepthook__", lambda *a: calls.append(a))
    monkeypatch.setattr(error_handling.logger, "critical", lambda *a, **kw: None)
    monkeypatch.setattr(error_handling.QMessageBox, "critical", staticmethod(lambda *a, **kw: None))

    error_handling.install_excepthook()
    sys.excepthook(ValueError, ValueError("x"), None)

    assert calls == []
