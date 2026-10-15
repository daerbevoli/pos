"""Tests for app.utils.error_handling: logging setup and global excepthook."""
import logging
import logging.handlers
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
    error_handling.pause_logging(False)
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


def test_setup_logging_file_gets_debug_panel_gets_info(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    error_handling.setup_logging()
    root = logging.getLogger()
    file_handler = next(h for h in root.handlers
                        if isinstance(h, logging.handlers.RotatingFileHandler))
    assert root.level == logging.DEBUG
    assert file_handler.level == logging.DEBUG
    assert error_handling.qt_log_handler.level == logging.INFO


def _file_lines(tmp_path):
    for h in logging.getLogger().handlers:
        h.flush()
    return (tmp_path / "logs" / "pos.log").read_text().splitlines()


def test_pause_logging_keeps_only_warnings_and_errors(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    error_handling.setup_logging()
    panel = []
    error_handling.qt_log_handler.emitter.record.connect(lambda line, lvl: panel.append(line))
    log = logging.getLogger("app.core.sales_service")

    error_handling.pause_logging(True)
    log.debug("Stock move for RF-0001")
    log.info("Refund RF-0001 completed")
    log.warning("stock went negative during refund")
    log.error("printer failed during refund")
    error_handling.pause_logging(False)
    log.info("Sale S-0002 completed")

    for lines in (_file_lines(tmp_path), panel):
        text = "\n".join(lines)
        assert "RF-0001" not in text
        assert "negative during refund" in text and "printer failed during refund" in text
        assert "Logging paused" in text and "Logging resumed" in text
        assert "S-0002" in text


def test_pause_logging_repeated_state_logs_marker_once(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    error_handling.setup_logging()
    # rf_cn_mode_changed re-emits the same state on every V-tab switch.
    for _ in range(3):
        error_handling.pause_logging(False)
    error_handling.pause_logging(True)
    error_handling.pause_logging(True)
    error_handling.pause_logging(False)
    lines = _file_lines(tmp_path)
    assert sum("Logging paused" in l for l in lines) == 1
    assert sum("Logging resumed" in l for l in lines) == 1


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
