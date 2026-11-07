"""Tests for the shared CSV import (app.core.csv_import) and the per-service row rules."""
import pytest

from app.core.client.client_service import ClientService
from app.core.csv_import import ImportFileError, read_csv_rows
from app.core.inventory.product_service import ProductService
from app.models.models import Product


def _write(tmp_path, text, name="import.csv"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_read_csv_rows_lowercases_and_trims_headers(tmp_path):
    path = _write(tmp_path, "Name , VAT,Street\nAcme,BE1,Main St\n")
    assert read_csv_rows(path) == [{"name": "Acme", "vat": "BE1", "street": "Main St"}]


def test_read_csv_rows_drops_cells_beyond_the_header(tmp_path):
    path = _write(tmp_path, "name\nAcme,extra\n")
    assert read_csv_rows(path) == [{"name": "Acme"}]


def test_read_csv_rows_refuses_other_file_types(tmp_path):
    path = _write(tmp_path, "name\nAcme\n", name="clients.xlsx")
    with pytest.raises(ImportFileError, match="Only csv and txt"):
        read_csv_rows(path)


def test_read_csv_rows_refuses_non_utf8(tmp_path):
    path = tmp_path / "clients.csv"
    path.write_bytes("name\nCaf\xe9\n".encode("latin-1"))
    with pytest.raises(ImportFileError, match="UTF-8"):
        read_csv_rows(str(path))


def test_client_import_reads_capitalised_headers(db_session, tmp_path):
    path = _write(tmp_path, "Name,VAT,Street,Zip,City,Country\nAcme,BE0234567873,Main St,1000,Brussels,BE\n")

    assert ClientService.import_rows(db_session, read_csv_rows(path)) == (1, 0)
    client = ClientService.get_all(db_session)[0]
    assert (client.name, client.street, client.zip_code, client.city, client.country) == \
        ("Acme", "Main St", "1000", "Brussels", "BE")


def test_client_import_skips_a_vat_number_already_in_the_same_file(db_session):
    row = {"name": "Acme", "vat": "BE0234567873", "street": "Main St"}
    assert ClientService.import_rows(db_session, [row, dict(row, name="Acme again")]) == (1, 1)


def test_product_import_falls_back_on_unreadable_numbers(db_session):
    rows = [{"name": "Odd", "price": "abc", "tax": "inf", "stock_quantity": "nan", "min_stock_level": "x"}]

    assert ProductService.import_rows(db_session, rows) == (1, 0)
    product = db_session.query(Product).filter_by(name="Odd").one()
    assert (product.price, product.is_open_price, product.tax, product.stock_quantity, product.min_stock_level) == \
        (0.0, True, 21, 0.0, 5.0)


@pytest.mark.parametrize("tax, expected", [
    ("6", 6), ("12.0", 12), ("0", 0), ("21", 21),  # the Belgian rates are kept
    (None, 21), ("", 21), ("7", 21), ("5.5", 21), ("-6", 21),  # anything else is 21%
])
def test_product_import_keeps_only_belgian_vat_rates(db_session, tax, expected):
    row = {"name": "Milk", "price": "1.20"}
    if tax is not None:
        row["tax"] = tax
    assert ProductService.import_rows(db_session, [row]) == (1, 0)
    assert db_session.query(Product).filter_by(name="Milk").one().tax == expected



def test_import_rows_reports_progress_up_to_the_end(db_session):
    progress = []
    rows = [{"name": f"A{i}", "barcode": f"B{i}"} for i in range(299)]

    added, skipped = ProductService.import_rows(db_session, rows, progress=progress.append)

    assert (added, skipped) == (299, 0)
    assert progress == sorted(progress)
    assert progress[-1] == 1.0  # 299 rows: steps of 2 would otherwise stop at 298/299
