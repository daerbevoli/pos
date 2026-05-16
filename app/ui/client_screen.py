"""
Client Screen
Select, view, add, edit and delete clients.
Layout mirrors a classic POS client selection screen.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt

from app.core.client_service import ClientService
from app.ui.dialogs.client_dialog import ClientDialog
from app.core.database import get_session


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
        action_grid = QGridLayout()
        action_grid.setSpacing(6)

        actions = [
            ("New Client",    0, 0, self._add_client),
            ("Edit Client",   0, 1, self._edit_client),
            ("Delete Client", 0, 2, self._delete_client),
            ("↑",             1, 0, self._scroll_up),
            ("🔄 Refresh",   1, 1, self._refresh),
            ("↓",             2, 0, self._scroll_down),
            ("Print",         3, 0, self._print_client),
            ("Address Label", 3, 1, self._print_label),
            ("OK",            3, 2, self._confirm_client),
            ("Cancel",        1, 2, self._cancel),
        ]

        self.ok_btn = None
        for label, row, col, handler in actions:
            btn = QPushButton(label)
            btn.setObjectName("clientActionBtn")
            btn.setFixedHeight(50)
            if label == "OK":
                btn.setObjectName("clientOkBtn")
                self.ok_btn = btn
            elif label == "Cancel":
                btn.setObjectName("clientCancelBtn")
            elif label == "Delete Client":
                btn.setObjectName("clientDeleteBtn")
            btn.clicked.connect(handler)
            action_grid.addWidget(btn, row, col)

        action_widget = QWidget()
        action_widget.setLayout(action_grid)
        top.addWidget(action_widget, stretch=2)

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

        # ── Virtual keyboard ──────────────────────────────────────────────────
        root.addWidget(self._build_keyboard())

    def _detail_row(self, parent_layout, label: str) -> QLabel:
        row = QHBoxLayout()
        lbl = QLabel(f"{label}:")
        lbl.setObjectName("clientDetailLabel")
        lbl.setFixedWidth(80)
        value = QLabel("—")
        value.setObjectName("clientDetailValue")
        row.addWidget(lbl)
        row.addWidget(value)
        parent_layout.addLayout(row)
        return value

    def _build_keyboard(self) -> QWidget:
        kb_widget = QWidget()
        kb_widget.setObjectName("keyboard")
        kb_layout = QVBoxLayout(kb_widget)
        kb_layout.setSpacing(5)
        kb_layout.setContentsMargins(0, 0, 0, 0)

        # (label, value_sent_to_handler, width, style)
        rows = [
            [("A", 1, 65, ""), ("Z", 1, 65, ""), ("E", 1, 65, ""), ("R", 1, 65, ""), ("T", 1, 65, ""),
             ("Y", 1, 65, ""), ("U", 1, 65, ""), ("I", 1, 65, ""), ("O", 1, 65, ""), ("P", 1, 65, ""),
             ("@", 1, 65, ""), ("⌫", "Del", 80, "keyboardDelBtn"),
             ("7", 1, 65, "keyboardNumBtn"), ("8", 1, 65, "keyboardNumBtn"), ("9", 1, 65, "keyboardNumBtn")],

            [("Q", 1, 65, ""), ("S", 1, 65, ""), ("D", 1, 65, ""), ("F", 1, 65, ""), ("G", 1, 65, ""),
             ("H", 1, 65, ""), ("J", 1, 65, ""), ("K", 1, 65, ""), ("L", 1, 65, ""), ("M", 1, 65, ""),
             ("+", 1, 65, ""), ("", None, 65, ""),
             ("4", 1, 65, "keyboardNumBtn"), ("5", 1, 65, "keyboardNumBtn"), ("6", 1, 65, "keyboardNumBtn")],

            [("W", 1, 65, ""), ("X", 1, 65, ""), ("C", 1, 65, ""), ("V", 1, 65, ""), ("B", 1, 65, ""),
             ("N", 1, 65, ""), (",", 1, 65, ""), (".", 1, 65, ""), ("/", 1, 65, ""), ("!", 1, 65, ""),
             ("*", 1, 65, ""), ("", None, 65, ""),
             ("1", 1, 65, "keyboardNumBtn"), ("2", 1, 65, "keyboardNumBtn"), ("3", 1, 65, "keyboardNumBtn")],

            [("Space", "Space", 500, "keyboardSpaceBtn"), ("", None, 65, ""), ("", None, 65, ""),
             ("", None, 65, ""), ("", None, 65, ""), ("", None, 65, ""), ("", None, 65, ""),
             ("", None, 65, ""), ("", None, 65, ""), ("", None, 65, ""), ("", None, 65, ""),
             ("", None, 65, ""),
             ("0", 1, 65, "keyboardNumBtn"), ("", None, 65, ""), ("", None, 65, "")],
        ]

        for key_row in rows:
            row_layout = QHBoxLayout()
            row_layout.setSpacing(5)
            for label, value, width, style in key_row:
                if not label:  # empty slot — invisible spacer button
                    spacer = QWidget()
                    spacer.setFixedWidth(width)
                    row_layout.addWidget(spacer)
                    continue
                btn = QPushButton(label)
                btn.setObjectName(style or "keyboardBtn")
                btn.setFixedHeight(50)
                btn.setFixedWidth(width)
                btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                # value=1 means use the label itself as the value
                send = label if value == 1 else value
                btn.clicked.connect(lambda _, k=send: self._keyboard_press(k))
                row_layout.addWidget(btn)
            row_layout.addStretch()
            kb_layout.addLayout(row_layout)

        return kb_widget

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

    def _edit_client(self):
        if self.selected_client:
            print(f"Edit: {self.selected_client['name']}")

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