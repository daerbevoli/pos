from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QPushButton, QSizePolicy, QWidget, QVBoxLayout, QFrame, QLabel, QTableWidget


class TicketTable(QTableWidget):
    backspace_pressed = pyqtSignal()
    text_entered = pyqtSignal(str)
    enter_pressed = pyqtSignal()

    def keyPressEvent(self, event):
        key = event.key()
        text = event.text()
        mods = event.modifiers()
        if key in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
            self.backspace_pressed.emit()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.enter_pressed.emit()
        elif (text and text.isprintable()
              and not mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)):
            self.text_entered.emit(text)
        else:
            super().keyPressEvent(event)

class TicketTab(QPushButton):
    """One of the V1 / V2 / V3 sale-slot tabs along the top."""
    def __init__(self, index: int):
        super().__init__()
        self.index = index
        self.setObjectName("ticketTab")
        self.setCheckable(True)
        self.setMinimumHeight(40)
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
        self.setMinimumHeight(36)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)


class CategoryButton(QPushButton):
    """A colored department / category / product key in the bottom grid."""
    def __init__(self, label: str, role: str):
        super().__init__(label)
        self.setObjectName(role)
        self.setMinimumHeight(36)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)


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
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.card = QFrame(self)
        self.card.setObjectName("tapDismissCard")
        self.card.setMinimumWidth(360)
        self.card.setMaximumWidth(520)

        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(28, 24, 28, 24)
        card_layout.setSpacing(8)

        self.title_label = QLabel("")
        self.title_label.setObjectName("tapDismissTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setWordWrap(True)

        self.message_label = QLabel("")
        self.message_label.setObjectName("tapDismissMessage")
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message_label.setWordWrap(True)

        card_layout.addWidget(self.title_label)
        card_layout.addWidget(self.message_label)

        layout.addWidget(self.card)

    def show_message(self, message: str, title: str = "", kind: str = "info"):
        """kind: 'info' | 'error' — controls the card's accent color."""
        self.title_label.setText(title)
        self.title_label.setVisible(bool(title))
        self.message_label.setText(message)
        self.card.setProperty("kind", kind)
        self.card.style().unpolish(self.card)
        self.card.style().polish(self.card)

        self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.show()

    def resizeEvent(self, event):
        # Keep covering the parent if the window is resized while visible
        if self.parentWidget():
            self.setGeometry(self.parentWidget().rect())
        super().resizeEvent(event)

    def mousePressEvent(self, event):
        # Tap anywhere — including the card — dismisses it
        self.hide()
