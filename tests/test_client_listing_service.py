"""Tests for ClientListingService (per-client invoice totals over a date range)."""
import csv
from datetime import date, datetime

from app.core.client_listing_service import ClientListingService, LISTING_HEADERS
from app.core.client_service import ClientService
from app.core.product_service import ProductService
from app.core.sales_service import Cart, CartItem, SalesService


def _make_client(session, name, vat):
    return ClientService.create(session, name=name, street=f"{name} street 1", zip_code="2000",
                                city="Antwerpen", vatNumber=vat)


def _item(product, quantity=1):
    return CartItem(product_id=product.id, product_name=product.name, product_barcode="",
                    unit_price=product.price, quantity=quantity, tax_rate=product.tax)


def _invoice(session, client, *items, issued_at=datetime(2026, 3, 10, 12), refund=False):
    cart = Cart(entries=list(items))
    cart.is_refund = refund
    invoice = SalesService.finalize_invoice(session, cart, client_id=client.id)
    invoice.issued_at = issued_at
    session.commit()
    return invoice


def _products(session):
    p21 = ProductService.create(session, name="Wine", price=12.10, stock_quantity=100, tax=21)
    p6 = ProductService.create(session, name="Bread", price=10.60, stock_quantity=100, tax=6)
    return p21, p6


def test_rows_total_per_client_with_vat_breakdown(db_session):
    p21, p6 = _products(db_session)
    acme = _make_client(db_session, "Acme", "BE0123456789")
    _invoice(db_session, acme, _item(p21), _item(p6))
    _invoice(db_session, acme, _item(p21, 2))

    rows = ClientListingService.build(db_session, date(2026, 3, 1), date(2026, 3, 31))

    assert len(rows) == 1
    row = rows[0]
    assert (row.name, row.vat_number, row.invoice_count) == ("Acme", "BE0123456789", 2)
    assert row.total_incl == 46.9
    assert row.total_excl == 40.0
    assert row.base_per_rate == {0: 0.0, 6: 10.0, 12: 0.0, 21: 30.0}


def test_only_invoices_in_range_count_and_end_date_is_inclusive(db_session):
    p21, _ = _products(db_session)
    acme = _make_client(db_session, "Acme", "BE0123456789")
    _invoice(db_session, acme, _item(p21), issued_at=datetime(2026, 2, 28, 23, 59))
    _invoice(db_session, acme, _item(p21), issued_at=datetime(2026, 3, 31, 23, 59))
    _invoice(db_session, acme, _item(p21), issued_at=datetime(2026, 4, 1, 0, 0))

    rows = ClientListingService.build(db_session, date(2026, 3, 1), date(2026, 3, 31))

    assert [(r.invoice_count, r.total_incl) for r in rows] == [(1, 12.10)]


def test_credit_note_nets_out_of_client_totals(db_session):
    p21, _ = _products(db_session)
    acme = _make_client(db_session, "Acme", "BE0123456789")
    _invoice(db_session, acme, _item(p21, 2))
    _invoice(db_session, acme, _item(p21, -1), refund=True)

    row = ClientListingService.build(db_session, date(2026, 3, 1), date(2026, 3, 31))[0]

    assert row.total_incl == 12.10
    assert row.base_per_rate[21] == 10.0
    assert row.invoice_count == 2


def test_rows_sorted_by_name_and_clients_without_invoices_left_out(db_session):
    p21, _ = _products(db_session)
    zed = _make_client(db_session, "Zed", "BE0999999999")
    alpha = _make_client(db_session, "alpha", "BE0111111111")
    _make_client(db_session, "Idle", "BE0222222222")
    _invoice(db_session, zed, _item(p21))
    _invoice(db_session, alpha, _item(p21))

    rows = ClientListingService.build(db_session, date(2026, 3, 1), date(2026, 3, 31))

    assert [r.name for r in rows] == ["alpha", "Zed"]


def test_write_csv(db_session, tmp_path):
    p21, _ = _products(db_session)
    acme = _make_client(db_session, "Acme", "BE0123456789")
    _invoice(db_session, acme, _item(p21))
    rows = ClientListingService.build(db_session, date(2026, 3, 1), date(2026, 3, 31))
    path = tmp_path / "listing.csv"

    ClientListingService.write_csv(rows, str(path))

    with open(path, newline="", encoding="utf-8") as f:
        written = list(csv.reader(f))
    assert written[0] == LISTING_HEADERS
    assert written[1] == ["Acme", "BE0123456789", "12.10", "10.00", "0.00", "0.00", "0.00", "10.00", "1"]


def test_write_pdf(db_session, tmp_path):
    p21, _ = _products(db_session)
    acme = _make_client(db_session, "Acme", "BE0123456789")
    _invoice(db_session, acme, _item(p21))
    rows = ClientListingService.build(db_session, date(2026, 3, 1), date(2026, 3, 31))
    path = tmp_path / "listing.pdf"

    ClientListingService.write_pdf(rows, str(path), date(2026, 3, 1), date(2026, 3, 31))

    assert path.read_bytes().startswith(b"%PDF")
