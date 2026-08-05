"""Colors used directly in Python.

Most colors live in resources/styles/main.qss; these are the few that
must be set programmatically via QColor because QSS cannot target
QTableWidgetItem backgrounds.
"""

COLOR_ROW_PENDING = (255, 230, 120)
COLOR_ROW_DISCOUNT = (145, 230, 120)
COLOR_ROW_PAYMENT = (176, 216, 230)
COLOR_ROW_PAYMENT_DARK = (135, 185, 215)

COLOR_BORDER_LIGHT = "#ccc"

__all__ = [
    "COLOR_ROW_PENDING",
    "COLOR_ROW_DISCOUNT",
    "COLOR_ROW_PAYMENT",
    "COLOR_ROW_PAYMENT_DARK",
    "COLOR_BORDER_LIGHT",
]
