from unittest import mock

import pytest
from PIL import Image

from app.core.sale.cart import Cart, CartItem, SubtotalMarker
from app.core.sale.receipt_service import LOGO_MAX_WIDTH_PX, _print_company_info, _print_line_items, _print_logo


def _printed_text(printer):
    return "".join(c.args[0] for c in printer.text.call_args_list)


def test_logo_missing_file_prints_text_header(tmp_path):
    printer = mock.Mock()
    _print_logo(printer, {"logo_path": str(tmp_path / "nope.png"), "trade_name": "Corner Shop"})
    printer.image.assert_not_called()
    assert "Corner Shop" in _printed_text(printer)


def test_logo_corrupt_file_prints_text_header_instead_of_failing(tmp_path):
    bad = tmp_path / "logo.png"
    bad.write_bytes(b"not an image")
    printer = mock.Mock()
    _print_logo(printer, {"logo_path": str(bad), "trade_name": "Corner Shop"})
    printer.image.assert_not_called()
    assert "Corner Shop" in _printed_text(printer)


def test_text_header_falls_back_to_company_name_without_trade_name():
    printer = mock.Mock()
    _print_logo(printer, {"company_name": "Corner Shop BV", "trade_name": ""})
    assert "Corner Shop BV" in _printed_text(printer)
    printer = mock.Mock()
    _print_logo(printer, {"company_name": "Corner Shop BV", "trade_name": "Corner Shop"})
    assert "Corner Shop\n" in _printed_text(printer) and "BV" not in _printed_text(printer)


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


def test_subtotal_lines_print_their_own_block():
    """Same figures as the till's SUBTOTAL rows (Cart.subtotals()), not a running total."""
    cart = Cart(entries=[
        CartItem(product_id=1, product_name="A", product_barcode="1", unit_price=10.0, quantity=1),
        SubtotalMarker(),
        CartItem(product_id=2, product_name="B", product_barcode="2", unit_price=2.5, quantity=2),
        SubtotalMarker(),
    ])
    printer = mock.Mock()
    _print_line_items(printer, cart)
    lines = [l.split() for l in _printed_text(printer).splitlines() if "SUBTOTAL" in l]
    assert lines == [["1", "SUBTOTAL", "10.00"], ["2", "SUBTOTAL", "5.00"]]


def test_receipt_printer_writes_have_a_timeout(monkeypatch):
    """Regression: timeout=0 is "no limit" in pyusb, so a printer that stops
    taking data (out of paper, cover open) hung the POS for good."""
    import escpos.printer
    import app.core.sale.receipt_service as receipt_service
    usb = mock.Mock()
    monkeypatch.setattr(receipt_service, "_get_backend", mock.Mock())
    monkeypatch.setattr(escpos.printer, "Usb", usb)

    receipt_service._open("0x04b8", "0x0e28")

    assert 0 < usb.call_args.kwargs["timeout"] <= 10_000


def _failing_printer(monkeypatch, error):
    import app.core.sale.receipt_service as receipt_service
    printer = mock.Mock()
    printer.cashdraw.side_effect = error
    monkeypatch.setattr(receipt_service, "_open", mock.Mock(return_value=printer))
    monkeypatch.setattr(receipt_service.SettingsService, "get_all", mock.Mock(return_value={}))
    return receipt_service


def test_printer_timeout_is_a_check_the_printer_warning(monkeypatch, caplog):
    """Out of paper / cover open is normal shop life: no ERROR (error badge), a plain message."""
    import usb.core
    receipt_service = _failing_printer(monkeypatch, usb.core.USBTimeoutError("timed out"))

    with pytest.raises(receipt_service.PrinterNotResponding, match="^Check the printer$"):
        receipt_service.ReceiptService.open_drawer(None)
    assert not [r for r in caplog.records if r.levelname == "ERROR"]
    assert [r for r in caplog.records if r.levelname == "WARNING"]


def test_other_printer_failure_stays_an_error(monkeypatch, caplog):
    receipt_service = _failing_printer(monkeypatch, RuntimeError("boom"))

    with pytest.raises(receipt_service.PrinterError, match="boom") as exc:
        receipt_service.ReceiptService.open_drawer(None)
    assert not isinstance(exc.value, receipt_service.PrinterNotResponding)
    assert [r for r in caplog.records if r.levelname == "ERROR"]


@pytest.fixture
def fresh_backend(monkeypatch):
    """Undo _get_backend()'s module-level cache and usb.core.find patch."""
    import usb.core
    import app.core.sale.receipt_service as receipt_service
    monkeypatch.setattr(receipt_service, "_backend", None)
    monkeypatch.setattr(usb.core, "find", usb.core.find)
    return receipt_service


def test_backend_on_linux_uses_system_libusb_and_patches_find_once(fresh_backend, monkeypatch):
    import usb.core
    from usb.backend import libusb1
    backend = object()
    get_backend = mock.Mock(return_value=backend)
    monkeypatch.setattr(fresh_backend.sys, "platform", "linux")
    monkeypatch.setattr(libusb1, "get_backend", get_backend)

    assert fresh_backend._get_backend() is backend
    patched_find = usb.core.find
    assert fresh_backend._get_backend() is backend

    get_backend.assert_called_once_with()  # no find_library: pyusb finds the system lib
    assert usb.core.find is patched_find  # cached: not wrapped a second time


def test_backend_that_cannot_load_raises_and_leaves_find_alone(fresh_backend, monkeypatch):
    import usb.core
    from usb.backend import libusb1
    original_find = usb.core.find
    monkeypatch.setattr(fresh_backend.sys, "platform", "linux")
    monkeypatch.setattr(libusb1, "get_backend", mock.Mock(return_value=None))

    for _ in range(2):  # each retry fails the same way
        with pytest.raises(fresh_backend.PrinterError):
            fresh_backend._get_backend()
    assert usb.core.find is original_find
    assert fresh_backend._backend is None
