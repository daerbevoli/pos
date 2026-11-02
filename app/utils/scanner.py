"""App-wide barcode scanner input.

The scanner acts as a keyboard and is programmed to wrap every scan in
SCAN_PREFIX / SCAN_SUFFIX (e.g. '^<5410000000012^>'), a sequence no one types
by hand. `ScanInterceptor` is installed on the QApplication, so it sees the
keystrokes before any widget does: the markers never reach a text field, and
the scanned code is handed to whatever has focus —

- a widget with a `barcode_scanned` signal (the POS ticket table) gets it
  emitted;
- an editable QLineEdit gets the code inserted followed by Enter, as if only
  the digits had been typed (inventory search, the article barcode field,
  label dialogs, ...).

On a Belgian AZERTY layout '^' is a dead key: Qt delivers it as a key event
with key Key_Dead_Circumflex and *no text*, and the next key event may carry
'<' alone or '^<' together. Both forms are matched here.
"""
import logging
import time

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication, QLineEdit

logger = logging.getLogger(__name__)

SCAN_PREFIX = "^<"
SCAN_SUFFIX = "^>"
# A scanner types a whole code in a few tens of ms; a longer pause means a
# person is typing, so a half-matched prefix or an unterminated scan is dropped.
MAX_KEY_GAP_S = 0.5


class ScanInterceptor(QObject):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._prefix_matched = ""
        # '^' swallowed while matching the prefix; replayed to the widget if
        # it turns out not to be a scan.
        self._pending_replay = ""
        self._scanning = False
        self._buffer = ""
        self._last_key_time = 0.0
        self._replaying = False
        self._dead_caret = False

    # ── event filter ──────────────────────────────────────────────────────

    def eventFilter(self, obj, event):
        if self._replaying or event.type() != QEvent.Type.KeyPress:
            return False
        # Key events propagate up the parent chain; act only on the first
        # delivery (the focus widget, or the window when nothing has focus).
        target = QApplication.focusWidget() or QApplication.activeWindow()
        if obj is not target:
            return False

        now = time.monotonic()
        if (self._scanning or self._prefix_matched) and now - self._last_key_time > MAX_KEY_GAP_S:
            if self._scanning:
                logger.warning("Barcode scan abandoned, no end marker: %r", self._buffer)
            self._reset()
        self._last_key_time = now

        text = event.text()
        if event.key() == Qt.Key.Key_Dead_Circumflex and not text:
            # The OS folds a dead '^' into the next key's text ('ê', or '^<'
            # when it can't combine) — or sends that key bare ('<'). Hold it.
            self._dead_caret = True
            return True
        if self._dead_caret and text:
            self._dead_caret = False
            if text[0] in "<>":
                text = "^" + text
        if not text:
            # Shift etc. — swallow mid-scan so nothing leaks into the widget.
            return self._scanning or bool(self._prefix_matched)

        consumed, code, replay = self._feed(text)
        if replay:
            self._replay(obj, replay)
        if code is not None:
            self._deliver(obj, code)
        return consumed

    # ── matching ──────────────────────────────────────────────────────────

    def _reset(self):
        self._prefix_matched = ""
        self._pending_replay = ""
        self._scanning = False
        self._buffer = ""
        self._dead_caret = False

    def _feed(self, text):
        """Returns (consumed, scanned_code_or_None, text_to_replay)."""
        consumed = True
        code = None
        replay = ""
        for ch in text:
            if self._scanning:
                self._buffer += ch
                if self._buffer.endswith(SCAN_SUFFIX):
                    code = self._buffer[:-len(SCAN_SUFFIX)]
                    self._reset()
                continue

            candidate = self._prefix_matched + ch
            if SCAN_PREFIX.startswith(candidate):
                if candidate == SCAN_PREFIX:
                    self._prefix_matched = ""
                    self._pending_replay = ""
                    self._scanning = True
                    self._buffer = ""
                else:
                    self._prefix_matched = candidate
                    self._pending_replay += ch
                continue

            # Not a scan: give back any real '^' we held, then let this
            # event through untouched (only if it's the event's sole text).
            replay += self._pending_replay
            self._prefix_matched = ""
            self._pending_replay = ""
            if SCAN_PREFIX.startswith(ch):
                self._prefix_matched = ch
                self._pending_replay = ch
            else:
                consumed = False
        if not consumed and len(text) > 1:
            # Mixed text like '^1' from a dead key: let the widget have it all.
            replay = ""
        return consumed, code, replay

    # ── output ────────────────────────────────────────────────────────────

    def _replay(self, widget, text):
        self._replaying = True
        try:
            QApplication.sendEvent(widget, QKeyEvent(
                QEvent.Type.KeyPress, Qt.Key.Key_unknown, Qt.KeyboardModifier.NoModifier, text))
        finally:
            self._replaying = False

    def _deliver(self, widget, code):
        code = code.strip()
        logger.info("Barcode scanned: %s (focus: %s)", code, type(widget).__name__)
        if not code:
            return
        # A container (e.g. the article form in edit mode) can claim scans
        # made anywhere inside it, whichever of its fields has focus.
        ancestor = widget
        while ancestor is not None:
            handler = getattr(ancestor, "handle_barcode_scan", None)
            if handler is not None and handler(code):
                return
            ancestor = ancestor.parentWidget()
        signal = getattr(widget, "barcode_scanned", None)
        if signal is not None:
            signal.emit(code)
        elif isinstance(widget, QLineEdit) and not widget.isReadOnly() and widget.isEnabled():
            widget.insert(code)
            self._replaying = True
            try:
                for etype in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
                    QApplication.sendEvent(widget, QKeyEvent(
                        etype, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier, "\r"))
            finally:
                self._replaying = False
        else:
            logger.info("Scan ignored: focused widget doesn't take barcodes")


def install_scan_interceptor(app: QApplication) -> ScanInterceptor:
    interceptor = ScanInterceptor(app)
    app.installEventFilter(interceptor)
    return interceptor
