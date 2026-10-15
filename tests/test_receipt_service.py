from unittest import mock

import pytest
from PIL import Image

from app.core.receipt_service import LOGO_MAX_WIDTH_PX, _print_logo


def _printed_text(printer):
    return "".join(c.args[0] for c in printer.text.call_args_list)


def test_logo_missing_file_prints_text_header(tmp_path):
    printer = mock.Mock()
    _print_logo(printer, {"logo_path": str(tmp_path / "nope.png")})
    printer.image.assert_not_called()
    assert "EUROSTAR SUPERMARKET" in _printed_text(printer)


def test_logo_corrupt_file_prints_text_header_instead_of_failing(tmp_path):
    bad = tmp_path / "logo.png"
    bad.write_bytes(b"not an image")
    printer = mock.Mock()
    _print_logo(printer, {"logo_path": str(bad)})
    printer.image.assert_not_called()
    assert "EUROSTAR SUPERMARKET" in _printed_text(printer)


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
