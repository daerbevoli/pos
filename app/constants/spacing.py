"""Layout spacing constants (margins/gaps) shared across the UI. Values are pixels."""

SPACING_XS = 2   # gaps in the V-tab bar; POS cart column, function/payment buttons, numpad & shortcut/product grid; inventory & client form and button grid; FormField rows
SPACING_SM = 6   # gaps between the POS screen's main sections; numpad dialog key grid
SPACING_MD = 8   # inventory & client edit panels, numpad dialog layout, tap-to-dismiss overlay card

MARGIN_NONE = (0, 0, 0, 0)  # tap-to-dismiss overlay (full-screen, no margins)

__all__ = [
    "SPACING_XS",
    "SPACING_SM",
    "SPACING_MD",
    "MARGIN_NONE",
]
