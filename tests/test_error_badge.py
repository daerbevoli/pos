"""
Tests for app.ui.widgets.error_badge.ErrorBadge. Each test feeds its own
QtLogHandler, so records logged by other tests can't leak into the count.
"""
import logging

import pytest

from app.ui.widgets.error_badge import ErrorBadge
from app.utils.error_handling import QtLogHandler


@pytest.fixture
def handler():
    h = QtLogHandler()
    h.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    return h


def _log(handler, level, msg):
    handler.handle(logging.LogRecord("test", level, __file__, 1, msg, None, None))


def test_hidden_until_an_error_is_logged(qtbot, handler):
    badge = ErrorBadge(handler)
    qtbot.addWidget(badge)
    _log(handler, logging.INFO, "sale completed")
    _log(handler, logging.WARNING, "shown to user")
    assert badge.isHidden() and badge.count == 0

    _log(handler, logging.ERROR, "printer failed")
    _log(handler, logging.CRITICAL, "unhandled exception")
    assert not badge.isHidden()
    assert badge.count == 2
    assert badge.text() == "⚠ 2 errors"
    assert "unhandled exception" in badge.toolTip()


def test_counts_errors_logged_before_it_was_built(qtbot, handler):
    _log(handler, logging.ERROR, "DB error at startup")
    badge = ErrorBadge(handler)
    qtbot.addWidget(badge)
    assert badge.count == 1 and badge.text() == "⚠ 1 error"


def test_acknowledge_hides_and_resets(qtbot, handler):
    badge = ErrorBadge(handler)
    qtbot.addWidget(badge)
    _log(handler, logging.ERROR, "ERP send failed")
    badge.acknowledge()
    assert badge.isHidden() and badge.count == 0
    _log(handler, logging.ERROR, "ERP send failed again")
    assert badge.count == 1
