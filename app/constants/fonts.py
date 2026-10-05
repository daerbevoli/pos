"""Font sizes used when building QFont objects in Python.

Font family/size rules driven by resources/styles/main.qss are not
duplicated here; this covers only fonts set programmatically (e.g. on
the cart table and payment footer, which QSS cannot target per-item).
Values are pixels.
"""

# ── POS screen ───────────────────────────────────────────────────────────
FONT_SIZE_CART = 18         # every cart row: items, discount, subtotal, paid, payment & change rows
FONT_SIZE_PAID_FOOTER = 30  # "Total" and "Change" labels in the footer under a paid ticket

__all__ = [
    "FONT_SIZE_CART",
    "FONT_SIZE_PAID_FOOTER",
]
