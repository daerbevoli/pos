from unittest import mock

import pytest
from PIL import Image

from app.core.receipt_service import LOGO_MAX_WIDTH_PX, _print_company_info, _print_logo


def _printed_text(printer):
    return "".join(c.args[0] for c in printer.text.call_args_list)


def test_logo_missing_file_prints_text_header(tmp_path):
    printer = mock.Mock()
    _print_logo(printer, {"logo_path": str(tmp_path / "nope.png"), "store_name": "Corner Shop"})
    printer.image.assert_not_called()
    assert "Corner Shop" in _printed_text(printer)


def test_logo_corrupt_file_prints_text_header_instead_of_failing(tmp_path):
    bad = tmp_path / "logo.png"
    bad.write_bytes(b"not an image")
    printer = mock.Mock()
    _print_logo(printer, {"logo_path": str(bad), "store_name": "Corner Shop"})
    printer.image.assert_not_called()
    assert "Corner Shop" in _printed_text(printer)


def test_logo_valid_file_is_scaled_to_paper_width(tmp_path):
    path = tmp_path / "logo.png"
    Image.new("RGB", (200, 50), "white").save(path)
    printer = mock.Mock()
    _print_logo(printer, {"logo_path": str(path)})
    img = printer.image.call_args.args[0]
    assert img.size == (LOGO_MAX_WIDTH_PX, 144)


def test_logo_printer_failure_still_propagates(tmp_path):
    path = tmp_path / "logo.png"
    Image.new("RGB", (LOGO_MAX_WIDTH_PX, 50), "white").save(path)
    printer = mock.Mock()
    printer.image.side_effect = OSError("USB write failed")
    with pytest.raises(OSError):
        _print_logo(printer, {"logo_path": str(path)})


@pytest.mark.parametrize("settings,expected", [
    ({"store_phone": "02 123 45 67", "store_vat": "BE0123456749"}, "02 123 45 67 - BE0123456749\n"),
    ({"store_vat": "BE0123456749"}, "BE0123456749\n"),
    ({"store_phone": "02 123 45 67"}, "02 123 45 67\n"),
    ({}, ""),
])
def test_company_info_prints_the_saved_phone_and_vat(settings, expected):
    """Regression: it read a "vat_number" key, but Settings saves "store_vat"."""
    printer = mock.Mock()
    _print_company_info(printer, settings)
    assert _printed_text(printer) == expected
