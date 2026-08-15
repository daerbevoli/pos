"""
Tests for app.ui.client_screen: ClientScreen (table/search/summary) and
ClientDetailPanel (new/edit/delete/import flows).

Uses the patched_db fixture so all get_session() calls inside the screen
hit an isolated in-memory database.
"""
import csv

import pytest
from PyQt6.QtWidgets import QMessageBox

from app.ui.client_screen import ClientScreen
from app.core.client_service import ClientService
from app.core.database import get_session


@pytest.fixture
def screen(qtbot, patched_db):
    s = ClientScreen()
    qtbot.addWidget(s)
    return s


def _add_client(**overrides):
    data = {"name": "Client A", "vatNumber": "V1"}
    data.update(overrides)
    data.setdefault("address", f"1 Main St, {data['name']}")
    with get_session() as session:
        client = ClientService.create(session, **data)
        return client.id


# ── Table / search ───────────────────────────────────────────────────────

def test_empty_state(screen):
    assert screen.table.rowCount() == 0
    assert screen.summary_label.text() == "0 client(s) shown"


def test_refresh_populates_table(screen):
    _add_client(name="Acme", vatNumber="V1")
    _add_client(name="Beta Corp", vatNumber="V2")
    screen.refresh()

    assert screen.table.rowCount() == 2
    names = {screen.table.item(r, 0).text() for r in range(screen.table.rowCount())}
    assert names == {"Acme", "Beta Corp"}
    assert screen.summary_label.text() == "2 client(s) shown"


def test_search_filters_table(screen, qtbot):
    _add_client(name="Fruit Market", vatNumber="V1")
    _add_client(name="Other Shop", vatNumber="V2")
    screen.refresh()

    screen.search_input.setText("Fruit")
    assert screen.table.rowCount() == 1
    assert screen.table.item(0, 0).text() == "Fruit Market"


def test_deactivated_clients_excluded_from_default_view(screen):
    cid = _add_client(name="Hidden")
    with get_session() as session:
        ClientService.deactivate(session, cid)
    screen.refresh()
    assert screen.table.rowCount() == 0


# ── Row selection ────────────────────────────────────────────────────────

def test_selecting_row_shows_detail_panel(screen):
    _add_client(name="Selectable", vatNumber="VSEL", phone="123")
    screen.refresh()
    screen.table.selectRow(0)

    panel = screen.detail_panel
    assert panel.name.text() == "Selectable"
    assert panel.vatNumber.text() == "VSEL"
    assert panel.phone.text() == "123"
    assert panel.current_client_id is not None


def test_clearing_current_cell_clears_panel(screen):
    _add_client(name="X")
    screen.refresh()
    screen.table.selectRow(0)
    assert screen.detail_panel.current_client_id is not None

    screen.table.setCurrentCell(-1, -1)
    assert screen.detail_panel.current_client_id is None


# ── New client flow ──────────────────────────────────────────────────────

def test_new_client_happy_path_persists(screen):
    panel = screen.detail_panel
    panel._start_new()
    assert panel._mode == "new"

    panel.name.setText("Brand New")
    panel.address.setText("1 Main St")
    panel.vatNumber.setText("VNEW")
    panel._on_ok()
    assert panel._mode == "display"

    with get_session() as session:
        found = ClientService.get_by_name(session, "Brand New")
    assert found is not None
    assert found.vatNumber == "VNEW"

def test_new_client_validation_blocks_empty_name(screen):
    panel = screen.detail_panel
    panel._start_new()
    panel.name.setText("")
    panel.address.setText("1 Main St")
    panel.vatNumber.setText("V1")

    panel._on_ok()

    assert panel._mode == "new"  # still editing — nothing was saved
    with get_session() as session:
        assert ClientService.get_all(session) == []


def test_new_client_validation_blocks_empty_address(screen):
    panel = screen.detail_panel
    panel._start_new()
    panel.name.setText("Has Name")
    panel.address.setText("")
    panel.vatNumber.setText("V1")

    panel._on_ok()

    assert panel._mode == "new"  # still editing — nothing was saved
    with get_session() as session:
        assert ClientService.get_all(session) == []


def test_new_client_validation_blocks_empty_vat(screen):
    panel = screen.detail_panel
    panel._start_new()
    panel.name.setText("Has Name")
    panel.address.setText("1 Main St")
    panel.vatNumber.setText("")

    panel._on_ok()
    assert panel._mode != "display"

    with get_session() as session:
        assert ClientService.get_all(session) == []


def test_new_client_cancel_discards_and_clears(screen):
    panel = screen.detail_panel
    panel._start_new()
    panel.name.setText("Discard Me")
    panel._on_cancel()

    assert panel._mode == "display"
    with get_session() as session:
        assert ClientService.get_all(session) == []


def test_start_new_ignored_while_already_editing(screen):
    panel = screen.detail_panel
    panel._start_new()
    panel.name.setText("First")
    panel._start_new()  # should be a no-op since mode != "display"
    assert panel.name.text() == "First"


# ── Edit flow ────────────────────────────────────────────────────────────

def test_edit_client_updates_existing_row(screen):
    cid = _add_client(name="Old Name", vatNumber="V1")
    screen.refresh()
    screen.table.selectRow(0)

    panel = screen.detail_panel
    panel._start_edit()
    assert panel._mode == "edit"
    panel.name.setText("Updated Name")
    panel._on_ok()

    with get_session() as session:
        client = ClientService.get_by_id(session, cid)
    assert client.name == "Updated Name"


def test_edit_cancel_restores_original_values(screen):
    cid = _add_client(name="Original", vatNumber="V1")
    screen.refresh()
    screen.table.selectRow(0)

    panel = screen.detail_panel
    panel._start_edit()
    panel.name.setText("Changed But Not Saved")
    panel._on_cancel()

    assert panel.name.text() == "Original"
    with get_session() as session:
        assert ClientService.get_by_id(session, cid).name == "Original"


# ── Delete flow ──────────────────────────────────────────────────────────

def test_delete_client_confirmed_deactivates(screen, monkeypatch):
    cid = _add_client(name="ToDelete")
    screen.refresh()

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **kw: QMessageBox.StandardButton.Yes))
    screen._delete_client(cid)

    with get_session() as session:
        client = ClientService.get_by_id(session, cid)
    assert client.is_active is False
    assert screen.table.rowCount() == 0


def test_delete_client_cancelled_keeps_active(screen, monkeypatch):
    cid = _add_client(name="KeepMe")
    screen.refresh()

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **kw: QMessageBox.StandardButton.No))
    screen._delete_client(cid)

    with get_session() as session:
        client = ClientService.get_by_id(session, cid)
    assert client.is_active is True


# ── CSV import ───────────────────────────────────────────────────────────

class _FakeFileDialog:
    def __init__(self, path, parent=None):
        self._path = path
        self.path = path

    def exec(self):
        return True


def test_import_csv_adds_new_clients_and_skips_duplicates(screen, monkeypatch, tmp_path):
    _add_client(name="Existing", vatNumber="DUPVAT")

    csv_path = tmp_path / "clients.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "vat", "email", "phone", "Street", "City", "Country"])
        writer.writeheader()
        writer.writerow({"name": "New Client", "vat": "NEWVAT", "email": "new@x.com",
                          "phone": "'0123", "Street": "Main St", "City": "Town", "Country": "BE"})
        writer.writerow({"name": "Dupe", "vat": "DUPVAT", "email": "", "phone": "", "Street": "", "City": "", "Country": ""})
        writer.writerow({"name": "No Vat", "vat": "", "email": "", "phone": "", "Street": "", "City": "", "Country": ""})

    monkeypatch.setattr(
        "app.ui.client_screen.FileDialog",
        lambda parent=None: _FakeFileDialog(str(csv_path)),
    )

    screen.detail_panel._on_import()

    with get_session() as session:
        names = {c.name for c in ClientService.get_all(session)}
    assert "New Client" in names
    assert "Existing" in names
    assert "No Vat" not in names


def test_import_csv_no_path_selected_is_noop(screen, monkeypatch):
    monkeypatch.setattr(
        "app.ui.client_screen.FileDialog",
        lambda parent=None: _FakeFileDialog(""),
    )
    screen.detail_panel._on_import()
    with get_session() as session:
        assert ClientService.get_all(session) == []


def test_import_csv_bad_encoding_shows_error_and_imports_nothing(screen, monkeypatch, tmp_path):
    csv_path = tmp_path / "clients.csv"
    # Latin-1 bytes containing an accented char that isn't valid UTF-8.
    csv_path.write_bytes("name,vat\nCaf\xe9,VAT1\n".encode("latin-1"))

    monkeypatch.setattr(
        "app.ui.client_screen.FileDialog",
        lambda parent=None: _FakeFileDialog(str(csv_path)),
    )

    screen.detail_panel._on_import()

    assert not screen.detail_panel.overlay.isHidden()
    with get_session() as session:
        assert ClientService.get_all(session) == []


def test_import_csv_row_error_does_not_abort_batch(screen, monkeypatch, tmp_path):
    import app.ui.client_screen as client_screen_module

    real_init = client_screen_module.Client.__init__

    def flaky_init(self, *args, **kwargs):
        if kwargs.get("vatNumber") == "BADVAT":
            raise RuntimeError("boom")
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(client_screen_module.Client, "__init__", flaky_init)

    csv_path = tmp_path / "clients.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "vat", "email", "phone", "Street", "City", "Country"])
        writer.writeheader()
        writer.writerow({"name": "Bad Row", "vat": "BADVAT", "email": "", "phone": "", "Street": "Main St", "City": "Town", "Country": "BE"})
        writer.writerow({"name": "Good Row", "vat": "GOODVAT", "email": "", "phone": "", "Street": "Main St", "City": "Town", "Country": "BE"})

    monkeypatch.setattr(
        "app.ui.client_screen.FileDialog",
        lambda parent=None: _FakeFileDialog(str(csv_path)),
    )

    screen.detail_panel._on_import()

    with get_session() as session:
        names = {c.name for c in ClientService.get_all(session)}
    assert "Good Row" in names
    assert "Bad Row" not in names
