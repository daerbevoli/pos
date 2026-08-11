"""
Tests for the small reusable Qt widgets in app.utils.utils:
TicketTable, TicketTab, FunctionButton, CategoryButton, TapToDismissOverlay.
"""
from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QWidget

from app.utils.utils import (
    TicketTable, TicketTab, FunctionButton, CategoryButton, TapToDismissOverlay,
)


def _key_event(key, text="", modifiers=Qt.KeyboardModifier.NoModifier):
    return QKeyEvent(QEvent.Type.KeyPress, key, modifiers, text)


# ── TicketTable ──────────────────────────────────────────────────────────

def test_ticket_table_backspace_emits_signal(qtbot):
    table = TicketTable(1, 1)
    qtbot.addWidget(table)
    received = []
    table.backspace_pressed.connect(lambda: received.append(True))

    table.keyPressEvent(_key_event(Qt.Key.Key_Backspace))
    table.keyPressEvent(_key_event(Qt.Key.Key_Delete))

    assert received == [True, True]


def test_ticket_table_enter_emits_signal(qtbot):
    table = TicketTable(1, 1)
    qtbot.addWidget(table)
    received = []
    table.enter_pressed.connect(lambda: received.append(True))

    table.keyPressEvent(_key_event(Qt.Key.Key_Return))
    table.keyPressEvent(_key_event(Qt.Key.Key_Enter))

    assert received == [True, True]


def test_ticket_table_digit_emits_text_entered(qtbot):
    table = TicketTable(1, 1)
    qtbot.addWidget(table)
    received = []
    table.text_entered.connect(received.append)

    table.keyPressEvent(_key_event(Qt.Key.Key_5, "5"))

    assert received == ["5"]


def test_ticket_table_decimal_comma_and_minus_emit_text_entered(qtbot):
    table = TicketTable(1, 1)
    qtbot.addWidget(table)
    received = []
    table.text_entered.connect(received.append)

    table.keyPressEvent(_key_event(Qt.Key.Key_Period, "."))
    table.keyPressEvent(_key_event(Qt.Key.Key_Comma, ","))
    table.keyPressEvent(_key_event(Qt.Key.Key_Minus, "-"))

    assert received == [".", ",", "-"]


def test_ticket_table_letter_key_does_not_emit(qtbot):
    table = TicketTable(1, 1)
    qtbot.addWidget(table)
    received = []
    table.text_entered.connect(received.append)

    table.keyPressEvent(_key_event(Qt.Key.Key_A, "a"))

    assert received == []


def test_ticket_table_ctrl_modifier_suppresses_text_entered(qtbot):
    table = TicketTable(1, 1)
    qtbot.addWidget(table)
    received = []
    table.text_entered.connect(received.append)

    table.keyPressEvent(_key_event(Qt.Key.Key_5, "5", Qt.KeyboardModifier.ControlModifier))

    assert received == []


def test_ticket_table_alt_modifier_suppresses_text_entered(qtbot):
    table = TicketTable(1, 1)
    qtbot.addWidget(table)
    received = []
    table.text_entered.connect(received.append)

    table.keyPressEvent(_key_event(Qt.Key.Key_5, "5", Qt.KeyboardModifier.AltModifier))

    assert received == []


def test_ticket_table_empty_text_does_not_emit(qtbot):
    """Modifier keys alone (e.g. a bare Shift press) carry no text."""
    table = TicketTable(1, 1)
    qtbot.addWidget(table)
    received = []
    table.text_entered.connect(received.append)

    table.keyPressEvent(_key_event(Qt.Key.Key_Shift, ""))

    assert received == []


# ── TicketTab ────────────────────────────────────────────────────────────

def test_ticket_tab_initial_label_has_no_amount(qtbot):
    tab = TicketTab(3)
    qtbot.addWidget(tab)
    assert tab.text() == "V 3"
    assert tab.isCheckable()
    assert tab.index == 3


def test_ticket_tab_set_label_with_amount(qtbot):
    tab = TicketTab(1)
    qtbot.addWidget(tab)
    tab._set_label("V 1", "12.50")
    assert tab.text() == "V 1\n12.50"


def test_ticket_tab_set_label_without_amount_omits_newline(qtbot):
    tab = TicketTab(1)
    qtbot.addWidget(tab)
    tab._set_label("V 1", "")
    assert tab.text() == "V 1"


# ── FunctionButton / CategoryButton ──────────────────────────────────────

def test_function_button_sets_object_name_and_focus_policy(qtbot):
    btn = FunctionButton("Cash", "cashBtn")
    qtbot.addWidget(btn)
    assert btn.objectName() == "cashBtn"
    assert btn.text() == "Cash"
    assert btn.focusPolicy() == Qt.FocusPolicy.NoFocus


def test_function_button_default_role():
    btn = FunctionButton("X")
    assert btn.objectName() == "func"


def test_category_button_sets_object_name_and_focus_policy(qtbot):
    btn = CategoryButton("Bakery", "categoryBtn")
    qtbot.addWidget(btn)
    assert btn.objectName() == "categoryBtn"
    assert btn.text() == "Bakery"
    assert btn.focusPolicy() == Qt.FocusPolicy.NoFocus


# ── TapToDismissOverlay ──────────────────────────────────────────────────

def test_overlay_hidden_initially(qtbot):
    parent = QWidget()
    qtbot.addWidget(parent)
    overlay = TapToDismissOverlay(parent)
    assert overlay.isVisible() is False


def test_overlay_show_message_sets_text_and_shows(qtbot):
    parent = QWidget()
    parent.resize(400, 300)
    qtbot.addWidget(parent)
    parent.show()
    overlay = TapToDismissOverlay(parent)

    overlay.show_message("Something happened", title="Oops", kind="error")

    assert overlay.title_label.text() == "Oops"
    assert not overlay.title_label.isHidden()
    assert overlay.message_label.text() == "Something happened"
    assert overlay.card.property("kind") == "error"
    assert not overlay.isHidden()


def test_overlay_show_message_without_title_hides_title_label(qtbot):
    parent = QWidget()
    parent.resize(400, 300)
    qtbot.addWidget(parent)
    overlay = TapToDismissOverlay(parent)

    overlay.show_message("Just a message")

    assert overlay.title_label.isVisible() is False


def test_overlay_mouse_press_dismisses(qtbot):
    parent = QWidget()
    parent.resize(400, 300)
    qtbot.addWidget(parent)
    parent.show()
    overlay = TapToDismissOverlay(parent)
    overlay.show_message("msg")
    assert not overlay.isHidden()

    from PyQt6.QtGui import QMouseEvent
    from PyQt6.QtCore import QPointF, Qt as QtCore_Qt

    event = QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(5, 5), QtCore_Qt.MouseButton.LeftButton,
        QtCore_Qt.MouseButton.LeftButton, QtCore_Qt.KeyboardModifier.NoModifier,
    )
    overlay.mousePressEvent(event)

    assert overlay.isHidden()


def test_overlay_resize_event_tracks_parent_size(qtbot):
    from PyQt6.QtGui import QResizeEvent
    from PyQt6.QtCore import QSize

    parent = QWidget()
    parent.resize(500, 400)
    qtbot.addWidget(parent)
    overlay = TapToDismissOverlay(parent)

    parent.resize(800, 600)
    overlay.resizeEvent(QResizeEvent(QSize(800, 600), QSize(500, 400)))

    assert overlay.geometry() == parent.rect()
