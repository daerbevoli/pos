"""Tests for the ZPL shelf labels in app.core.label_service."""
from types import SimpleNamespace

from app.core.label_service import _build_zpl, promo_label_data


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
    zpl = _build_zpl("Cola", "541234567890", "€ 2.50", "pcs")
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
