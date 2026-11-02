"""
Widget dimension constants (heights, widths, fixed sizes) shared across the UI.

Grouped by the screen/widget that uses them; each name says what it sizes and
each comment lists the exact rows/buttons/fields it is applied to. Values are pixels.
"""

# ── Main window ──────────────────────────────────────────────────────────
MAIN_WINDOW_SIZE = (1024, 768)         # fixed window size
TAB_BAR_MIN_HEIGHT = 45                # V-tab button bar — min height (2px margins + 41px buttons/clock box)
TAB_BAR_MAX_HEIGHT = 45                # V-tab button bar — max height
VTAB_BUTTON_HEIGHT = 35                # each V-tab button (TicketTab) — min content height; keep equal to min-height in main.qss (+2px padding, 1px border each side = 41px)
ERROR_BADGE_WIDTH = 140                # error badge in the V-tab bar — fixed, so the V-tabs don't resize when it fills/empties

# ── POS screen: cart / ticket ────────────────────────────────────────────
CART_ROW_HEIGHT = 21                   # every cart row: items, discount, subtotal, paid, payment & change rows
CART_INFO_BAR_HEIGHT = 21              # client label, running total label, scan/amount input and paid-ticket footer under the cart — min height

# ── Customer display (app/ui/customer_display.py) ────────────────────────
CUSTOMER_DISPLAY_WINDOW_SIZE = (800, 600)  # initial (width, height) when shown as a normal window (no second monitor)

# ── Shared buttons (app/utils/utils.py) ──────────────────────────────────
FUNCTION_BUTTON_HEIGHT = 40            # every FunctionButton (POS, Inventory, Clients, Reports, Settings, dialogs), every
                                       # CategoryButton (POS shortcut selector & product slots) and the POS numpad keys — min height
# ── Inventory / Clients screens ──────────────────────────────────────────
LIST_ACTION_BUTTON_HEIGHT = 26         # action-button grid beside the list (new/modify/delete, up/down, search, OK, …) — min height
LIST_FILTER_HEIGHT = 30                # search box, category filter and "low stock" toggle above the list
FORM_FIELD_HEIGHT = 24                 # article & client edit-form inputs and FormField inputs — min height
FORM_LABEL_WIDTH = 100                 # label column of a FormField row (label left, input right)

# ── Reports screen ───────────────────────────────────────────────────────
REPORTS_BUTTON_HEIGHT = 40             # date pickers, range dropdown, report-type buttons, X/Z report & OK buttons
REPORT_ROW_HEIGHT = 30                 # rows of the sales, VAT and categories tables

# ── Settings screen ──────────────────────────────────────────────────────
SETTINGS_BUTTON_HEIGHT = 40            # every button on the Settings screen (all tabs incl. Logs, Buttons box, OK) — fixed; labels must fit on one line
LOGO_PREVIEW_SIZE = (120, 60)          # receipt-logo preview box (width, height)
LOG_PANEL_MAX_LINES = 2000             # Logs tab: oldest lines are dropped beyond this (also the startup backlog size)

# ── Dialogs ──────────────────────────────────────────────────────────────
DIALOG_BUTTON_HEIGHT = 40              # every button in every dialog (incl. message boxes) except the numpad keys — enforced by the
                                       # "QDialog QPushButton" rule in main.qss (keep the two in sync); also the promo dialog's table rows,
                                       # which hold a Remove button
NUMPAD_DIALOG_WIDTH = 300              # numpad dialog — min width
NUMPAD_DIALOG_KEY_HEIGHT = 48          # numpad dialog keys and its display field — min height (keys: also in main.qss, keep in sync)
PAYMENT_DIALOG_WIDTH = 400             # payment dialog — min width
PAYMENT_AMOUNT_INPUT_HEIGHT = 40       # payment dialog tendered-amount input
PAYMENT_METHOD_BUTTON_HEIGHT = 44      # payment dialog cash/card method buttons
PAYMENT_CONFIRM_BUTTON_HEIGHT = 54     # payment dialog Confirm button
STOCK_ADJUST_DIALOG_WIDTH = 420        # stock adjustment dialog — min width
INVENTORY_FORMAT_DIALOG_WIDTH = 300    # inventory format (PDF/CSV) dialog — min width
SHORTCUT_DIALOG_MIN_SIZE = (680, 460)  # shortcut dialog — min (width, height)
PROMO_DIALOG_MIN_SIZE = (820, 520)     # promo dialog — min (width, height)
LABEL_SHEET_DIALOG_WIDTH = 480         # label sheet (print barcodes) dialog — min width
LABEL_SHEET_FIELD_HEIGHT = 24          # label sheet dialog name/manufacturer/lot/expiry/barcode inputs — min height
BACKUP_DIALOG_MIN_SIZE = (760, 500)    # backup dialog — min (width, height)
Z_REPORTS_DIALOG_MIN_SIZE = (700, 460) # Z reports (reprint) dialog — min (width, height)
Z_PROGRESS_DIALOG_WIDTH = 480          # Z report progress popup (backup → close → backup → print) — min width
Z_PROGRESS_BAR_HEIGHT = 32             # its progress bar

# ── Tap-to-dismiss overlay (app/utils/utils.py) ──────────────────────────
OVERLAY_CARD_MIN_WIDTH = 360           # message card shown over a screen (e.g. "Enter an amount first") — min width
OVERLAY_CARD_MAX_WIDTH = 520           # same card — max width

__all__ = [
                                       "BACKUP_DIALOG_MIN_SIZE",
                                       "CART_INFO_BAR_HEIGHT",
                                       "CART_ROW_HEIGHT",
                                       "CUSTOMER_DISPLAY_WINDOW_SIZE",
                                       "DIALOG_BUTTON_HEIGHT",
                                       "ERROR_BADGE_WIDTH",
                                       "FORM_FIELD_HEIGHT",
                                       "FORM_LABEL_WIDTH",
                                       "FUNCTION_BUTTON_HEIGHT",
                                       "INVENTORY_FORMAT_DIALOG_WIDTH",
                                       "LABEL_SHEET_DIALOG_WIDTH",
                                       "LABEL_SHEET_FIELD_HEIGHT",
                                       "LIST_ACTION_BUTTON_HEIGHT",
                                       "LIST_FILTER_HEIGHT",
                                       "LOGO_PREVIEW_SIZE",
                                       "LOG_PANEL_MAX_LINES",
                                       "MAIN_WINDOW_SIZE",
                                       "NUMPAD_DIALOG_KEY_HEIGHT",
                                       "NUMPAD_DIALOG_WIDTH",
                                       "OVERLAY_CARD_MAX_WIDTH",
                                       "OVERLAY_CARD_MIN_WIDTH",
                                       "PAYMENT_AMOUNT_INPUT_HEIGHT",
                                       "PAYMENT_CONFIRM_BUTTON_HEIGHT",
                                       "PAYMENT_DIALOG_WIDTH",
                                       "PAYMENT_METHOD_BUTTON_HEIGHT",
                                       "PROMO_DIALOG_MIN_SIZE",
                                       "REPORTS_BUTTON_HEIGHT",
                                       "REPORT_ROW_HEIGHT",
                                       "SETTINGS_BUTTON_HEIGHT",
                                       "SHORTCUT_DIALOG_MIN_SIZE",
                                       "STOCK_ADJUST_DIALOG_WIDTH",
                                       "TAB_BAR_MAX_HEIGHT",
                                       "TAB_BAR_MIN_HEIGHT",
                                       "VTAB_BUTTON_HEIGHT",
                                       "Z_PROGRESS_BAR_HEIGHT",
                                       "Z_PROGRESS_DIALOG_WIDTH",
                                       "Z_REPORTS_DIALOG_MIN_SIZE",
]
