import pytest
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication, QLineEdit, QVBoxLayout, QWidget

from app.utils.scanner import ScanInterceptor
from app.utils.utils import TicketTable


@pytest.fixture
def interceptor(qapp):
    f = ScanInterceptor()
    qapp.installEventFilter(f)
    yield f
    qapp.removeEventFilter(f)


@pytest.fixture
def window(qtbot):
    w = QWidget()
    lay = QVBoxLayout(w)
    w.table = TicketTable()
    w.edit = QLineEdit()
    lay.addWidget(w.table)
    lay.addWidget(w.edit)
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    w.activateWindow()
    return w


def _key(widget, text, key=Qt.Key.Key_unknown):
    """Sends a key press the way the app's event loop would (through
    QApplication.notify, so application event filters run)."""
    QApplication.sendEvent(widget, QKeyEvent(
        QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier, text))


def _type(widget, s):
    for ch in s:
        _key(widget, ch)


def _focus(qtbot, widget):
    widget.setFocus()
    qtbot.waitUntil(lambda: QApplication.focusWidget() is widget)


def test_scan_on_ticket_table_emits_code(interceptor, window, qtbot):
    _focus(qtbot, window.table)
    scans, typed = [], []
    window.table.barcode_scanned.connect(scans.append)
    window.table.text_entered.connect(typed.append)
    _type(window.table, "^<5410000000012^>")
    _type(window.table, "7")
    assert scans == ["5410000000012"]
    assert typed == ["7"]


def test_scan_into_line_edit_strips_markers_and_presses_enter(interceptor, window, qtbot):
    _focus(qtbot, window.edit)
    entered = []
    window.edit.returnPressed.connect(lambda: entered.append(window.edit.text()))
    _type(window.edit, "^<5410000000012^>")
    assert window.edit.text() == "5410000000012"
    assert entered == ["5410000000012"]


def test_azerty_dead_caret(interceptor, window, qtbot):
    """Belgian AZERTY: '^' arrives as a text-less dead-key event, the next
    key carries '<' (or '^<' combined)."""
    _focus(qtbot, window.table)
    scans = []
    window.table.barcode_scanned.connect(scans.append)
    _key(window.table, "", Qt.Key.Key_Dead_Circumflex)
    _key(window.table, "<")
    _type(window.table, "123")
    _key(window.table, "", Qt.Key.Key_Dead_Circumflex)
    _key(window.table, ">")
    _key(window.table, "", Qt.Key.Key_Dead_Circumflex)
    _key(window.table, "^<")
    _type(window.table, "456")
    _key(window.table, "", Qt.Key.Key_Dead_Circumflex)
    _key(window.table, "^>")
    assert scans == ["123", "456"]


def test_manual_caret_is_not_lost(interceptor, window, qtbot):
    _focus(qtbot, window.edit)
    _type(window.edit, "a^b")
    assert window.edit.text() == "a^b"
