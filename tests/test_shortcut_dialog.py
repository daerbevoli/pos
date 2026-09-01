"""
Tests for app.ui.dialogs.shortcut_dialog.ShortcutDialog.

The dialog reads the product catalogue through ProductService (which calls
get_session() internally), so every test uses the patched_db fixture.
"""
import pytest
from PyQt6.QtCore import Qt

from app.ui.dialogs.shortcut_dialog import ShortcutDialog
from app.core.database import get_session
from app.core.product_service import ProductService


@pytest.fixture
def products(patched_db):
    with get_session() as session:
        return {
            name: ProductService.create(session, name=name, price=1.0, tax=21).id
            for name in ["Cola 33cl", "Cola 50cl", "Water", "Bread"]
        }


def _make(qtbot, **kwargs):
    d = ShortcutDialog(**kwargs)
    qtbot.addWidget(d)
    return d


def test_prefills_name_and_items(qtbot, products):
    d = _make(qtbot, sc_name="Lunch", product_ids=[products["Water"], products["Bread"]])
    assert d.name_edit.text() == "Lunch"
    assert d.product_ids == [products["Water"], products["Bread"]]
    assert d.selected_list.count() == 2
    assert d.selected_list.item(0).text() == "1.  Water"


def test_search_lists_matches_and_flags_already_added(qtbot, products):
    d = _make(qtbot, product_ids=[products["Cola 33cl"]])
    d.search_edit.setText("Cola")
    rows = [d.results_list.item(i) for i in range(d.results_list.count())]
    assert len(rows) == 2
    added = next(r for r in rows if r.data(Qt.ItemDataRole.UserRole) == products["Cola 33cl"])
    assert not (added.flags() & Qt.ItemFlag.ItemIsEnabled)
    assert "(added)" in added.text()


def test_add_from_results_appends(qtbot, products):
    d = _make(qtbot)
    d.search_edit.setText("Water")
    d.results_list.setCurrentRow(0)
    d._add_selected_result()
    assert d.product_ids == [products["Water"]]


def test_add_ignores_disabled_already_added_row(qtbot, products):
    d = _make(qtbot, product_ids=[products["Water"]])
    d.search_edit.setText("Water")
    d.results_list.setCurrentRow(0)
    d._add_selected_result()
    assert d.product_ids == [products["Water"]]  # unchanged


def test_remove_and_reorder(qtbot, products):
    ids = [products["Cola 33cl"], products["Water"], products["Bread"]]
    d = _make(qtbot, product_ids=list(ids))

    d.selected_list.setCurrentRow(2)
    d._move(-1)
    assert d.product_ids == [ids[0], ids[2], ids[1]]

    d.selected_list.setCurrentRow(0)
    d._remove_selected_item()
    assert d.product_ids == [ids[2], ids[1]]


def test_move_at_edges_is_noop(qtbot, products):
    ids = [products["Water"], products["Bread"]]
    d = _make(qtbot, product_ids=list(ids))
    d.selected_list.setCurrentRow(0)
    d._move(-1)
    assert d.product_ids == ids


def test_ok_rejects_blank_name(qtbot, products, monkeypatch):
    warned = []
    monkeypatch.setattr("app.ui.dialogs.shortcut_dialog.QMessageBox.warning",
                        lambda *a, **kw: warned.append(a))
    d = _make(qtbot)
    d.name_edit.setText("   ")
    d.on_ok()
    assert warned and d.result() != d.DialogCode.Accepted


def test_ok_rejects_duplicate_name(qtbot, products, monkeypatch):
    warned = []
    monkeypatch.setattr("app.ui.dialogs.shortcut_dialog.QMessageBox.warning",
                        lambda *a, **kw: warned.append(a))
    d = _make(qtbot, existing_names=["Lunch", "Dinner"])
    d.name_edit.setText("dinner")
    d.on_ok()
    assert warned


def test_ok_allows_keeping_original_name_when_editing(qtbot, products):
    d = _make(qtbot, sc_name="Lunch", existing_names=["Lunch", "Dinner"])
    d.on_ok()
    assert d.sc_name == "Lunch"
    assert d.result() == d.DialogCode.Accepted


def test_deleted_product_id_shows_placeholder(qtbot, patched_db):
    d = _make(qtbot, product_ids=[4242])
    assert "deleted product #4242" in d.selected_list.item(0).text()
