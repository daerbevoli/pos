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
from app.utils.barcodes import barcode_symbology

logger = logging.getLogger(__name__)

LABEL_WIDTH_DOTS = 448   # 56mm @ 203dpi
LABEL_HEIGHT_DOTS = 256  # 32mm @ 203dpi


def _open(vendor_id: str, product_id: str):
    """Open a connection to the configured USB label printer. Raises PrinterError on failure."""
    backend = _get_backend()
    import usb.core
    import usb.util

    logger.debug("Opening label printer USB %s:%s", vendor_id, product_id)
    try:
        vid = _parse_id(vendor_id, "Vendor ID")
        pid = _parse_id(product_id, "Product ID")
    except PrinterError as e:
        logger.error("Label printer not usable: %s", e)
        raise

    dev = usb.core.find(idVendor=vid, idProduct=pid, backend=backend)
    if dev is None:
        logger.error("Label printer USB %s:%s not found", vendor_id, product_id)
        raise PrinterError(
            f"No USB device found with vendor ID '{vendor_id}' and product ID '{product_id}'. "
            "Check the printer is connected and the IDs are correct."
        )

    try:
        if dev.is_kernel_driver_active(0):
            dev.detach_kernel_driver(0)
    except (NotImplementedError, usb.core.USBError) as e:
        # not applicable on this platform, or already detached
        logger.debug("Label printer kernel driver not detached: %r", e)

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
            logger.error("Label printer USB %s:%s has no OUT endpoint", vendor_id, product_id)
            raise PrinterError("Could not find an OUT endpoint on this USB device.")

        return dev, out_ep
    except usb.core.USBError as e:
        logger.error("Could not connect to label printer USB %s:%s: %s", vendor_id, product_id, e)
        raise PrinterError(f"Could not connect to label printer: {e}") from e

BARCODE_X = 60  # left edge of the barcode, in dots


def _zpl_barcode(barcode: str, y: int) -> str:
    """The ZPL barcode field for `barcode`, in the symbology that scans back
    as the same digits (see app.utils.barcodes). The EAN/UPC commands get the
    code without its check digit: the printer adds it."""
    kind = barcode_symbology(barcode)
    if kind == "EAN13":
        return f"^FO{BARCODE_X},{y}^BY3^BEN,45,Y,N^FD{barcode[:12]}^FS"
    if kind == "UPCA":
        return f"^FO{BARCODE_X},{y}^BY3^BUN,45,Y,N,Y^FD{barcode[:11]}^FS"
    if kind == "EAN8":
        return f"^FO{BARCODE_X},{y}^BY3^B8N,45,Y,N^FD{barcode[:7]}^FS"
    # Code 128 in automatic mode (digit pairs packed two per symbol). Roughly
    # 11 modules per symbol plus start/check/stop: narrow the bars when the
    # code would otherwise run off the label.
    symbols = (len(barcode) + 1) // 2 if barcode.isdigit() else len(barcode)
    module = 2 if (11 * symbols + 35) * 2 <= LABEL_WIDTH_DOTS - BARCODE_X else 1
    return f"^FO{BARCODE_X},{y}^BY{module}^BCN,45,Y,N,N,A^FD{barcode}^FS"


def _build_zpl(name: str, barcode: str, price: str, unit: str, promo: dict | None = None) -> str:
    """
    Builds a ZPL label: name at top, barcode in middle, price at bottom.
    Label size: 56mm x 32mm @ 203dpi (448 x 256 dots).
    The barcode prints as EAN-13, UPC-A or EAN-8 when it is one, else Code 128.

    With `promo` ({"price": new price text}), the bottom row becomes
    "PROMO" on the left in a different font (^AD at 2x, vs the regular
    ^A0), and on the right, flush with the label edge, the old price
    struck through above the promo price — leaving the middle empty.
    """
    unit_data = f" / {unit}" if unit in {"kg", "g", "l", "ml"} else ""
    if promo is None:
        barcode_y = 100
        bottom = f"^FO30,210^A0N,40,40^FD{price}{unit_data}^FS"
    else:
        barcode_y = 88  # moved up to make room for the taller promo row
        # Both prices are right-aligned (^FB ...,R) in one block; move or
        # resize the block here and the strike line follows, since it's
        # anchored to the block's right end where the old price ends. The
        # unit only goes on the promo price, set narrower (34 wide) to fit.
        price_x = LABEL_WIDTH_DOTS - 20 - 248  # block's left edge
        price_block_width = 200
        price_right = price_x + price_block_width  # where both prices end
        strike_width = len(price) * 12  # ~12 dots/char at ^A0 24pt
        bottom = f"""
                ^FO20,203^ADN,36,20^FDPROMO^FS
                ^FO{price_x},178^FB{price_block_width},1,0,R,0^A0N,24,24^FD{price}^FS
                ^FO{price_right - strike_width},189^GB{strike_width},3,3^FS
                ^FO{price_x},206^FB{price_block_width},1,0,R,0^A0N,44,34^FD{promo["price"]}{unit_data}^FS
                """

    return f"""
            ^XA
            ^CI28
            ^PW{LABEL_WIDTH_DOTS}
            ^LL{LABEL_HEIGHT_DOTS}
            ^MNY
            ^MD15
            
            ^FO30,15^A0N,30,30^FB408,2,4,L,0^FD{name}^FS
            
            {_zpl_barcode(barcode, barcode_y)}
            {bottom}
            
            ^PQ1
            ^XZ
            """


def promo_label_data(product: Product, currency: str) -> dict | None:
    """{"price"} for the product's running promo, or None. The
    promo price uses the same rule as the till (CartItem.discount_amount):
    percent off, or a fixed amount off per unit, never below 0."""
    promo_item = product.active_promo_item
    if promo_item is None:
        return None
    value = promo_item.discount_value
    if promo_item.discount_type == "percent":
        new_price = round(product.price * (1 - value / 100), 2)
    else:
        new_price = round(max(product.price - value, 0.0), 2)
    return {"price": f"{currency} {new_price:.2f}"}


class LabelPrinterService:

    @staticmethod
    def _print_zpl(vendor_id: str, product_id: str, zpl: str):
        dev, out_ep = _open(vendor_id, product_id)
        logger.debug("Sending ZPL to label printer:%s", zpl)
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
        logger.info("Label printer test label printed (USB %s:%s)", vendor_id, product_id)

    @staticmethod
    def print_product_label(session: Session, product: Product):
        settings = SettingsService.get_all(session)
        currency = settings.get("currency_symbol", "€")
        vendor_id = settings.get("label_printer_vendor_id", "")
        product_id = settings.get("label_printer_product_id", "")
        promo = promo_label_data(product, currency)
        zpl = _build_zpl(
            product.name, product.barcode or "", f"{currency} {product.price:.2f}", product.unit,
            promo=promo,
        )
        LabelPrinterService._print_zpl(vendor_id, product_id, zpl)
        logger.info("Shelf label printed: product %s %r, barcode %s, %.2f%s",
                    product.id, product.name, product.barcode, product.price,
                    f" (promo {promo['price']})" if promo else "")
