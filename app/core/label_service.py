"""
Label Printer Service
Talks to the USB Zebra-compatible label printer (ZPL) for product shelf
labels. Vendor/product IDs come from Settings.
"""

import logging

from sqlalchemy.orm import Session

from app.core.receipt_service import PrinterError, _get_backend, _parse_id
from app.core.settings_service import SettingsService
from app.models.models import Product

logger = logging.getLogger("pos")

LABEL_WIDTH_DOTS = 448   # 56mm @ 203dpi
LABEL_HEIGHT_DOTS = 256  # 32mm @ 203dpi


def _open(vendor_id: str, product_id: str):
    """Open a connection to the configured USB label printer. Raises PrinterError on failure."""
    backend = _get_backend()
    import usb.core
    import usb.util

    vid = _parse_id(vendor_id, "Vendor ID")
    pid = _parse_id(product_id, "Product ID")

    dev = usb.core.find(idVendor=vid, idProduct=pid, backend=backend)
    if dev is None:
        raise PrinterError(
            f"No USB device found with vendor ID '{vendor_id}' and product ID '{product_id}'. "
            "Check the printer is connected and the IDs are correct."
        )

    try:
        if dev.is_kernel_driver_active(0):
            dev.detach_kernel_driver(0)
    except (NotImplementedError, usb.core.USBError):
        pass  # not applicable on this platform, or already detached

    try:
        dev.set_configuration()
        cfg = dev.get_active_configuration()
        intf = cfg[(0, 0)]

        out_ep = usb.util.find_descriptor(
            intf,
            custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
            == usb.util.ENDPOINT_OUT,
        )
        if out_ep is None:
            raise PrinterError("Could not find an OUT endpoint on this USB device.")

        return dev, out_ep
    except usb.core.USBError as e:
        raise PrinterError(f"Could not connect to label printer: {e}") from e


def _build_zpl(name: str, barcode: str, price: str, unit: str) -> str:
    """
    Builds a ZPL label: name at top, EAN-13 barcode in middle, price at bottom.
    Label size: 56mm x 32mm @ 203dpi (448 x 256 dots).
    barcode must be exactly 12 digits (EAN-13 auto-computes the check digit).
    """
    barcode_data = barcode[:12]

    unit_data = f" / {unit}" if unit in {"kg", "g", "l", "ml"} else ""
    return f"""
^XA
^CI28
^PW{LABEL_WIDTH_DOTS}
^LL{LABEL_HEIGHT_DOTS}
^MNY
^MD15

^FO30,15^A0N,30,30^FB408,2,4,L,0^FD{name}^FS

^FO60,100^BY3^BEN,45,Y,N^FD{barcode_data}^FS

^FO30,210^A0N,40,40^FD{price}{unit_data}^FS

^PQ1
^XZ
"""


class LabelPrinterService:

    @staticmethod
    def _print_zpl(vendor_id: str, product_id: str, zpl: str):
        dev, out_ep = _open(vendor_id, product_id)
        try:
            out_ep.write(zpl.encode("utf-8"))
        except Exception as e:
            logger.exception("Failed to print label")
            raise PrinterError(f"Printer connected but failed to print: {e}") from e
        finally:
            import usb.util
            usb.util.dispose_resources(dev)

    @staticmethod
    def test_print(vendor_id: str, product_id: str):
        zpl = _build_zpl("TEST LABEL", "000000000000", "0.00", "")
        LabelPrinterService._print_zpl(vendor_id, product_id, zpl)

    @staticmethod
    def print_product_label(session: Session, product: Product):
        settings = SettingsService.get_all(session)
        currency = settings.get("currency_symbol", "€")
        vendor_id = settings.get("label_printer_vendor_id", "")
        product_id = settings.get("label_printer_product_id", "")
        zpl = _build_zpl(product.name, product.barcode or "", f"{currency} {product.price:.2f}", product.unit)
        LabelPrinterService._print_zpl(vendor_id, product_id, zpl)
