"""
Tests for app.ui.inventory_screen: InventoryScreen (table/search/filters)
and ArticleDetailPanel (new/edit/delete/picker/stock-adjustment/export/import flows).
"""
import csv

import pytest
from PyQt6.QtWidgets import QMessageBox, QFileDialog

from app.ui.inventory_screen import InventoryScreen
from app.ui.dialogs.stock_adjustment_dialog import StockAdjustmentDialog
from app.core.product_service import ProductService
from app.core.database import get_session
from app.models.models import Product


@pytest.fixture
def screen(qtbot, patched_db):
    s = InventoryScreen()
    qtbot.addWidget(s)
    return s


def _add_product(**overrides):
    data = {"name": "Product A", "price": 5.0, "stock_quantity": 10, "min_stock_level": 5}
    data.update(overrides)
    with get_session() as session:
        p = ProductService.create(session, **data)
        return p.id


# ── Table / filters ──────────────────────────────────────────────────────

def test_empty_state(screen):
    assert screen.table.rowCount() == 0
    assert screen.summary_label.text() == "0 product(s) shown"


def test_category_filter_seeded_with_default_categories(screen):
    labels = [screen.category_filter.itemText(i) for i in range(screen.category_filter.count())]
    assert labels[0] == "All Categories"
    assert "Bakery" in labels


def test_refresh_populates_table(screen):
    _add_product(name="Milk", barcode="111")
    _add_product(name="Bread", barcode="222")
    screen.refresh()
    assert screen.table.rowCount() == 2


def test_search_filters_table(screen):
    _add_product(name="Cola", barcode="500123")
    _add_product(name="Water", barcode="999999")
    screen.refresh()

    screen.search_input.setText("Cola")
    assert screen.table.rowCount() == 1
    assert screen.table.item(0, 1).text() == "Cola"


def test_low_stock_filter(screen):
    _add_product(name="Low", stock_quantity=1, min_stock_level=5)
    _add_product(name="Plenty", stock_quantity=50, min_stock_level=5)
    screen.refresh()

    screen.low_stock_btn.setChecked(True)
    assert screen.table.rowCount() == 1
    assert screen.table.item(0, 1).text() == "Low"


def test_category_filter_restricts_products(screen):
    with get_session() as session:
        cat = ProductService.create_category(session, "Special Cat")
        cat_id = cat.id
    _add_product(name="InCat", category_id=cat_id)
    _add_product(name="NoCat")
    screen.refresh()

    idx = screen.category_filter.findData(cat_id)
    screen.category_filter.setCurrentIndex(idx)
    assert screen.table.rowCount() == 1
    assert screen.table.item(0, 1).text() == "InCat"


# ── Row selection ────────────────────────────────────────────────────────

def test_selecting_row_shows_detail_panel(screen):
    _add_product(name="Selectable", price=9.99, barcode="777")
    screen.refresh()
    screen.table.selectRow(0)

    panel = screen.detail_panel
    assert panel.name.text() == "Selectable"
    assert panel.barcode.text() == "777"
    assert panel.price.value() == 9.99


# ── New product flow ─────────────────────────────────────────────────────

def test_new_product_happy_path_persists(screen):
    panel = screen.detail_panel
    panel._start_new()
    assert panel._mode == "new"

    panel.name.setText("Brand New")
    panel.price.setValue(3.50)
    panel._on_ok()

    with get_session() as session:
        found = session.query(Product).filter_by(name="Brand New").first()
    assert found is not None
    assert found.price == 3.50
    assert panel._mode == "display"


def test_new_product_validation_blocks_empty_name(screen):
    panel = screen.detail_panel
    panel._start_new()
    panel.price.setValue(1.0)
    panel._on_ok()

    assert panel._mode == "new"
    with get_session() as session:
        assert ProductService.get_all(session) == []


def test_new_product_validation_blocks_zero_price(screen):
    panel = screen.detail_panel
    panel._start_new()
    panel.name.setText("No Price")
    panel.price.setValue(0.0)
    panel._on_ok()

    with get_session() as session:
        assert ProductService.get_all(session) == []


def test_new_product_picker_sets_tax_unit_category(screen):
    with get_session() as session:
        cat = ProductService.create_category(session, "Cat X")
        cat_id = cat.id
    screen.detail_panel._load_categories()

    panel = screen.detail_panel
    panel._start_new()
    panel.name.setText("Taxed Item")
    panel.price.setValue(1.0)

    panel._active_picker = "tax"
    panel._pick("6", "6 %")
    panel._active_picker = "unit"
    panel._pick("kg", "kg")
    panel._active_picker = "category"
    panel._pick(cat_id, "Cat X")

    panel._on_ok()

    with get_session() as session:
        product = session.query(Product).filter_by(name="Taxed Item").first()
    assert product.tax == 6
    assert product.unit == "kg"
    assert product.category_id == cat_id


def test_new_product_cancel_discards(screen):
    panel = screen.detail_panel
    panel._start_new()
    panel.name.setText("Discard Me")
    panel._on_cancel()

    assert panel._mode == "display"
    with get_session() as session:
        assert ProductService.get_all(session) == []


# ── Edit flow ────────────────────────────────────────────────────────────

def test_edit_product_updates_existing(screen):
    pid = _add_product(name="Old", price=1.0)
    screen.refresh()
    screen.table.selectRow(0)

    panel = screen.detail_panel
    panel._start_edit()
    assert panel._mode == "edit"
    panel.name.setText("Updated")
    panel.price.setValue(2.5)
    panel._on_ok()

    with get_session() as session:
        product = ProductService.get_by_id(session, pid)
    assert product.name == "Updated"
    assert product.price == 2.5


# ── Delete flow ──────────────────────────────────────────────────────────

def test_delete_product_confirmed_deactivates(screen, monkeypatch):
    pid = _add_product(name="ToDelete")
    screen.refresh()

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **kw: QMessageBox.StandardButton.Yes))
    screen._delete_product(pid)

    with get_session() as session:
        product = ProductService.get_by_id(session, pid)
    assert product.is_active is False


def test_delete_product_cancelled_keeps_active(screen, monkeypatch):
    pid = _add_product(name="KeepMe")
    screen.refresh()

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **kw: QMessageBox.StandardButton.No))
    screen._delete_product(pid)

    with get_session() as session:
        product = ProductService.get_by_id(session, pid)
    assert product.is_active is True


# ── Stock adjustment ─────────────────────────────────────────────────────

def test_adjust_stock_applies_dialog_data(screen, monkeypatch):
    pid = _add_product(name="Stocked", stock_quantity=10)

    monkeypatch.setattr(StockAdjustmentDialog, "exec", lambda self: True)
    monkeypatch.setattr(
        StockAdjustmentDialog, "get_data",
        lambda self: {"quantity_change": 5, "movement_type": "purchase", "notes": None},
    )

    screen._adjust_stock(pid)

    with get_session() as session:
        product = ProductService.get_by_id(session, pid)
    assert product.stock_quantity == 15


def test_adjust_stock_cancelled_dialog_makes_no_change(screen, monkeypatch):
    pid = _add_product(name="Stocked", stock_quantity=10)
    monkeypatch.setattr(StockAdjustmentDialog, "exec", lambda self: False)

    screen._adjust_stock(pid)

    with get_session() as session:
        product = ProductService.get_by_id(session, pid)
    assert product.stock_quantity == 10


# ── Barcode scan ─────────────────────────────────────────────────────────

def test_barcode_scan_known_barcode_selects_row(screen):
    _add_product(name="Scanned", barcode="123456789")
    screen.refresh()

    screen.search_input.setText("123456789")
    screen._on_barcode_scan()

    assert screen.detail_panel.name.text() == "Scanned"
    assert screen.search_input.text() == ""


def test_barcode_scan_unknown_barcode_shows_overlay(screen, qtbot):
    screen.search_input.setText("nonexistent")
    screen._on_barcode_scan()
    assert not screen.detail_panel.overlay.isHidden()


def test_barcode_scan_ignored_while_editing(screen):
    screen.detail_panel._start_new()
    screen.search_input.setText("123456789")
    screen._on_barcode_scan()
    # still in "new" mode, search text untouched by the scan handler
    assert screen.detail_panel._mode == "new"


# ── Picker page swap ─────────────────────────────────────────────────────

def test_show_picker_and_table_page_swap(screen):
    screen._show_picker_page()
    assert screen.table_stack.currentWidget() is screen.detail_panel.picker_page

    screen._show_table_page()
    assert screen.table_stack.currentWidget() is screen.table


# ── CSV export ───────────────────────────────────────────────────────────

def test_export_writes_all_products_including_inactive(screen, monkeypatch, tmp_path):
    out_path = tmp_path / "articles.csv"
    with get_session() as session:
        cat = ProductService.create_category(session, "Export Cat")
        cat_id = cat.id
    active_id = _add_product(name="Active One", barcode="EXP1", price=2.5, tax=6,
                              unit="pcs", stock_quantity=10, min_stock_level=3, category_id=cat_id)
    inactive_id = _add_product(name="Inactive One", barcode="EXP2")
    with get_session() as session:
        ProductService.deactivate(session, inactive_id)

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **kw: (str(out_path), "")))
    screen.detail_panel._on_export()

    assert out_path.exists()
    with open(out_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2  # active AND inactive both exported
    row_by_barcode = {r["barcode"]: r for r in rows}
    assert row_by_barcode["EXP1"]["name"] == "Active One"
    assert row_by_barcode["EXP1"]["price"] == "2.5"
    assert row_by_barcode["EXP1"]["tax"] == "6"
    assert row_by_barcode["EXP1"]["category"] == "Export Cat"
    assert row_by_barcode["EXP2"]["name"] == "Inactive One"


def test_export_cancelled_dialog_is_noop(screen, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **kw: ("", "")))
    screen.detail_panel._on_export()  # must not raise, and there's nothing to assert on disk


# ── CSV import ───────────────────────────────────────────────────────────

class _FakeFileDialog:
    def __init__(self, path, parent=None):
        self.path = path

    def exec(self):
        return True


def _import_from(screen, monkeypatch, path):
    monkeypatch.setattr(
        "app.ui.inventory_screen.FileDialog",
        lambda parent=None: _FakeFileDialog(str(path)),
    )
    screen.detail_panel._on_import()


def test_import_adds_new_articles_and_skips_barcode_duplicates(screen, monkeypatch, tmp_path):
    _add_product(name="Existing", barcode="DUPBC")

    csv_path = tmp_path / "articles.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["barcode", "name", "price", "tax", "unit", "stock_quantity", "min_stock_level", "category"])
        writer.writeheader()
        writer.writerow({"barcode": "NEWBC", "name": "New Article", "price": "3.5", "tax": "21",
                          "unit": "pcs", "stock_quantity": "20", "min_stock_level": "4", "category": ""})
        writer.writerow({"barcode": "DUPBC", "name": "Should Be Skipped", "price": "1", "tax": "0",
                          "unit": "pcs", "stock_quantity": "1", "min_stock_level": "1", "category": ""})

    _import_from(screen, monkeypatch, csv_path)

    with get_session() as session:
        names = {p.name for p in ProductService.get_all(session, active_only=False)}
    assert "New Article" in names
    assert "Should Be Skipped" not in names
    assert "Existing" in names


def test_import_resolves_category_by_name(screen, monkeypatch, tmp_path):
    csv_path = tmp_path / "articles.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["barcode", "name", "price", "tax", "unit", "stock_quantity", "min_stock_level", "category"])
        writer.writeheader()
        writer.writerow({"barcode": "CATBC", "name": "Categorized", "price": "1", "tax": "0",
                          "unit": "pcs", "stock_quantity": "0", "min_stock_level": "5", "category": "Bakery"})

    _import_from(screen, monkeypatch, csv_path)

    with get_session() as session:
        product = session.query(Product).filter_by(barcode="CATBC").first()
        assert product.category is not None
        assert product.category.name == "Bakery"


def test_import_defaults_missing_numeric_fields(screen, monkeypatch, tmp_path):
    csv_path = tmp_path / "articles.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["barcode", "name", "price", "tax", "unit", "stock_quantity", "min_stock_level", "category"])
        writer.writeheader()
        writer.writerow({"barcode": "", "name": "Bare Minimum", "price": "", "tax": "",
                          "unit": "", "stock_quantity": "", "min_stock_level": "", "category": ""})

    _import_from(screen, monkeypatch, csv_path)

    with get_session() as session:
        product = session.query(Product).filter_by(name="Bare Minimum").first()
    assert product.price == 0.0
    assert product.tax == 0
    assert product.unit == "pcs"
    assert product.stock_quantity == 0.0
    assert product.min_stock_level == 5.0
    assert product.barcode is None


def test_import_skips_rows_without_a_name(screen, monkeypatch, tmp_path):
    csv_path = tmp_path / "articles.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["barcode", "name", "price", "tax", "unit", "stock_quantity", "min_stock_level", "category"])
        writer.writeheader()
        writer.writerow({"barcode": "NB1", "name": "", "price": "1", "tax": "0",
                          "unit": "pcs", "stock_quantity": "0", "min_stock_level": "5", "category": ""})

    _import_from(screen, monkeypatch, csv_path)

    with get_session() as session:
        assert ProductService.get_all(session, active_only=False) == []


def test_import_no_path_selected_is_noop(screen, monkeypatch):
    monkeypatch.setattr(
        "app.ui.inventory_screen.FileDialog",
        lambda parent=None: _FakeFileDialog(""),
    )
    screen.detail_panel._on_import()
    with get_session() as session:
        assert ProductService.get_all(session, active_only=False) == []


def test_import_bad_encoding_shows_error_and_imports_nothing(screen, monkeypatch, tmp_path):
    csv_path = tmp_path / "articles.csv"
    # Latin-1 bytes containing an accented char that isn't valid UTF-8.
    csv_path.write_bytes("name,barcode\nCaf\xe9,BC1\n".encode("latin-1"))

    _import_from(screen, monkeypatch, csv_path)

    assert not screen.detail_panel.overlay.isHidden()
    with get_session() as session:
        assert ProductService.get_all(session, active_only=False) == []


def test_import_overflowing_tax_defaults_instead_of_aborting_batch(screen, monkeypatch, tmp_path):
    csv_path = tmp_path / "articles.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["barcode", "name", "price", "tax", "unit", "stock_quantity", "min_stock_level", "category"])
        writer.writeheader()
        # tax="1e400" parses as float('inf'); int(float('inf')) raises OverflowError,
        # which used to escape the row loop and abort the whole import.
        writer.writerow({"barcode": "OVF1", "name": "Overflowing Tax", "price": "1", "tax": "1e400",
                          "unit": "pcs", "stock_quantity": "0", "min_stock_level": "5", "category": ""})
        writer.writerow({"barcode": "OVF2", "name": "After Bad Row", "price": "1", "tax": "0",
                          "unit": "pcs", "stock_quantity": "0", "min_stock_level": "5", "category": ""})

    _import_from(screen, monkeypatch, csv_path)

    with get_session() as session:
        names = {p.name for p in ProductService.get_all(session, active_only=False)}
        overflowing = session.query(Product).filter_by(barcode="OVF1").first()
    assert "Overflowing Tax" in names
    assert overflowing.tax == 0
    assert "After Bad Row" in names


def test_export_then_import_round_trip_restores_catalog(screen, monkeypatch, tmp_path):
    """The intended real-world use: export the current catalog, wipe the
    products table (e.g. a fresh/reset database), then re-import the CSV
    and end up with the same articles back."""
    out_path = tmp_path / "articles.csv"
    with get_session() as session:
        cat = ProductService.create_category(session, "Round Trip Cat")
        cat_id = cat.id
    _add_product(name="Round Trip Item", barcode="RT1", price=4.25, tax=21,
                 unit="kg", stock_quantity=7, min_stock_level=2, category_id=cat_id)

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **kw: (str(out_path), "")))
    screen.detail_panel._on_export()

    # Simulate "delete the database and start over": wipe all products.
    with get_session() as session:
        session.query(Product).delete()
        session.commit()

    _import_from(screen, monkeypatch, out_path)

    with get_session() as session:
        restored = session.query(Product).filter_by(barcode="RT1").first()
        assert restored is not None
        assert restored.name == "Round Trip Item"
        assert restored.price == 4.25
        assert restored.tax == 21
        assert restored.unit == "kg"
        assert restored.stock_quantity == 7
        assert restored.min_stock_level == 2
        assert restored.category.name == "Round Trip Cat"
