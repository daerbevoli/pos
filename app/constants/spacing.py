"""
Layout spacing constants (margins/gaps) shared across the UI. Values are pixels.
"""

SPACING_XS = 2   # gaps in the V-tab bar; POS cart column, function/payment buttons, numpad & shortcut/product grid; inventory & client form and button grid; FormField rows; label sheet dialog layout-button grid
SPACING_SM = 6   # gaps between the POS screen's main sections; numpad dialog key grid; reports screen control-grid columns
SPACING_MD = 8   # inventory & client edit panels, numpad dialog layout, tap-to-dismiss overlay card; settings screen sections
SPACING_LG = 4  # reports screen gap separating the range/view columns from the report/action columns

MARGIN_NONE = (0, 0, 0, 0)  # tap-to-dismiss overlay (full-screen, no margins)
MARGIN_SETTINGS = (10, 10, 10, 10)  # settings screen edge; kept tight so the General tab fits the 768px window

__all__ = [
    "SPACING_XS",
    "SPACING_SM",
    "SPACING_MD",
    "SPACING_LG",
    "MARGIN_NONE",
    "MARGIN_SETTINGS",
]
