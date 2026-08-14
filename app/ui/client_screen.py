"""
Client Screen
Table list of clients on top; selecting a row shows a "Client
selecteren"-style detail panel below, with a field list on the left and a
function-key grid on the right (New/Modify/Delete client, Import, Search by
vat, OK/Cancel). New/Modify client edit the fields inline in the panel
itself, mirroring the inventory screen's article editing.
"""
import csv

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLineEdit,
    QLabel, QFrame, QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QFileDialog
)
from PyQt6.QtCore import Qt, QEvent, pyqtSignal

from app.core.client_service import ClientService
from app.models.models import Client
from app.core.database import get_session
from app.ui.widgets.form_fields import FieldRow
from app.ui.dialogs.file_dialog import FileDialog
from app.utils.utils import TapToDismissOverlay, FunctionButton
from app.constants import (
    BUTTON_HEIGHT_XS,
    INPUT_HEIGHT,
    INPUT_HEIGHT_COMPACT,
    SPACING_MD,
    SPACING_XS,
)
# Column order shared by _on_export/_on_import so a re-imported CSV round-trips cleanly.
CLIENT_CSV_FIELDS = ["name", "vat", "address", "phone", "email", "active"]


class ClientDetailPanel(QFrame):
    """
    Detail view for a single client: a field list on the left (editable
    inline for New/Modify), a function-key grid on the right. Hidden until a
    row is selected in the table above it.
    """

    def __init__(self, parent_screen):
        super().__init__(parent_screen)
        self.parent_screen = parent_screen
        self.current_client_id = None
        self._mode = "display"  # "display" | "new" | "edit"

        self._active_row: FieldRow | None = None

        self.overlay = TapToDismissOverlay(self)

        self.setObjectName("articleDetailPanel")
        self._build_ui()

    # ── Setup ────────────────────────────────────────────────────────────

    def _build_ui(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(3, 3, 3, 3)
        outer.setSpacing(SPACING_XS)

        # ── Left: field list ────────────────────────────────────────────
        field_frame = QFrame()
        field_frame.setObjectName("articleFieldFrame")
        field_col = QVBoxLayout(field_frame)
        field_col.setContentsMargins(6, 6, 6, 6)
        field_col.setSpacing(SPACING_XS)

        title_row = QHBoxLayout()
        self._title_label = QLabel("Select Client")
        self._title_label.setObjectName("articleDetailTitle")
        title_row.addWidget(self._title_label)
        title_row.addStretch()
        self._active_status_label = QLabel("—")
        self._active_status_label.setObjectName("articleFieldValue")
        title_row.addWidget(self._active_status_label)
        field_col.addLayout(title_row)

        self.name = QLineEdit()
        self.name.setMinimumHeight(INPUT_HEIGHT_COMPACT)

        self.address = QLineEdit()
        self.address.setMinimumHeight(INPUT_HEIGHT_COMPACT)

        self.vatNumber = QLineEdit()
        self.vatNumber.setMinimumHeight(INPUT_HEIGHT_COMPACT)

        self.phone = QLineEdit()
        self.phone.setMinimumHeight(INPUT_HEIGHT_COMPACT)

        self.email = QLineEdit()
        self.email.setMinimumHeight(INPUT_HEIGHT_COMPACT)

        rows_spec = [
            ("Name *",       self.name),
            ("Address",      self.address),
            ("VAT Number *", self.vatNumber),
            ("Phone",        self.phone),
            ("Email",        self.email),
        ]

        self._fields = []
        self._row_map: dict = {}

        for label_text, widget in rows_spec:
            row = FieldRow(label_text, widget)
            field_col.addWidget(row)
            self._fields.append(widget)
            self._row_map[widget] = row
            widget.installEventFilter(self)

        field_col.addStretch()
        outer.addWidget(field_frame, stretch=3)

        # ── Right: function-key grid ────────────────────────────────────
        grid = QGridLayout()
        grid.setSpacing(SPACING_XS)

        self.btn_new = FunctionButton("New\nClient", "newArticleBtn")
        self.btn_modify = FunctionButton("Modify\nClient", "secFunc")
        self.btn_delete = FunctionButton("Delete\nClient", "deleteArticleBtn")
        self.btn_error = FunctionButton("Error", "errorBtn")

        self.btn_up = FunctionButton("Up", "secFunc")
        self.btn_import = FunctionButton("Import", "secFunc")
        self.btn_export = FunctionButton("Export", "secFunc")
        self.btn_search_key = FunctionButton("Search by\nvat", "secFunc")
        self.btn_cancel = FunctionButton("Cancel", "cancelBtn")

        self.btn_down = FunctionButton("Down", "secFunc")
        self.btn_ok = FunctionButton("OK", "okBtn")

        layout_map = [
            (self.btn_new, 0, 0), (self.btn_modify, 0, 1),
            (self.btn_delete, 0, 2), (self.btn_error, 0, 3),

            (self.btn_up, 1, 0), (self.btn_import, 1, 1),
            (self.btn_export, 1, 2), (self.btn_cancel, 1, 3),

            (self.btn_down, 2, 0), (self.btn_search_key, 2, 2),
            (self.btn_ok, 2, 3),
        ]
        for widget, r, c in layout_map:
            widget.setMinimumHeight(BUTTON_HEIGHT_XS)
            grid.addWidget(widget, r, c)

        for c in range(4):
            grid.setColumnStretch(c, 1)
        for r in range(5):
            grid.setRowStretch(r, 1)

        outer.addLayout(grid, stretch=3)

        # Wire actions
        self.btn_new.clicked.connect(self._start_new)
        self.btn_modify.clicked.connect(self._start_edit)
        self.btn_delete.clicked.connect(self._on_delete)
        self.btn_error.clicked.connect(self._on_cancel)
        self.btn_cancel.clicked.connect(self._on_cancel)
        self.btn_ok.clicked.connect(self._on_ok)
        self.btn_import.clicked.connect(self._on_import)
        self.btn_export.clicked.connect(self._on_export)
        self.btn_search_key.clicked.connect(self._on_search_key)
        self.btn_up.clicked.connect(lambda: self._navigate(-1))
        self.btn_down.clicked.connect(lambda: self._navigate(1))

        self._set_edit_mode(False)

    # ── Event filter (focus tracking + keyboard nav) ───────────────────────

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.FocusIn:
            if self._active_row:
                self._active_row.set_active(False)
            row = self._row_map.get(obj)
            if row:
                self._active_row = row
                row.set_active(True)

        elif event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Up:
                self._navigate(-1)
                return True
            elif key == Qt.Key.Key_Down:
                self._navigate(1)
                return True
            elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                return True

        return super().eventFilter(obj, event)

    def _navigate(self, direction: int):
        focused = self.focusWidget()
        if focused not in self._fields:
            return
        idx = self._fields.index(focused)
        self._fields[(idx + direction) % len(self._fields)].setFocus()

    # ── Mode switching ───────────────────────────────────────────────────

    def _set_edit_mode(self, enabled: bool):
        for widget in self._fields:
            widget.setEnabled(enabled)
        self.btn_new.setEnabled(not enabled)
        self.btn_modify.setEnabled(not enabled and self.current_client_id is not None)
        self.btn_delete.setEnabled(not enabled and self.current_client_id is not None)
        self.parent_screen.table.setEnabled(not enabled)
        if not enabled:
            if self._active_row:
                self._active_row.set_active(False)
                self._active_row = None

    def _reset_fields_to_placeholder(self):
        self.name.clear()
        self.address.clear()
        self.vatNumber.clear()
        self.phone.clear()
        self.email.clear()

    def _populate_fields(self, client):
        self.name.setText(client.name or "")
        self.address.setText(client.address or "")
        self.vatNumber.setText(client.vatNumber or "")
        self.phone.setText(client.phone or "")
        self.email.setText(client.email or "")
        is_active = getattr(client, "is_active", True)
        self._active_status_label.setText("Active" if is_active else "Inactive")

    # ── Display ──────────────────────────────────────────────────────────

    def show_client(self, client):
        self.current_client_id = client.id
        self._populate_fields(client)
        self._mode = "display"
        self._title_label.setText("Select Client")
        self._set_edit_mode(False)
        self.show()

    def _clear(self):
        self.current_client_id = None
        self._mode = "display"
        self._reset_fields_to_placeholder()
        self._active_status_label.setText("—")
        self._title_label.setText("Select Client")
        self._set_edit_mode(False)

    # ── Actions ──────────────────────────────────────────────────────────

    def _start_new(self):
        if self._mode != "display":
            return
        self.current_client_id = None
        self._mode = "new"
        self._reset_fields_to_placeholder()
        self._active_status_label.setText("Active")
        self._title_label.setText("New Client")
        self._set_edit_mode(True)
        self.name.setFocus()

    def _start_edit(self):
        if self.current_client_id is None or self._mode != "display":
            return
        with get_session() as session:
            client = ClientService.get_by_id(session, self.current_client_id)
        if not client:
            return
        self._populate_fields(client)
        self._mode = "edit"
        self._title_label.setText("Modify Client")
        self._set_edit_mode(True)
        self.name.setFocus()

    def _validate(self) -> bool:
        if not self.name.text().strip():
            self._show_overlay("Client name is required.")
            return False
        if not self.vatNumber.text().strip():
            self._show_overlay("VAT number is required.")
            return False
        return True

    def _collect_data(self) -> dict:
        return {
            "name": self.name.text().strip(),
            "address": self.address.text().strip() or None,
            "vatNumber": self.vatNumber.text().strip(),
            "phone": self.phone.text().strip() or None,
            "email": self.email.text().strip() or None,
        }

    def _on_ok(self):
        if self._mode in ("new", "edit"):
            if not self._validate():
                return
            data = self._collect_data()
            with get_session() as session:
                if self._mode == "new":
                    client = ClientService.create(session, **data)
                    self.current_client_id = client.id
                else:
                    ClientService.update(session, self.current_client_id, **data)
            self._mode = "display"
            self._set_edit_mode(False)
            saved_id = self.current_client_id
            # refresh() rebuilds the table (clearing selection along the way),
            # which resets current_client_id via _on_row_selected -> _clear();
            # saved_id keeps track of what to re-select afterward.
            self.parent_screen.refresh()
            if not self.parent_screen._select_client_row(saved_id):
                with get_session() as session:
                    client = ClientService.get_by_id(session, saved_id)
                if client:
                    self.show_client(client)
                else:
                    self._clear()
        else:
            if self.current_client_id:
                self.parent_screen.selected_client.emit(self.current_client_id, self.name.text())
            self.parent_screen.navigate.emit(0)

    def _on_cancel(self):
        if self._mode == "new":
            self._clear()
        elif self._mode == "edit":
            client_id = self.current_client_id
            self._mode = "display"
            client = None
            if client_id:
                with get_session() as session:
                    client = ClientService.get_by_id(session, client_id)
            if client:
                self.show_client(client)
            else:
                self._clear()
        else:
            self.parent_screen.table.clearSelection()
            self._clear()
        self.parent_screen.search_input.setFocus()

    def _on_delete(self):
        if self.current_client_id is None:
            return
        self.parent_screen._delete_client(self.current_client_id)

    def _on_export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Clients", "clients.csv", "CSV Files (*.csv)")
        if not path:
            return

        with get_session() as session:
            clients = ClientService.get_all(session, active_only=False)
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=CLIENT_CSV_FIELDS)
                writer.writeheader()
                for c in clients:
                    writer.writerow({
                        "name": c.name,
                        "vat": c.vatNumber,
                        "address": c.address,
                        "phone": c.phone or "",
                        "email": c.email or "",
                        "active": 1 if c.is_active else 0,
                    })

        self._show_overlay(f"Exported {len(clients)} client(s).", title="Export complete")

    def _on_import(self):
        path = ""
        file_dialog = FileDialog(parent=self)
        if file_dialog.exec():
            path = file_dialog.path
        if not path:
            return
        if not path.endswith((".csv", ".txt")):
            self._show_overlay("Only csv and txt files allowed to import", title="Import failed", kind="error")
            return
        try:
            with open(path, "r", newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
        except UnicodeDecodeError:
            self._show_overlay(
                "This file isn't valid UTF-8 text. Re-save it as UTF-8 CSV and try again.",
                title="Import failed", kind="error",
            )
            return
        except (OSError, csv.Error) as e:
            self._show_overlay(f"Couldn't read file: {e}", title="Import failed", kind="error")
            return

        clients_added = 0
        clients_skipped = 0
        with (get_session() as session):
            for row in rows:
                try:
                    vat = row.get("vat")
                    email = row.get("email") or None
                    existing = session.query(Client).filter_by(vatNumber=vat).first() if vat else None
                    if not existing and email:
                        existing = session.query(Client).filter_by(email=email).first()
                    if not vat or existing:
                        clients_skipped += 1
                        continue

                    address = ", ".join(part for part in (row.get("Street"), row.get("City"), row.get("Country")) if part) or row.get("address")
                    phone = (row.get("phone") or "").lstrip("'") or None
                    session.add(Client(
                        name=row.get("name"),
                        vatNumber=vat,
                        address=address or None,
                        phone=phone,
                        email=email,
                        is_active=True,
                    ))
                    session.flush()
                    clients_added += 1
                except Exception as e:
                    session.rollback()
                    clients_skipped += 1
                    print(f"Skipped {row.get('name')!r}: {e}")

            session.commit()

        print(f"{clients_added} added, {clients_skipped} skipped")
        self.parent_screen.refresh()

    def _on_search_key(self):
        self.parent_screen.search_input.setFocus()
        self.parent_screen.search_input.setPlaceholderText("Search by name or VAT…")

    def _show_overlay(self, message: str, title: str = "", kind: str = "info"):
        self.overlay.show_message(message, title=title, kind=kind)


class ClientScreen(QWidget):

    navigate = pyqtSignal(int)
    selected_client = pyqtSignal(int, str)

    def __init__(self):
        super().__init__()
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(SPACING_MD)

        # ── Client table (constructed early: ClientDetailPanel references it) ─
        self.table = QTableWidget(0, 5)
        self.table.setObjectName("inventoryTable")
        self.table.setHorizontalHeaderLabels([
            "Name", "Address", "VAT", "Phone", "Email"
        ])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._on_row_selected)

        # ── Client detail panel (always visible) ───────────────────────────
        self.detail_panel = ClientDetailPanel(self)
        layout.addWidget(self.detail_panel)

        # ── Search / filter bar ─────────────────────────────────────────────
        toolbar = QHBoxLayout()

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search by name or VAT…")
        self.search_input.setFixedHeight(INPUT_HEIGHT)
        self.search_input.textChanged.connect(self.refresh)
        toolbar.addWidget(self.search_input, stretch=1)

        layout.addLayout(toolbar)

        layout.addWidget(self.table, stretch=1)

        # ── Summary row ───────────────────────────────────────────────────────
        self.summary_label = QLabel()
        layout.addWidget(self.summary_label)

        self._client_cache = {}

    def refresh(self):
        with get_session() as session:
            query = self.search_input.text().strip()
            if query:
                clients = ClientService.search(session, query)
            else:
                clients = ClientService.get_all(session)

            self._populate_table(clients, session)
            self.summary_label.setText(f"{len(clients)} client(s) shown")
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
            self.table.setItem(row, 2, QTableWidgetItem(c.vatNumber or ""))
            self.table.setItem(row, 3, QTableWidgetItem(c.phone or ""))
            self.table.setItem(row, 4, QTableWidgetItem(c.email or ""))

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
        self.detail_panel._start_new()

    def _edit_client(self, client_id: int):
        self.detail_panel.current_client_id = client_id
        self.detail_panel._start_edit()

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

    def _select_client_row(self, client_id: int) -> bool:
        """Selects client_id's row in the table if it's in the current
        (possibly filtered) view. Returns whether it found one."""
        for row, cid in self._client_cache.items():
            if cid == client_id:
                self.table.selectRow(row)
                return True
        return False
