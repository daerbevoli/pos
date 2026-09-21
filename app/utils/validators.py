"""VAT number checksum validation.

Odoo rejects a VAT number that has the right shape (country prefix + right
digit count) but fails its country's checksum — catching that here means the
user finds out in the client dialog instead of at invoice-send time.
"""

import re


def is_valid_belgian_vat(vat: str) -> bool:
    """BE VAT: 'BE' + 9 or 10 digits, with a mod-97 check on the last two
    digits against the first eight."""
    match = re.fullmatch(r"BE(\d{9,10})", vat.strip().upper())
    if not match:
        return False
    digits = match.group(1)
    if len(digits) == 9:
        digits = "0" + digits
        # check last 2 digits == 97 - first 8 digits mod 97
    return int(digits[8:]) == 97 - (int(digits[:8]) % 97)


_VALIDATORS = {
    "BE": is_valid_belgian_vat,
}


def is_valid_vat(vat: str, country_code: str) -> bool:
    """True if `vat` passes its country's checksum. Countries without a
    checksum implemented here are not format-checked (returns True)."""
    validator = _VALIDATORS.get(country_code)
    return validator(vat) if validator else True
