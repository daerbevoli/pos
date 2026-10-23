"""
Tests for app.ui.widgets.error_badge.ErrorBadge. Each test feeds its own
QtLogHandler, so records logged by other tests can't leak into the count.
"""
import logging

import pytest

from app.constants import ERROR_BADGE_WIDTH
from app.ui.widgets.error_badge import ErrorBadge
from app.utils.error_handling import QtLogHandler


@pytest.fixture
def handler():
    h = QtLogHandler()
    h.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    return h


def _log(handler, level, msg):
    handler.handle(logging.LogRecord("test", level, __file__, 1, msg, None, None))


def test_blank_until_an_error_is_logged(qtbot, handler):
    badge = ErrorBadge(handler)
    qtbot.addWidget(badge)
    _log(handler, logging.INFO, "sale completed")
    _log(handler, logging.WARNING, "shown to user")
    assert not badge.active and not badge.isEnabled() and badge.text() == ""
    assert badge.count == 0

    _log(handler, logging.ERROR, "printer failed")
    _log(handler, logging.CRITICAL, "unhandled exception")
    assert badge.active and badge.isEnabled()
    assert badge.count == 2
    assert badge.text() == "⚠ 2 errors"
    assert "unhandled exception" in badge.toolTip()


def test_counts_errors_logged_before_it_was_built(qtbot, handler):
    _log(handler, logging.ERROR, "DB error at startup")
    badge = ErrorBadge(handler)
    qtbot.addWidget(badge)
    assert badge.count == 1 and badge.text() == "⚠ 1 error"


def test_acknowledge_blanks_and_resets(qtbot, handler):
    badge = ErrorBadge(handler)
    qtbot.addWidget(badge)
    _log(handler, logging.ERROR, "ERP send failed")
    badge.acknowledge()
    assert not badge.active and badge.text() == "" and badge.count == 0
    _log(handler, logging.ERROR, "ERP send failed again")
    assert badge.count == 1


def test_width_is_fixed_whether_blank_or_showing_errors(qtbot, handler):
    badge = ErrorBadge(handler)
    qtbot.addWidget(badge)
    assert badge.minimumWidth() == badge.maximumWidth() == ERROR_BADGE_WIDTH
    for _ in range(12):
        _log(handler, logging.ERROR, "printer failed")
    assert badge.minimumWidth() == badge.maximumWidth() == ERROR_BADGE_WIDTH


def test_count_display_caps_at_99_plus(qtbot, handler):
    badge = ErrorBadge(handler)
    qtbot.addWidget(badge)
    for _ in range(99):
        _log(handler, logging.ERROR, "printer failed")
    assert badge.text() == "⚠ 99 errors"
    _log(handler, logging.ERROR, "printer failed")
    assert badge.count == 100 and badge.text() == "⚠ 99+ errors"
