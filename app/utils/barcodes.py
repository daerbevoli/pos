"""
Which symbology prints a stored barcode so that scanning the label gives the
same digits back. EAN-13/UPC-A/EAN-8 only when the code has exactly that
length and a valid check digit: the printers (ZPL and reportlab alike) add
or recompute the check digit themselves, so anything else would print a
different number. Everything else prints as Code 128, which encodes any
text as is.
"""


def gtin_check_digit(data: str) -> str:
    """Check digit for an EAN-13/UPC-A/EAN-8 code without its last digit."""
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(data)))
    return str((10 - total % 10) % 10)


_GTIN_LENGTHS = {13: "EAN13", 12: "UPCA", 8: "EAN8"}


def barcode_symbology(barcode: str) -> str:
    """"EAN13", "UPCA", "EAN8" or "Code128"."""
    kind = _GTIN_LENGTHS.get(len(barcode))
    if kind and barcode.isdigit() and gtin_check_digit(barcode[:-1]) == barcode[-1]:
        return kind
    return "Code128"
