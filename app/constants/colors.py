"""Colors used directly in Python.

Most colors live in resources/styles/main.qss; these are the few that
must be set programmatically via QColor because QSS cannot target
QTableWidgetItem backgrounds. RGB tuples unless noted.
"""

# ── POS cart rows (open ticket) ──────────────────────────────────────────
COLOR_ROW_PENDING = (255, 230, 120)         # item row still waiting for a price or weight ("?")
COLOR_ROW_SUMMARY = (238, 226, 218)         # SUBTOTAL and discount rows — one tint darker than the cart background
COLOR_ROW_PAYMENT = (176, 216, 230)         # "PAID Cash/Card" partial-payment rows; method rows of a paid ticket
COLOR_ROW_CHANGE = (135, 185, 215)          # "Change" row of a paid ticket
COLOR_ROW_DIVIDER = (204, 197, 190)         # thin line separating the items from the payment rows

# ── POS cart rows (frozen / paid ticket) ─────────────────────────────────
COLOR_ROW_FROZEN = (204, 197, 190)          # every row of a paid ticket
COLOR_ROW_DIVIDER_FROZEN = (184, 176, 168)  # divider line on a paid ticket

# ── Settings screen ──────────────────────────────────────────────────────
COLOR_LOGO_PREVIEW_BORDER = "#ccc"          # border around the receipt-logo preview box

__all__ = [
    "COLOR_ROW_PENDING",
    "COLOR_ROW_SUMMARY",
    "COLOR_ROW_PAYMENT",
    "COLOR_ROW_CHANGE",
    "COLOR_ROW_DIVIDER",
    "COLOR_ROW_FROZEN",
    "COLOR_ROW_DIVIDER_FROZEN",
    "COLOR_LOGO_PREVIEW_BORDER",
]
