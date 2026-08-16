"""Font sizes used when building QFont objects in Python.

Font family/size rules driven by resources/styles/main.qss are not
duplicated here; this covers only fonts set programmatically (e.g. on
the cart table and payment footer, which QSS cannot target per-item).
"""

FONT_SIZE_CART_ROW = 15
FONT_SIZE_CART_ITEM = 20
FONT_SIZE_FOOTER_TOTAL = 30

__all__ = [
    "FONT_SIZE_CART_ROW",
    "FONT_SIZE_CART_ITEM",
    "FONT_SIZE_FOOTER_TOTAL",
]
