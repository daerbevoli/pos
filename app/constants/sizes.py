"""Widget dimension constants (heights, widths, fixed sizes) shared across the UI.

Grouped by the screen/widget that uses them; each name says what it sizes and
each comment lists the exact rows/buttons/fields it is applied to. Values are pixels.
"""

# ── Main window ──────────────────────────────────────────────────────────
MAIN_WINDOW_SIZE = (1024, 768)         # fixed window size
TAB_BAR_MIN_HEIGHT = 44                # V-tab button bar — min height
TAB_BAR_MAX_HEIGHT = 56                # V-tab button bar — max height
VTAB_BUTTON_HEIGHT = 40                # each V-tab button (TicketTab) — min height
ERROR_BADGE_WIDTH = 140                # error badge in the V-tab bar — fixed, so the V-tabs don't resize when it fills/empties

# ── POS screen: cart / ticket ────────────────────────────────────────────
CART_ROW_HEIGHT = 21                   # every cart row: items, discount, subtotal, paid, payment & change rows
CART_INFO_BAR_HEIGHT = 21              # client label, running total label, scan/amount input and paid-ticket footer under the cart — min height

# ── Customer display (app/ui/customer_display.py) ────────────────────────
CUSTOMER_DISPLAY_WINDOW_SIZE = (800, 600)  # initial (width, height) when shown as a normal window (no second monitor)

# ── Shared buttons (app/utils/utils.py) ──────────────────────────────────
FUNCTION_BUTTON_HEIGHT = 36            # every FunctionButton (POS, Inventory, Clients, Reports, Settings, dialogs), every
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
SETTINGS_OK_BUTTON_HEIGHT = 40         # OK (save) button at the bottom of the screen
SETTINGS_FUNCTION_BUTTON_HEIGHT = 60   # Admin / RF-CN / Reports buttons in the Buttons box below the tabs
LOGO_PREVIEW_SIZE = (120, 60)          # receipt-logo preview box (width, height)
LOG_PANEL_MAX_LINES = 2000             # Logs tab: oldest lines are dropped beyond this (also the startup backlog size)

# ── Dialogs ──────────────────────────────────────────────────────────────
DIALOG_BUTTON_HEIGHT = 40              # OK / Cancel buttons of the category, file, shortcut, promo, backup and Z reports dialogs;
                                       # labels-per-page and Cancel buttons of the label sheet dialog
NUMPAD_DIALOG_WIDTH = 300              # numpad dialog — min width
NUMPAD_DIALOG_KEY_HEIGHT = 48          # numpad dialog keys and its display field — min height
NUMPAD_DIALOG_OK_HEIGHT = 44           # numpad dialog OK button — min height
PAYMENT_DIALOG_WIDTH = 400             # payment dialog — min width
PAYMENT_AMOUNT_INPUT_HEIGHT = 40       # payment dialog tendered-amount input
PAYMENT_METHOD_BUTTON_HEIGHT = 44      # payment dialog cash/card method buttons
PAYMENT_CONFIRM_BUTTON_HEIGHT = 54     # payment dialog Confirm button
STOCK_ADJUST_DIALOG_WIDTH = 420        # stock adjustment dialog — min width
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
    "MAIN_WINDOW_SIZE",
    "TAB_BAR_MIN_HEIGHT",
    "TAB_BAR_MAX_HEIGHT",
    "VTAB_BUTTON_HEIGHT",
    "ERROR_BADGE_WIDTH",
    "CART_ROW_HEIGHT",
    "CART_INFO_BAR_HEIGHT",
    "CUSTOMER_DISPLAY_WINDOW_SIZE",
    "FUNCTION_BUTTON_HEIGHT",
    "LIST_ACTION_BUTTON_HEIGHT",
    "LIST_FILTER_HEIGHT",
    "FORM_FIELD_HEIGHT",
    "FORM_LABEL_WIDTH",
    "REPORTS_BUTTON_HEIGHT",
    "REPORT_ROW_HEIGHT",
    "SETTINGS_OK_BUTTON_HEIGHT",
    "SETTINGS_FUNCTION_BUTTON_HEIGHT",
    "LOGO_PREVIEW_SIZE",
    "LOG_PANEL_MAX_LINES",
    "DIALOG_BUTTON_HEIGHT",
    "NUMPAD_DIALOG_WIDTH",
    "NUMPAD_DIALOG_KEY_HEIGHT",
    "NUMPAD_DIALOG_OK_HEIGHT",
    "PAYMENT_DIALOG_WIDTH",
    "PAYMENT_AMOUNT_INPUT_HEIGHT",
    "PAYMENT_METHOD_BUTTON_HEIGHT",
    "PAYMENT_CONFIRM_BUTTON_HEIGHT",
    "STOCK_ADJUST_DIALOG_WIDTH",
    "SHORTCUT_DIALOG_MIN_SIZE",
    "PROMO_DIALOG_MIN_SIZE",
    "LABEL_SHEET_DIALOG_WIDTH",
    "LABEL_SHEET_FIELD_HEIGHT",
    "BACKUP_DIALOG_MIN_SIZE",
    "Z_REPORTS_DIALOG_MIN_SIZE",
    "Z_PROGRESS_DIALOG_WIDTH",
    "Z_PROGRESS_BAR_HEIGHT",
    "OVERLAY_CARD_MIN_WIDTH",
    "OVERLAY_CARD_MAX_WIDTH",
]
