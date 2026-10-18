"""Tests for app.core.inventory_report_service.InventoryReportService."""
import csv

import pytest

from app.core.inventory_report_service import InventoryLine, InventoryReportService
from app.core.product_service import ProductService


def _make_product(session, **overrides):
    data = {"name": "Product A", "price": 1.0}
    data.update(overrides)
    return ProductService.create(session, **data)


def test_snapshot_lists_active_products_by_barcode_with_total(db_session):
    _make_product(db_session, name="Bread", barcode="5400000000002", price=2.50, stock_quantity=-3)
    _make_product(db_session, name="Apple", barcode="5400000000001", price=1.25, stock_quantity=40)
    _make_product(db_session, name="Loose", price=0.50)
    gone = _make_product(db_session, name="Gone", barcode="5400000000000", price=9.99)
    ProductService.deactivate(db_session, gone.id)

    snapshot = InventoryReportService.take_snapshot(db_session)

    # Sorted by barcode; a product without one comes last with an empty ID.
    assert [(l.barcode, l.name, l.price) for l in snapshot.lines] == [
        ("5400000000001", "Apple", 1.25), ("5400000000002", "Bread", 2.50), ("", "Loose", 0.50),
    ]
    # Every product counts as one, whatever its stock.
    assert snapshot.total == 4.25


def test_snapshot_leaves_out_open_price_products(db_session):
    _make_product(db_session, name="Fixed", barcode="1", price=4.0)
    _make_product(db_session, name="Open", barcode="2", price=7.0, is_open_price=True)
    snapshot = InventoryReportService.take_snapshot(db_session)
    assert [l.name for l in snapshot.lines] == ["Fixed"]
    assert snapshot.total == 4.0


def test_snapshot_does_not_change_after_products_change(db_session):
    p = _make_product(db_session, name="Apple", price=1.0)
    snapshot = InventoryReportService.take_snapshot(db_session)
    ProductService.update(db_session, p.id, price=5.0)
    _make_product(db_session, name="Later", price=3.0)
    assert snapshot.total == 1.0
    assert len(snapshot.lines) == 1


@pytest.mark.parametrize("price, rate, excl", [
    (1.21, 21, 1.00), (2.12, 6, 2.00), (1.12, 12, 1.00), (3.00, 0, 3.00), (0.0, 21, 0.0),
])
def test_line_price_excl_vat(price, rate, excl):
    assert InventoryLine("", "X", rate, price).price_excl_vat == excl


def test_write_csv_has_columns_rows_and_totals(db_session, tmp_path):
    _make_product(db_session, name="Apple", barcode="1001", price=1.21, tax=21)
    _make_product(db_session, name="Bread, white", barcode="1002", price=2.12, tax=6)
    _make_product(db_session, name="Book", barcode="1003", price=5.00, tax=0)
    path = tmp_path / "inventory.csv"

    InventoryReportService.write_csv(str(path), InventoryReportService.take_snapshot(db_session))

    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows == [
        ["Barcode", "Product", "VAT %", "Excl. VAT", "Price"],
        ["1001", "Apple", "21", "1.00", "1.21"],
        ["1002", "Bread, white", "6", "2.00", "2.12"],
        ["1003", "Book", "0", "5.00", "5.00"],
        ["", "Total", "", "8.00", "8.33"],
    ]


def test_write_pdf_creates_pdf(db_session, tmp_path):
    for i in range(80):  # spans more than one page
        _make_product(db_session, name=f"Product <{i}> & co", barcode=f"54{i:011d}", price=1.0)
    path = tmp_path / "inventory.pdf"

    InventoryReportService.write_pdf(str(path), InventoryReportService.take_snapshot(db_session))

    assert path.read_bytes().startswith(b"%PDF")


def test_write_pdf_with_no_products(db_session, tmp_path):
    path = tmp_path / "inventory.pdf"
    InventoryReportService.write_pdf(str(path), InventoryReportService.take_snapshot(db_session))
    assert path.read_bytes().startswith(b"%PDF")
