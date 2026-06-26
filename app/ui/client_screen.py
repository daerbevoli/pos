"""
Client Screen
Select, view, add, edit and delete clients.
Layout mirrors a classic POS client selection screen.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal

from app.core.client_service import ClientService
from app.ui.dialogs.client_dialog import ClientDialog
from app.core.database import get_session
from app.utils.utils import FunctionButton

# ── Dummy client data (replace with DB later) ─────────────────────────────────
DUMMY_CLIENTS = [
    {"id": 1,  "name": "Bakkerij De Zon",      "street": "Kerkstraat 12",       "postcode": "2000", "city": "Antwerpen", "phone": "0471234567", "vat": "BE 0123.456.789"},
    {"id": 2,  "name": "Slagerij Peeters",      "street": "Marktplein 5",        "postcode": "2060", "city": "Antwerpen", "phone": "0472345678", "vat": ""},
    {"id": 3,  "name": "Café De Kroon",         "street": "Grote Markt 1",       "postcode": "2800", "city": "Mechelen",  "phone": "0473456789", "vat": "BE 0234.567.890"},
    {"id": 4,  "name": "Frituur 't Hoekje",     "street": "Stationsstraat 44",   "postcode": "2018", "city": "Antwerpen", "phone": "0474567890", "vat": ""},
    {"id": 5,  "name": "Apotheek Janssen",      "street": "Leopoldlei 8",        "postcode": "2930", "city": "Brasschaat","phone": "0475678901", "vat": "BE 0345.678.901"},
    {"id": 6,  "name": "Bloemenwinkel Roos",    "street": "Antwerpseweg 22",     "postcode": "2500", "city": "Lier",      "phone": "0476789012", "vat": ""},
    {"id": 7,  "name": "Garage Vermeersch",     "street": "Industrieweg 77",     "postcode": "2200", "city": "Herentals","phone": "0477890123", "vat": "BE 0456.789.012"},
    {"id": 8,  "name": "Kapsalon Hairmax",      "street": "Turnhoutsebaan 15",   "postcode": "2140", "city": "Borgerhout","phone": "0478901234", "vat": ""},
    {"id": 9,  "name": "Restaurant Azur",       "street": "Havenstraat 3",       "postcode": "2000", "city": "Antwerpen", "phone": "0479012345", "vat": "BE 0567.890.123"},
    {"id": 10, "name": "Tuincentrum Groen",     "street": "Boomsesteenweg 99",   "postcode": "2610", "city": "Wilrijk",   "phone": "0480123456", "vat": ""},
    {"id": 11, "name": "Parfumerie Belle",      "street": "Meir 50",             "postcode": "2000", "city": "Antwerpen", "phone": "0481234567", "vat": "BE 0678.901.234"},
    {"id": 12, "name": "Drukkerij Snelprint",   "street": "Nijverheidskaai 14",  "postcode": "1080", "city": "Brussel",   "phone": "0482345678", "vat": "BE 0789.012.345"},
    {"id": 13, "name": "Elektro Watt",          "street": "Diksmuidelaan 6",     "postcode": "2600", "city": "Berchem",   "phone": "0483456789", "vat": ""},
    {"id": 14, "name": "Sportshop Running",     "street": "Atletenstraat 33",    "postcode": "2100", "city": "Deurne",    "phone": "0484567890", "vat": "BE 0890.123.456"},
    {"id": 15, "name": "Ijswinkel Gelato",      "street": "Zomerstraat 2",       "postcode": "2000", "city": "Antwerpen", "phone": "0485678901", "vat": ""},
    {"id": 16, "name": "Boekhandel Pagina",     "street": "Schoenmarkt 7",       "postcode": "2000", "city": "Antwerpen", "phone": "0486789012", "vat": "BE 0901.234.567"},
    {"id": 17, "name": "Kantoorshop Pro",       "street": "Bedrijvenpark 11",    "postcode": "2300", "city": "Turnhout",  "phone": "0487890123", "vat": ""},
    {"id": 18, "name": "Vishandel Neptuno",     "street": "Visserskaai 4",       "postcode": "8400", "city": "Oostende",  "phone": "0488901234", "vat": "BE 0012.345.678"},
]


class ClientScreen(QWidget):

    navigate = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.selected_client = None
        self.filtered_clients = list(DUMMY_CLIENTS)
        self.search_term = ""
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._build_ui()
        self._render_client_grid()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # ── Top section: client detail + action buttons ───────────────────────
        top = QHBoxLayout()
        top.setSpacing(10)

        # Client detail panel
        detail_frame = QFrame()
        detail_frame.setObjectName("clientDetailFrame")
        detail_frame.setFixedHeight(220)
        detail_layout = QVBoxLayout(detail_frame)
        detail_layout.setContentsMargins(16, 12, 16, 12)
        detail_layout.setSpacing(6)

        title = QLabel("Select Client")
        title.setObjectName("clientDetailTitle")
        detail_layout.addWidget(title)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setObjectName("clientDetailSep")
        detail_layout.addWidget(sep)

        self.detail_name     = self._detail_row(detail_layout, "Name")
        self.detail_street   = self._detail_row(detail_layout, "Street")
        self.detail_postcode = self._detail_row(detail_layout, "Postcode")
        self.detail_city     = self._detail_row(detail_layout, "City")
        self.detail_phone    = self._detail_row(detail_layout, "Phone")
        self.detail_vat      = self._detail_row(detail_layout, "VAT")

        top.addWidget(detail_frame, stretch=3)

        # Action buttons panel
        action_panel = QWidget()
        action_panel.setFixedHeight(220)
        action_panel.setLayout(self._build_action_panel())
        top.addWidget(action_panel, stretch=3)

        root.addLayout(top)

        # ── Search display ────────────────────────────────────────────────────
        search_bar = QHBoxLayout()
        search_icon = QLabel("🔍")
        search_icon.setFixedWidth(30)
        self.search_display = QLabel("Type to search clients...")
        self.search_display.setObjectName("clientSearchDisplay")
        search_bar.addWidget(search_icon)
        search_bar.addWidget(self.search_display)
        search_bar.addStretch()
        root.addLayout(search_bar)

        # ── Client grid ───────────────────────────────────────────────────────
        self.client_grid_widget = QWidget()
        self.client_grid_layout = QGridLayout(self.client_grid_widget)
        self.client_grid_layout.setSpacing(5)
        root.addWidget(self.client_grid_widget)


    def _build_action_panel(self):
        grid = QGridLayout()
        grid.setSpacing(4)

        self.btn_new     = FunctionButton("New\nClient",    "secFunc")
        self.btn_edit    = FunctionButton("Edit\nClient",   "secFunc")
        self.btn_delete  = FunctionButton("Delete\nClient", "errorBtn")
        self.btn_up      = FunctionButton("↑",              "navBtn")
        self.btn_down    = FunctionButton("↓",              "navBtn")
        self.btn_refresh = FunctionButton("Refresh",        "secFunc")
        self.btn_print   = FunctionButton("Print",          "secFunc")
        self.btn_label   = FunctionButton("Address\nLabel", "secFunc")
        self.btn_ok      = FunctionButton("OK",             "okBtn")
        self.btn_cancel  = FunctionButton("Cancel",         "clearBtn")

        layout_map = [
            (self.btn_new,     0, 0, 1, 1), (self.btn_edit,    0, 1, 1, 1), (self.btn_delete,  0, 2, 1, 1),
            (self.btn_up,      1, 0, 1, 1), (self.btn_refresh, 1, 1, 1, 1), (self.btn_cancel,  1, 2, 1, 1),
            (self.btn_down,    2, 0, 1, 1),
            (self.btn_print,   3, 0, 1, 1), (self.btn_label,   3, 1, 1, 1), (self.btn_ok,      3, 2, 1, 1),
        ]

        for widget, r, c, rs, cs in layout_map:
            grid.addWidget(widget, r, c, rs, cs)

        for col in range(3):
            grid.setColumnStretch(col, 1)
        for row in range(4):
            grid.setRowStretch(row, 1)

        self.btn_new.clicked.connect(self._add_client)
        self.btn_edit.clicked.connect(self._edit_client)
        self.btn_delete.clicked.connect(self._delete_client)
        self.btn_up.clicked.connect(self._scroll_up)
        self.btn_down.clicked.connect(self._scroll_down)
        self.btn_refresh.clicked.connect(self._refresh)
        self.btn_print.clicked.connect(self._print_client)
        self.btn_label.clicked.connect(self._print_label)
        self.btn_ok.clicked.connect(self._confirm_client)
        self.btn_cancel.clicked.connect(self._cancel)

        return grid

    def _detail_row(self, parent_layout, label: str) -> QLabel:
        row = QHBoxLayout()
        lbl = QLabel(f"{label}:")
        lbl.setObjectName("clientDetailLabel")
        lbl.setFixedWidth(30)
        value = QLabel("—")
        value.setObjectName("clientDetailValue")
        row.addWidget(lbl)
        row.addWidget(value)
        parent_layout.addLayout(row)
        return value

    def _render_client_grid(self):
        # Clear existing buttons
        for i in reversed(range(self.client_grid_layout.count())):
            w = self.client_grid_layout.itemAt(i).widget()
            if w:
                w.deleteLater()

        cols = 6
        for idx, client in enumerate(self.filtered_clients):
            row = idx // cols
            col = idx % cols
            name_lines = client["name"]
            btn = QPushButton(f"{name_lines}")
            btn.setObjectName("clientGridBtn")
            btn.setFixedSize(200, 65)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

            if self.selected_client and self.selected_client["id"] == client["id"]:
                btn.setObjectName("clientGridBtnSelected")
            btn.clicked.connect(lambda _, c=client: self._select_client(c))
            self.client_grid_layout.addWidget(btn, row, col)

    def _select_client(self, client: dict):
        self.selected_client = client
        self.detail_name.setText(client["name"])
        self.detail_street.setText(client["street"])
        self.detail_postcode.setText(client["postcode"])
        self.detail_city.setText(client["city"])
        self.detail_phone.setText(client["phone"])
        self.detail_vat.setText(client["vat"] or "—")
        self._render_client_grid()  # re-render to show selection highlight

    def _keyboard_press(self, key: str):
        if key == "Del":
            self.search_term = self.search_term[:-1]
        elif key == "Space":
            self.search_term += " "
        else:
            self.search_term += key

        # Update the search display
        if self.search_term:
            self.search_display.setText(self.search_term + "▌")
        else:
            self.search_display.setText("Type to search clients...")

        # Filter clients by name
        term = self.search_term.upper()
        self.filtered_clients = [
            c for c in DUMMY_CLIENTS
            if term in c["name"].upper()
        ]
        self._render_client_grid()

    def keyPressEvent(self, event):
        key = event.key()
        text = event.text()
        print(key, text)

        if key == Qt.Key.Key_Backspace:
            self._keyboard_press("Del")  # reuse same logic

        elif key == Qt.Key.Key_Space:
            self._keyboard_press("Space")  # reuse same logic

        elif key == Qt.Key.Key_Escape:
            self._cancel()

        elif key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
            self._confirm_client()

        elif text and text.isprintable():
            self._keyboard_press(text)

        else:
            super().keyPressEvent(event)

    # ── Action handlers ───────────────────────────────────────────────────────
    def _add_client(self):
        dialog = ClientDialog(self)
        if dialog.exec():
            with get_session() as session:
                ClientService.create(session, **dialog.get_data())
            self.filtered_clients.append(dialog.get_data())
        self._refresh()

    def _edit_client(self, client_id: int):
        with get_session() as session:
            client = ClientService.get_by_id(session, client_id=client_id)
            if not client:
                return
            dialog = ClientDialog(self, client)
            if dialog.exec():
                ClientService.update(session, client_id, **dialog.get_data())
        self._refresh()

    def _delete_client(self):
        if self.selected_client:
            print(f"Delete: {self.selected_client['name']}")

    def _scroll_up(self):
        print("Scroll up")

    def _scroll_down(self):
        print("Scroll down")

    def _print_client(self):
        print("Print client fiche")

    def _print_label(self):
        print("Print address label")

    def _confirm_client(self):
        if self.selected_client:
            print(f"Confirmed: {self.selected_client['name']}")

    def _cancel(self):
        if self.selected_client is not None:
            self.selected_client = None
            self.search_term = ""
            self.filtered_clients = list(DUMMY_CLIENTS)
            self.detail_name.setText("—")
            self.detail_street.setText("—")
            self.detail_postcode.setText("—")
            self.detail_city.setText("—")
            self.detail_phone.setText("—")
            self.detail_vat.setText("—")
            self._render_client_grid()
            return
        self.navigate.emit(0)


    def _refresh(self):
        self.search_term = ""
        self.search_display.setText("Type to search clients...")
        self.filtered_clients = list(DUMMY_CLIENTS)
        self._render_client_grid()


if __name__ == "__main__":
    import sys
    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    # with open("resources/styles/main.qss", "r") as f:
    #     app.setStyleSheet(f.read())
    window = ClientScreen()
    window.setWindowTitle("Client Screen - Dev")
    window.resize(1280, 800)
    window.show()
    sys.exit(app.exec())