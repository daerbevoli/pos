"""
Printer Service
Talks to the USB thermal receipt printer (ESC/POS) for tickets, invoices,
test pages, and the cash drawer kick. Vendor/product IDs come from Settings.
"""

import glob
import json
import logging
import os
import platform
import textwrap

from PIL import Image
from sqlalchemy.orm import Session

from app.core.sales_service import Cart, CartItem, DiscountEntry, SubtotalMarker
from app.core.settings_service import SettingsService
from app.models.models import Invoice, Sale, ZReport

logger = logging.getLogger("pos")

LINE_WIDTH = 48  # 80mm paper at font A (12x24 dots -> 576px / 12)
DRAWER_PIN = 2  # 2 = connector pin 2 (common default), 5 = connector pin 5
LOGO_MAX_WIDTH_PX = 576  # 80mm paper at 203dpi

WEIGHT_UNITS = {"kg", "g", "ml", "l"}

QTY_COL = 5
NAME_COL = 23
UNIT_COL = 9    # unit price ("Price" column)
TOTAL_COL = LINE_WIDTH - QTY_COL - NAME_COL - UNIT_COL  # line total ("Total" column)
LABEL_COL = QTY_COL + NAME_COL + UNIT_COL  # summary rows (TOTAL, VAT, payments) span the first 3 columns

_backend = None


class PrinterError(Exception):
    """Raised when the receipt printer can't be reached or fails to print."""


def _get_backend():
    """Lazily resolve the libusb1 backend, patching pyusb's global find() so
    python-escpos's internal usb.core.find() calls use it too. The `libusb`
    pip package nests DLLs in per-arch subfolders and pyusb won't find them
    via PATH alone (see Zadig/WinUSB setup)."""
    global _backend
    if _backend is not None:
        return _backend

    import libusb
    import usb.core
    import usb.backend.libusb1

    pkg_dir = os.path.dirname(libusb.__file__)
    arch = ("arm64" if "arm" in platform.machine().lower()
            else "x86_64" if platform.architecture()[0] == "64bit" else "x86")
    matches = glob.glob(os.path.join(pkg_dir, "**", arch, "libusb-1.0.dll"), recursive=True)
    if not matches:
        raise PrinterError("libusb-1.0.dll not found for this platform/architecture.")

    backend = usb.backend.libusb1.get_backend(find_library=lambda x: matches[0])
    original_find = usb.core.find
    usb.core.find = lambda *a, **kw: original_find(*a, **{**kw, "backend": backend})
    _backend = backend
    return _backend


def _parse_id(raw: str, label: str) -> int:
    raw = (raw or "").strip()
    if not raw:
        raise PrinterError(f"{label} is not configured. Set it in Settings.")
    try:
        return int(raw, 16)
    except ValueError:
        raise PrinterError(f"{label} '{raw}' is not a valid hex ID (e.g. 0x04b8).")


def _open(vendor_id: str, product_id: str):
    """Open a connection to the configured USB printer. Raises PrinterError on failure."""
    _get_backend()
    import usb.core
    import usb.backend.libusb1
    from escpos.exceptions import Error as EscposError
    from escpos.printer import Usb

    vid = _parse_id(vendor_id, "Vendor ID")
    pid = _parse_id(product_id, "Product ID")
    try:
        return Usb(vid, pid, timeout=0, in_ep=0x81, out_ep=0x01)
    except (usb.core.USBError, EscposError) as e:
        raise PrinterError(f"Could not connect to receipt printer: {e}") from e


def _money(currency: str, amount: float) -> str:
    return f"{currency}{amount:.2f}"


def _print_logo(printer, settings: dict):
    logo_path = settings.get("logo_path", "")
    if not logo_path or not os.path.isfile(logo_path):
        printer.set(align="center", bold=True, width=2, height=2, custom_size=True)
        printer.text(f"EUROSTAR SUPERMARKET\n")
        printer.text("-" * LINE_WIDTH + "\n")
        printer.set(align="left")
        return
    try:
        with Image.open(logo_path) as img:
            if img.width != LOGO_MAX_WIDTH_PX:
                ratio = LOGO_MAX_WIDTH_PX / img.width
                size = (LOGO_MAX_WIDTH_PX, max(1, round(img.height * ratio)))
                img = img.resize(size, Image.LANCZOS)
            printer.image(img, center=True)
            printer.text("-" * LINE_WIDTH + "\n")
            printer.set(align="left")
    except Exception:
        logger.exception("Failed to print logo image at %s", logo_path)


def _wrap_name(name: str) -> list[str]:
    """Wrap a name to fit NAME_COL, preferring word breaks; overflow spills to extra lines."""
    return textwrap.wrap(name, width=NAME_COL, break_long_words=True, break_on_hyphens=False) or [""]


def _print_line_items(printer, cart: Cart, currency: str):
    printer.set(bold=True)
    printer.text(f"{'#':<{QTY_COL}}{'Description':<{NAME_COL}}{'Price':>{UNIT_COL}}{'Total':>{TOTAL_COL}}\n")
    printer.text("-" * LINE_WIDTH + "\n")
    printer.set(bold=False)
    running_qty = 0.0
    running_total = 0.0
    for entry in cart.entries:
        if isinstance(entry, CartItem):
            if entry.quantity is None:
                continue
            prefix = "VOID " if entry.is_reversal else ""
            weight_text = None
            if entry.unit in WEIGHT_UNITS:
                # One weighed article, not `quantity` units of it — the
                # subtotal counts articles, and the actual weight prints
                # on its own centered line below the article.
                qty_count = -1 if entry.quantity < 0 else 1
                qty = f"{qty_count}"
                weight_text = f"{abs(entry.quantity):g}{entry.unit}"
                unit_price = f"{_money(currency, entry.unit_price)}/{entry.unit}"
            else:
                qty_count = entry.quantity
                qty = f"{entry.quantity:g}"
                unit_price = _money(currency, entry.unit_price)
            name = prefix + entry.product_name
            running_qty += qty_count
            running_total += entry.line_total
            name_lines = _wrap_name(name)
            printer.text(
                f"{qty:<{QTY_COL}}{name_lines[0]:<{NAME_COL}}"
                f"{unit_price:>{UNIT_COL}}{_money(currency, entry.line_total):>{TOTAL_COL}}\n"
            )
            for extra in name_lines[1:]:
                printer.text(f"{'':<{QTY_COL}}{extra}\n")
            if weight_text:
                printer.text(weight_text.center(LINE_WIDTH // 2) + "\n")
            if entry.discount:
                pre_discount = entry.unit_price * entry.quantity
                pct = round(entry.discount / pre_discount * 100, 2) if pre_discount else 0
                printer.text(
                    f"{'':<{QTY_COL}}{f'Discount {pct:g}%':<{NAME_COL}}{'':>{UNIT_COL}}"
                    f"{'-' + _money(currency, entry.discount):>{TOTAL_COL}}\n"
                )
        elif isinstance(entry, SubtotalMarker):
            qty_str = f"{running_qty:g}"
            printer.set(bold=True)
            printer.text(
                f"{qty_str:<{QTY_COL}}{'Subtotal':<{NAME_COL}}{'':>{UNIT_COL}}"
                f"{_money(currency, running_total):>{TOTAL_COL}}\n"
            )
            printer.set(bold=False)
        elif isinstance(entry, DiscountEntry):
            running_total += entry.line_total
            label_lines = _wrap_name(f"Discount {entry.label}")
            printer.text(
                f"{'':<{QTY_COL-1}} {label_lines[0]:<{NAME_COL}}{'':>{UNIT_COL}}"
                f"{'-' + _money(currency, entry.amount):>{TOTAL_COL}}\n"
            )
            for extra in label_lines[1:]:
                printer.text(f"{'':<{QTY_COL}}{extra}\n")
    printer.text("-" * LINE_WIDTH + "\n")


TOTAL_ROW_WIDTH = LINE_WIDTH // 2  # columns available at the TOTAL row's 2x character width


def _print_totals(printer, currency: str, tax_amount: float, final_amount: float):
    printer.set(bold=True, width=2, height=2, custom_size=True)
    label_col = TOTAL_ROW_WIDTH - 10
    printer.text(f"{'TOTAL':<{label_col}}{_money(currency, final_amount):>10}\n")
    printer.set(bold=False, width=1, height=1, custom_size=True)

def _print_payment_breakdown(printer, currency: str, sale: Sale):
    breakdown = json.loads(sale.payment_breakdown) if sale.payment_breakdown else [
        {"method": sale.payment_method, "amount": sale.amount_tendered or sale.final_amount}
    ]
    for entry in breakdown:
        printer.text(f"{entry['method'].capitalize():<{LABEL_COL}}{_money(currency, entry['amount']):>{TOTAL_COL}}\n")
    if sale.change_given:
        printer.text(f"{'Change':<{LABEL_COL}}{'-'+_money(currency, sale.change_given):>{TOTAL_COL}}\n")
    printer.text("-" * LINE_WIDTH + "\n")


def _print_footer(printer, document_number: str, created_at, footer_text: str):
    printer.set(align="center")
    printer.text(f"\n{document_number}\n{created_at.strftime('%d-%m-%Y %H:%M')}\n")
    if footer_text:
        printer.text(f"\n{footer_text}\n")
    printer.text("\n")

def _print_company_info(printer, settings):
    printer.set(align="center", bold=True, width=1, height=1, custom_size=True)
    printer.text(f"{settings.get('store_name', '')}\n")
    printer.set(align="center", bold=False, width=1, height=1, custom_size=True)
    if settings.get("store_address"):
        printer.text(f"{settings['store_address']}\n")
    if settings.get("store_phone"):
        printer.text(f"{settings['store_phone']} - ")
    if settings.get("vat_number"):
        printer.text(f"{settings['vat_number']}")

RATE_COL = 6
AMT_COL = (LINE_WIDTH - RATE_COL) // 3  # 14 — Base / Tax / Total (incl.) columns


def _print_report_header(printer, title: str, report_number, period_start, period_end):
    printer.set(align="center", bold=True, width=2, height=2, custom_size=True)
    printer.text(f"{title}\n")
    printer.set(align="left", bold=False, width=1, height=1, custom_size=True)
    if report_number:
        printer.text(f"{report_number}\n")
    printer.text(
        f"{period_start.strftime('%d/%m/%Y %H:%M')}\n{period_end.strftime('%d/%m/%Y %H:%M')}\n"
    )
    printer.set(align="left")
    printer.text("-" * LINE_WIDTH + "\n")


def _print_report_totals(printer, currency: str, totals: dict):

    printer.set(bold=True)
    printer.text(f"{'Payment':<{LABEL_COL}}{'Amount':>{TOTAL_COL}}\n")
    printer.set(bold=False)
    printer.text(f"{'TOTAL':<{LABEL_COL}} {totals['final_amount']:>10.2f}\n")
    for leg in totals["payment_breakdown"]:
        printer.text(
            f"{leg['method'].capitalize():<{LABEL_COL}}{leg['amount']:>{TOTAL_COL}.2f}\n"
        )
    printer.text("-" * LINE_WIDTH + "\n")

    printer.set(bold=True)
    printer.text(f"{'Transactions':<{LABEL_COL}}{totals['transaction_count']:>{TOTAL_COL}}\n")
    printer.text("-" * LINE_WIDTH + "\n")

    printer.text(f"{'Rate':<{RATE_COL}}{'Base':>{AMT_COL}}{'Tax':>{AMT_COL}}{'Total':>{AMT_COL}}\n")
    printer.set(bold=False)
    total_base = total_tax = total_incl = 0.0
    for rate, amounts in totals["vat_breakdown"].items():
        total_base += amounts["base"]
        total_tax += amounts["tax"]
        total_incl += amounts["total"]
        printer.text(
            f"{rate + '%':<{RATE_COL}}{amounts['base']:>{AMT_COL}.2f}"
            f"{amounts['tax']:>{AMT_COL}.2f}{amounts['total']:>{AMT_COL}.2f}\n"
        )
    printer.set(bold=True)
    printer.text(
        f"{'Total':<{RATE_COL}}{total_base:>{AMT_COL}.2f}"
        f"{total_tax:>{AMT_COL}.2f}{total_incl:>{AMT_COL}.2f}\n"
    )
    printer.set(bold=False)
    printer.text("-" * LINE_WIDTH + "\n")

    _print_categories(printer, currency, totals)



CAT_NAME_COL = 24
CAT_QTY_COL = 10
CAT_AMT_COL = LINE_WIDTH - CAT_NAME_COL - CAT_QTY_COL  # 14


def _print_categories(printer, currency: str, totals: dict):
    printer.set(bold=True)
    printer.text(f"{'Category':<{CAT_NAME_COL}}{'Qty':>{CAT_QTY_COL}}{'Amount':>{CAT_AMT_COL}}\n")
    printer.set(bold=False)
    for name, (qty, amount) in totals["category_breakdown"].items():
        printer.text(
            f"{name:<{CAT_NAME_COL}}{qty:>{CAT_QTY_COL}g}{amount:>{CAT_AMT_COL}.2f}\n"
        )
    printer.text("-" * LINE_WIDTH + "\n")


def _print_b2b_info(printer, invoice):
    printer.set(align="left", bold=True, width=1, height=1)
    printer.text(f"{invoice.client_name}\n")
    printer.text(f"{invoice.client_address}\n")
    printer.text(f"{invoice.client_vat_number}\n")
    printer.text("-" * LINE_WIDTH + "\n")

class ReceiptService:

    @staticmethod
    def test_print(vendor_id: str, product_id: str):
        printer = _open(vendor_id, product_id)
        try:
            printer.set(align="center", bold=True, width=2, height=2, custom_size=True)
            printer.text("TEST PRINT\n")
            printer.set(align="center", bold=False, width=1, height=1, custom_size=True)
            printer.text("Printer connected OK\n")
            printer.text("-" * LINE_WIDTH + "\n")
            printer.cut()
        except Exception as e:
            raise PrinterError(f"Printer connected but failed to print: {e}") from e
        finally:
            printer.close()

    @staticmethod
    def open_drawer(session: Session):
        settings = SettingsService.get_all(session)
        printer = _open(settings.get("receipt_printer_vendor_id", ""), settings.get("receipt_printer_product_id", ""))
        try:
            printer.cashdraw(DRAWER_PIN)
        except Exception as e:
            raise PrinterError(f"Could not open cash drawer: {e}") from e
        finally:
            printer.close()

    @staticmethod
    def print_receipt(session: Session, sale: Sale):
        settings = SettingsService.get_all(session)
        currency = settings.get("currency_symbol", "€")
        printer = _open(settings.get("receipt_printer_vendor_id", ""), settings.get("receipt_printer_product_id", ""))
        try:
            _print_logo(printer, settings)
            if sale.invoice:
                _print_b2b_info(printer, sale.invoice)
            ticket_num = sale.invoice.invoice_number if sale.invoice else sale.sale_number
            _print_line_items(printer, Cart.from_snapshot(sale.cart_snapshot), currency)
            _print_totals(printer, currency, sale.tax_amount, sale.final_amount)
            _print_payment_breakdown(printer, currency, sale)
            _print_footer(printer, ticket_num, sale.created_at, settings.get("receipt_footer", ""))
            _print_company_info(printer, settings)

            printer.cut(mode="PART")
        except PrinterError:
            raise
        except Exception as e:
            logger.exception("Failed to print receipt for sale %s", sale.sale_number)
            raise PrinterError(f"Printer connected but failed to print: {e}") from e
        finally:
            printer.close()

    @staticmethod
    def print_x_report(session: Session, totals: dict):
        settings = SettingsService.get_all(session)
        currency = settings.get("currency_symbol", "€")
        printer = _open(settings.get("receipt_printer_vendor_id", ""), settings.get("receipt_printer_product_id", ""))
        try:
            _print_company_info(printer, settings)
            printer.text("\n")
            _print_report_header(printer, "X REPORT", None, totals["period_start"], totals["period_end"])
            _print_report_totals(printer, currency, totals)
            printer.text("\n")

            printer.cut()
        except PrinterError:
            raise
        except Exception as e:
            logger.exception("Failed to print X report")
            raise PrinterError(f"Printer connected but failed to print: {e}") from e
        finally:
            printer.close()

    @staticmethod
    def print_z_report(session: Session, z_report: ZReport):
        settings = SettingsService.get_all(session)
        currency = settings.get("currency_symbol", "€")
        printer = _open(settings.get("receipt_printer_vendor_id", ""), settings.get("receipt_printer_product_id", ""))
        try:
            totals = {
                "transaction_count": z_report.transaction_count,
                "tax_amount": z_report.tax_amount,
                "final_amount": z_report.final_amount,
                "vat_breakdown": json.loads(z_report.vat_breakdown) if z_report.vat_breakdown else {},
                "category_breakdown": json.loads(z_report.category_breakdown) if z_report.category_breakdown else {},
                "payment_breakdown": json.loads(z_report.payment_breakdown) if z_report.payment_breakdown else [],
            }
            _print_company_info(printer, settings)
            printer.text("\n")
            _print_report_header(printer, "Z REPORT", z_report.report_number, z_report.period_start, z_report.period_end)
            _print_report_totals(printer, currency, totals)
            printer.text("\n")

            printer.cut()
        except PrinterError:
            raise
        except Exception as e:
            logger.exception("Failed to print Z report %s", z_report.report_number)
            raise PrinterError(f"Printer connected but failed to print: {e}") from e
        finally:
            printer.close()

    @staticmethod
    def print_invoice(session: Session, invoice: Invoice):
        settings = SettingsService.get_all(session)
        currency = settings.get("currency_symbol", "€")
        printer = _open(settings.get("receipt_printer_vendor_id", ""), settings.get("receipt_printer_product_id", ""))
        try:
            # _print_store_header(printer, settings)
            printer.set(align="left", bold=False)
            if invoice.client_name:
                printer.text(f"Bill to: {invoice.client_name}\n")
            if invoice.client_vat_number:
                printer.text(f"VAT: {invoice.client_vat_number}\n")
            if invoice.client_address:
                printer.text(f"{invoice.client_address}\n")
            printer.text("-" * LINE_WIDTH + "\n")
            _print_line_items(printer, Cart.from_snapshot(invoice.line_items_snapshot), currency)
            _print_totals(printer, currency, invoice.tax_amount, invoice.final_amount)
            _print_footer(printer, invoice.invoice_number, invoice.issued_at, settings.get("receipt_footer", ""))
            printer.cut()
        except PrinterError:
            raise
        except Exception as e:
            logger.exception("Failed to print invoice %s", invoice.invoice_number)
            raise PrinterError(f"Printer connected but failed to print: {e}") from e
        finally:
            printer.close()
