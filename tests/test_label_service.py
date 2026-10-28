"""Tests for the ZPL shelf labels in app.core.label_service."""
from types import SimpleNamespace

import pytest

from app.core.label_service import _build_zpl, _zpl_barcode, promo_label_data


def _product(price=2.50, promo=None):
    return SimpleNamespace(price=price, active_promo_item=promo)


def _promo(discount_type, value):
    return SimpleNamespace(discount_type=discount_type, discount_value=value)


def test_no_promo_gives_no_promo_data():
    assert promo_label_data(_product(), "€") is None


def test_percent_promo_price():
    assert promo_label_data(_product(2.50, _promo("percent", 20)), "€") == {"price": "€ 2.00"}


def test_fixed_promo_price_never_below_zero():
    assert promo_label_data(_product(2.50, _promo("fixed", 0.60)), "€") == {"price": "€ 1.90"}
    assert promo_label_data(_product(0.50, _promo("fixed", 1.00)), "€")["price"] == "€ 0.00"


def test_regular_label_is_unchanged_without_promo():
    zpl = _build_zpl("Cola", "5410000000002", "€ 2.50", "pcs")
    assert "PROMO" not in zpl
    assert "^FO60,100^BY3" in zpl
    assert "^FO30,210^A0N,40,40^FD€ 2.50^FS" in zpl


def test_promo_label_has_promo_text_old_and_new_price():
    zpl = _build_zpl("Cola", "541234567890", "€ 2.50", "pcs", promo={"price": "€ 2.00"})
    assert "^FO20,203^ADN,36,20^FDPROMO^FS" in zpl  # left, different font, no box
    assert "^FR" not in zpl
    assert "^FO180,178^FB200,1,0,R,0^A0N,24,24^FD€ 2.50^FS" in zpl  # old price, right-aligned
    assert "^FO308,189^GB72,3,3^FS" in zpl                          # strike line ends where the price does (x=380)
    assert "^FO180,206^FB200,1,0,R,0^A0N,44,34^FD€ 2.00^FS" in zpl  # promo price, right-aligned
    assert zpl.count("^XA") == 1 and zpl.strip().endswith("^XZ")


def test_promo_label_puts_unit_only_on_the_new_price():
    zpl = _build_zpl("Bananas", "200000000004", "€ 2.49", "kg", promo={"price": "€ 1.99"})
    assert "^FD€ 2.49^FS" in zpl
    assert "^FD€ 1.99 / kg^FS" in zpl


@pytest.mark.parametrize("barcode, field", [
    ("5410000000002", "^BY3^BEN,45,Y,N^FD541000000000^FS"),   # EAN-13: printer adds the check digit
    ("036000291452", "^BY3^BUN,45,Y,N,Y^FD03600029145^FS"),   # UPC-A, not EAN-13 data
    ("96385074", "^BY3^B8N,45,Y,N^FD9638507^FS"),             # EAN-8
    ("5410000000003", "^BY2^BCN,45,Y,N,N,A^FD5410000000003^FS"),  # bad check digit: printed as is
    ("ABC-123", "^BY2^BCN,45,Y,N,N,A^FDABC-123^FS"),
])
def test_label_barcode_scans_back_as_the_stored_code(barcode, field):
    """Regression: barcode[:12] went out as EAN-13 whatever the code was."""
    assert _zpl_barcode(barcode, 100) == f"^FO60,100{field}"


def test_long_code128_narrows_its_bars_to_fit_the_label():
    assert "^BY1^BC" in _zpl_barcode("ABCDEFGHIJKLMNOPQRS", 100)
