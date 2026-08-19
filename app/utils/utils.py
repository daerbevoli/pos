from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QPushButton, QSizePolicy, QWidget, QVBoxLayout, QFrame, QLabel, QTableWidget

from app.constants import (
    BUTTON_HEIGHT,
    BUTTON_HEIGHT_COMPACT,
    LIST_PANEL_MAX_WIDTH,
    LIST_PANEL_MIN_WIDTH,
    MARGIN_NONE,
    SPACING_MD,
)


class TicketTable(QTableWidget):
    """The scanner should be programmed to wrap every scan in SCAN_MARKER
    (e.g. 'A12345678A'), a character no one would type manually. That lets
    us tell a scan apart from typed digits with certainty instead of
    guessing from length."""

    SCAN_MARKER = "A"

    backspace_pressed = pyqtSignal()
    text_entered = pyqtSignal(str)
    enter_pressed = pyqtSignal()
    barcode_scanned = pyqtSignal(str)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._scanning = False
        self._scan_buffer = ""

    def keyPressEvent(self, event):
        key = event.key()
        text = event.text()
        mods = event.modifiers()

        if text == self.SCAN_MARKER and not self._scanning:
            self._scanning = True
            self._scan_buffer = ""
            return

        if self._scanning:
            if text == self.SCAN_MARKER:
                self._scanning = False
                self.barcode_scanned.emit(self._scan_buffer)
                self._scan_buffer = ""
            else:
                self._scan_buffer += text
            return

        if key in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
            self.backspace_pressed.emit()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.enter_pressed.emit()
        elif (text and (text.isdigit() or text in ".,-")
              and not mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)):
            self.text_entered.emit(text)
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        # Clicking empty space below the rows would otherwise clear the
        # current selection; ignore that so the last selected row stays
        # highlighted.
        if self.itemAt(event.position().toPoint()) is None:
            return
        super().mousePressEvent(event)

class TicketTab(QPushButton):
    """One of the V1 / V2 / V3 sale-slot tabs along the top."""
    def __init__(self, index: int):
        super().__init__()
        self.index = index
        self.setObjectName("ticketTab")
        self.setCheckable(True)
        self.setMinimumHeight(BUTTON_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._set_label(f"V {index}", "")

    def _set_label(self, title: str, amount: str):
        text = f"{title}\n{amount}" if amount else title
        self.setText(text)

class FunctionButton(QPushButton):
    """A square-ish function key in the right-hand control grid."""
    def __init__(self, label: str, role: str = "func"):
        super().__init__(label)
        self.setObjectName(role)
        self.setMinimumHeight(BUTTON_HEIGHT_COMPACT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)



class CategoryButton(QPushButton):
    """A colored department / category / product key in the bottom grid."""
    def __init__(self, label: str, role: str):
        super().__init__(label)
        self.setObjectName(role)
        self.setMinimumHeight(BUTTON_HEIGHT_COMPACT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)



class TapToDismissOverlay(QWidget):
    """
    Full-screen modal-style overlay: dims the background, shows a centered
    message card, and blocks all other input. Disappears when clicked
    anywhere on it (including the card itself).
    """
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("tapDismissOverlay")
        # Always cover the full parent, regardless of when shown
        self.setGeometry(parent.rect())
        self.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(*MARGIN_NONE)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.card = QFrame(self)
        self.card.setObjectName("tapDismissCard")
        self.card.setMinimumWidth(LIST_PANEL_MIN_WIDTH)
        self.card.setMaximumWidth(LIST_PANEL_MAX_WIDTH)

        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(28, 24, 28, 24)
        card_layout.setSpacing(SPACING_MD)

        self.message_label = QLabel("")
        self.message_label.setObjectName("tapDismissMessage")
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message_label.setWordWrap(True)

        card_layout.addWidget(self.message_label)

        layout.addWidget(self.card)

    def show_message(self, message: str, kind: str = "info"):
        """kind: 'info' | 'error' — controls the card's accent color."""
        self.message_label.setText(message)
        for widget in (self.card, self.message_label):
            widget.setProperty("kind", kind)
            widget.style().unpolish(widget)
            widget.style().polish(widget)

        self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.show()
        self.grabKeyboard()

    def resizeEvent(self, event):
        # Keep covering the parent if the window is resized while visible
        if self.parentWidget():
            self.setGeometry(self.parentWidget().rect())
        super().resizeEvent(event)

    def mousePressEvent(self, event):
        # Tap anywhere — including the card — dismisses it
        self.hide()

    def hideEvent(self, event):
        # Release regardless of how the overlay was hidden, so a stray hide()
        # call elsewhere can never leave the keyboard grabbed permanently.
        self.releaseKeyboard()
        super().hideEvent(event)
