"""
Client Screen
Select, view, add, edit and delete clients.
Layout mirrors a classic POS client selection screen.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QFrame, QSizePolicy, QMessageBox, QLineEdit, QComboBox, QTableWidget, QTableWidgetItem,
    QHeaderView
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


class ClientDetailPanel(QFrame):
    """
    "Detail view for a single Client:
    a field list on the left, a function-key grid on the right.
    Hidden until a row is selected in the table above it.
    """

    def __init__(self, parent_screen):
        super().__init__(parent_screen)
        self.parent_screen = parent_screen
        self.current_client_id = None
        self.setObjectName("articleDetailPanel")
        self._build_ui()

    def _build_ui(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        # ── Left: field list ────────────────────────────────────────────
        field_frame = QFrame()
        field_frame.setObjectName("articleFieldFrame")
        field_col = QVBoxLayout(field_frame)
        field_col.setSpacing(10)

        title = QLabel("Select Client")
        title.setObjectName("articleDetailTitle")
        field_col.addWidget(title)

        self.field_labels = {}
        field_names = [
            ("name", "Name:"),
            ("address", "Address:"),
            ("vat", "VAT:"),
            ("phone", "Phone:"),
            ("email", "Email:")
        ]
        for key, caption in field_names:
            row = QHBoxLayout()
            cap_label = QLabel(caption)
            cap_label.setObjectName("articleFieldCaption")
            cap_label.setFixedWidth(120)
            value_label = QLabel("—")
            value_label.setObjectName("articleFieldValue")
            row.addWidget(cap_label)
            row.addWidget(value_label, stretch=1)
            field_col.addLayout(row)
            self.field_labels[key] = value_label

        field_col.addStretch()
        outer.addWidget(field_frame, stretch=3)

        # ── Right: function-key grid ────────────────────────────────────
        grid = QGridLayout()
        grid.setSpacing(4)

        self.btn_new = FunctionButton("New\nClient", "newArticleBtn")
        self.btn_modify = FunctionButton("Modify\nClient", "secFunc")
        self.btn_delete = FunctionButton("Delete\nClient", "deleteArticleBtn")
        self.btn_error = FunctionButton("Error", "errorBtn")

        self.btn_print_label = FunctionButton("Print\nlabel", "secFunc")
        self.btn_cancel = FunctionButton("Cancel", "cancelBtn")

        self.btn_search_barcode = FunctionButton("Search by\nname", "secFunc")
        self.btn_search_key = FunctionButton("Search by\nvat", "secFunc")
        self.btn_ok = FunctionButton("OK", "okBtn")

        layout_map = [
            (self.btn_new, 0, 0), (self.btn_modify, 0, 1),
            (self.btn_delete, 0, 2), (self.btn_error, 0, 3),

            (self.btn_search_barcode, 1, 1),
            (self.btn_search_key, 1, 2), (self.btn_ok, 1, 3),

            (self.btn_cancel, 2, 3)
        ]
        for widget, r, c in layout_map:
            grid.addWidget(widget, r, c)

        for c in range(4):
            grid.setColumnStretch(c, 1)
        for r in range(5):
            grid.setRowStretch(r, 1)

        outer.addLayout(grid, stretch=4)

        # Wire actions to the parent screen's existing service calls
        self.btn_new.clicked.connect(self.parent_screen._add_client)
        self.btn_modify.clicked.connect(self._on_modify)
        self.btn_delete.clicked.connect(self._on_delete)
        self.btn_error.clicked.connect(self._clear)
        self.btn_cancel.clicked.connect(self._clear)
        self.btn_ok.clicked.connect(self._confirm_client)
        self.btn_search_barcode.clicked.connect(self._on_search_barcode)
        self.btn_search_key.clicked.connect(self._on_search_key)

    # ── Display ──────────────────────────────────────────────────────────

    def _clear(self):
        if self.current_client_id is not None:
            self.current_client_id = None
            for label in self.field_labels.values():
                label.setText("—")

    def _confirm_client(self):
        if self.current_client_id:
            self.parent_screen.selected_client.emit(self.current_client_id, self.field_labels["name"].text())
        self.parent_screen.navigate.emit(0)


    def show_client(self, client):
        self.current_client_id = client.id
        self.field_labels["name"].setText(client.name or "—")
        self.field_labels["address"].setText(client.address or "-")
        self.field_labels["vat"].setText(client.vatNumber or "—")
        self.field_labels["phone"].setText(client.phone or "-")
        self.field_labels["email"].setText(client.email or "-")
        self.show()

    # ── Actions ──────────────────────────────────────────────────────────

    def _on_modify(self):
        if self.current_client_id is None:
            return
        self.parent_screen._edit_client(self.current_client_id)

    def _on_delete(self):
        if self.current_client_id is None:
            return
        self.parent_screen._delete_client(self.current_client_id)
        self.hide()

    def _on_search_barcode(self):
        self.parent_screen.search_input.setFocus()
        self.parent_screen.search_input.setPlaceholderText("Scan or type barcode…")

    def _on_search_key(self):
        self.parent_screen.search_input.setFocus()
        self.parent_screen.search_input.setPlaceholderText("Search by name or barcode…")

    def _stub_action(self, label: str):
        QMessageBox.information(self, label, f"{label} — coming soon.")


class ClientScreen(QWidget):

    navigate = pyqtSignal(int)
    selected_client = pyqtSignal(int, str)

    def __init__(self):
        super().__init__()
        self._build_ui()
        self.refresh()


    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # ── Article detail panel (always visible) ─────────────────────────────
        self.detail_panel = ClientDetailPanel(self)
        layout.addWidget(self.detail_panel)

        # ── Search / filter bar ───────────────────────────────────────────────
        toolbar = QHBoxLayout()

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search by name or VAT…")
        self.search_input.setFixedHeight(44)
        self.search_input.textChanged.connect(self.refresh)
        toolbar.addWidget(self.search_input, stretch=2)
        layout.addLayout(toolbar)

        # ── client table ─────────────────────────────────────────────────────
        self.table = QTableWidget(0, 4)
        self.table.setObjectName("inventoryTable")
        self.table.setHorizontalHeaderLabels([
            "Name", "Address", "Vat", "Phone", "Email"
        ])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        layout.addWidget(self.table, stretch=1)

        self._client_cache = {}

    def refresh(self):
        with get_session() as session:

            # Get clients
            query = self.search_input.text().strip()
            if query:
                clients = ClientService.search(session, query)
            else:
                clients = ClientService.get_all(session)

            self._populate_table(clients, session)
        self.search_input.setFocus()


    def _populate_table(self, clients, session):
        self.table.setRowCount(0)
        self._client_cache = {}
        for c in clients:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self._client_cache[row] = c.id

            self.table.setItem(row, 0, QTableWidgetItem(c.name or ""))
            self.table.setItem(row, 1, QTableWidgetItem(c.address or ""))
            self.table.setItem(row, 2, QTableWidgetItem(f"{c.vatNumber}"))
            self.table.setItem(row, 3, QTableWidgetItem(f"{c.phone}"))
            self.table.setItem(row, 4, QTableWidgetItem(f"{c.email}"))

            # Action buttons
            actions = QWidget()
            actions_layout = QHBoxLayout(actions)
            actions_layout.setContentsMargins(2, 2, 2, 2)
            actions_layout.setSpacing(4)

            edit_btn = QPushButton("✏️")
            edit_btn.setFixedSize(36, 36)
            edit_btn.clicked.connect(lambda _, cid=c.id: self._edit_client(cid))
            actions_layout.addWidget(edit_btn)

            del_btn = QPushButton("🗑️")
            del_btn.setFixedSize(36, 36)
            del_btn.clicked.connect(lambda _, cid=c.id: self._delete_client(cid))
            actions_layout.addWidget(del_btn)

            self.table.setCellWidget(row, 7, actions)
            self.table.setRowHeight(row, 50)

    # ── Detail panel wiring ─────────────────────────────────────────────────

    def _on_row_selected(self):
        row = self.table.currentRow()
        if row < 0 or row not in self._client_cache:
            self.detail_panel._clear()
            return
        client_id = self._client_cache[row]
        with get_session() as session:
            client = ClientService.get_by_id(session, client_id)
            if client:
                self.detail_panel.show_client(client)
            else:
                self.detail_panel._clear()

    def _add_client(self):
        dialog = ClientDialog(self)
        if dialog.exec():
            with get_session() as session:
                ClientService.create(session, **dialog.get_data())
            self.refresh()

    def _edit_client(self, client_id: int):
        with get_session() as session:
            client = ClientService.get_by_id(session, client_id)
            if not client:
                return
            dialog = ClientDialog(self, client)
            if dialog.exec():
                ClientService.update(session, client_id, **dialog.get_data())
        self.refresh()

    def _delete_client(self, client_id: int):
        reply = QMessageBox.question(
            self, "Deactivate client",
            "This will hide the client from the POS. Sales history is preserved.\nContinue?"
        )
        if reply == QMessageBox.StandardButton.Yes:
            with get_session() as session:
                ClientService.deactivate(session, client_id)
            self.refresh()

    def _clear(self):
        self.navigate.emit(0)