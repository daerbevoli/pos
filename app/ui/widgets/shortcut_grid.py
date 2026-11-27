"""
ShortcutGrid
The POS-style shortcut keyboard as a standalone widget: rows 0-2 are product
slots filled from whichever shortcut is selected, rows 3-4 are the shortcut
selector buttons. Tapping a filled slot emits product_pressed(product_id)
When there are more shortcuts (or products in a shortcut) than buttons, the
last button of that area becomes "More ▸" (next page), "◂ Back" on the last
page (back to the first).
"""
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QGridLayout, QWidget

from app.constants import SPACING_XS
from app.core.database import get_session
from app.core.inventory.product_service import ProductService
from app.utils.utils import CategoryButton


MORE_LABEL = "More ▸"
BACK_LABEL = "◂ Back"


def _page(n: int, capacity: int, page: int) -> tuple[int, int, int, str | None]:
    """Paging of n items over capacity buttons: (page, start, stop, nav label).
    page wraps around; nav label is None when everything fits on one page."""
    if n <= capacity:
        return 0, 0, n, None
    per = capacity - 1  # the last button is the page switch
    pages = -(-n // per)
    page %= pages
    start = page * per
    return page, start, min(start + per, n), BACK_LABEL if page == pages - 1 else MORE_LABEL


class ShortcutGrid(QWidget):
    product_pressed = pyqtSignal(int)

    COLUMNS = 8
    SLOT_ROWS = 3
    SHORTCUT_ROWS = 2
    SLOT_COUNT = SLOT_ROWS * COLUMNS

    def __init__(self, parent=None, show_prices: bool = False):
        super().__init__(parent)
        self._show_prices = show_prices  # append the current price to each slot label

        self.slot_buttons: list[CategoryButton] = []
        self._slot_product_ids: list[int | None] = [None] * self.SLOT_COUNT
        self.shortcut_buttons: list[CategoryButton] = []
        self._shortcuts: list[tuple[int, str]] = []  # (Shortcut.id, name), index-aligned with shortcut_buttons
        self.active_shortcut_id: int | None = None
        self._shortcut_page = 0
        self._shortcut_start = 0  # index in _shortcuts of shortcut_buttons[0]
        self._shortcut_nav = False  # last shortcut button is the page switch
        self._slot_rows: list[tuple] = []  # every product of the open shortcut
        self._slot_page = 0
        self._slot_nav = False

        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(SPACING_XS)

        for r in range(self.SLOT_ROWS):
            for c in range(self.COLUMNS):
                i = len(self.slot_buttons)
                btn = CategoryButton("", "blankBtnLight")
                btn.setEnabled(False)
                btn.clicked.connect(lambda _, idx=i: self._on_slot_pressed(idx))
                grid.addWidget(btn, r, c)
                self.slot_buttons.append(btn)

        for r in range(self.SLOT_ROWS, self.SLOT_ROWS + self.SHORTCUT_ROWS):
            for c in range(self.COLUMNS):
                i = len(self.shortcut_buttons)
                btn = CategoryButton("", "blankBtnLight")
                btn.setEnabled(False)
                btn.clicked.connect(lambda _, idx=i: self._on_shortcut_pressed(idx))
                grid.addWidget(btn, r, c)
                self.shortcut_buttons.append(btn)

        for c in range(self.COLUMNS):
            grid.setColumnStretch(c, 1)
        for r in range(self.SLOT_ROWS + self.SHORTCUT_ROWS):
            grid.setRowStretch(r, 1)

    def reload(self):
        """Refresh the selector buttons (and the open shortcut's slots) from
        the DB. Safe to call whenever shortcuts or prices may have changed."""
        with get_session() as session:
            self._shortcuts = [
                (sc.id, sc.name) for sc in ProductService.get_all_shortcuts(session)
            ]

        self._render_shortcuts()
        self.restore(self.active_shortcut_id)

    def _render_shortcuts(self):
        self._shortcut_page, start, stop, nav = _page(
            len(self._shortcuts), len(self.shortcut_buttons), self._shortcut_page)
        self._shortcut_start = start
        self._shortcut_nav = nav is not None
        for i, btn in enumerate(self.shortcut_buttons):
            btn.setProperty("active", False)
            if start + i < stop:
                btn.setText(self._shortcuts[start + i][1])
                btn.setEnabled(True)
                _apply_button_role(btn, "categoryBtn")
            elif nav and i == len(self.shortcut_buttons) - 1:
                btn.setText(nav)
                btn.setEnabled(True)
                _apply_button_role(btn, "generalBtn")
            else:
                btn.setText("")
                btn.setEnabled(False)
                _apply_button_role(btn, "blankBtnLight")
        self._sync_active_shortcut_style()

    def restore(self, shortcut_id: int | None):
        """Re-open shortcut_id if it still exists (it may have been deleted
        since it was selected), otherwise deselect and blank the slots."""
        if shortcut_id in {sid for sid, _ in self._shortcuts}:
            self.show_shortcut(shortcut_id)
        else:
            self.active_shortcut_id = None
            self.clear_slots()
            self._sync_active_shortcut_style()

    def show_shortcut(self, shortcut_id: int):
        with get_session() as session:
            rows = []
            for pid in ProductService.get_shortcut_product_ids(session, shortcut_id):
                product = ProductService.get_by_id(session, pid)
                if product and product.is_active:
                    rows.append((product.id, product.name, product.price, product.is_open_price))

        if shortcut_id != self.active_shortcut_id:
            self._slot_page = 0  # a reload of the same shortcut keeps its page
        self.active_shortcut_id = shortcut_id
        self._slot_rows = rows
        self._render_slots()
        self._sync_active_shortcut_style()

    def _render_slots(self):
        self.clear_slots()
        self._slot_page, start, stop, nav = _page(
            len(self._slot_rows), self.SLOT_COUNT, self._slot_page)
        for i, (pid, name, price, is_open_price) in enumerate(self._slot_rows[start:stop]):
            btn = self.slot_buttons[i]
            if self._show_prices:
                btn.setText(f"{name}\n{'Open price' if is_open_price else f'€{price:.2f}'}")
            else:
                btn.setText(name)
            btn.setEnabled(True)
            _apply_button_role(btn, "productBtn")
            self._slot_product_ids[i] = pid
        if nav:
            self._slot_nav = True
            btn = self.slot_buttons[-1]
            btn.setText(nav)
            btn.setEnabled(True)
            _apply_button_role(btn, "generalBtn")

    def _on_shortcut_pressed(self, index: int):
        """index is the button pressed, not the shortcut's position in the list."""
        if self._shortcut_nav and index == len(self.shortcut_buttons) - 1:
            self._shortcut_page += 1
            self._render_shortcuts()
        elif self._shortcut_start + index < len(self._shortcuts):
            self.show_shortcut(self._shortcuts[self._shortcut_start + index][0])

    def _on_slot_pressed(self, index: int):
        if self._slot_nav and index == self.SLOT_COUNT - 1:
            self._slot_page += 1
            self._render_slots()
        elif 0 <= index < len(self._slot_product_ids):
            pid = self._slot_product_ids[index]
            if pid is not None:
                self.product_pressed.emit(pid)

    def clear_slots(self):
        self._slot_nav = False
        for i, btn in enumerate(self.slot_buttons):
            btn.setText("")
            btn.setEnabled(False)
            _apply_button_role(btn, "blankBtnLight")
            self._slot_product_ids[i] = None

    def _sync_active_shortcut_style(self):
        shown = self._shortcuts[self._shortcut_start:]
        for (sid, _), btn in zip(shown, self.shortcut_buttons[: len(self.shortcut_buttons) - self._shortcut_nav]):
            btn.setProperty("active", sid == self.active_shortcut_id)
            btn.style().unpolish(btn)
            btn.style().polish(btn)


def _apply_button_role(btn: CategoryButton, role: str):
    if btn.objectName() != role:
        btn.setObjectName(role)
    btn.style().unpolish(btn)
    btn.style().polish(btn)
