# POS

A self-contained supermarket Point of Sale application built with Python + PyQt6 and SQLAlchemy/SQLite.

## Features

- **POS Screen**
  - Up to 5 independent ticket tabs ("V-tabs"), each with its own cart, held/reopened state, and B2B flag
  - Barcode scan (via keyboard-wedge scanner) or manual product search
  - Percentage and fixed-amount discounts, per item or per subtotal section
  - Cash and card payment, with change calculation
  - Invoice (B2B) mode — link a sale to a client and issue an immutable invoice, independent of the sale record
  - Reopen a previously completed ticket for corrections
  - Receipt printing and cash drawer kick via the configured USB receipt printer

- **Inventory**
  - Add/edit products (price, tax rate, unit, barcode, category, stock)
  - Stock adjustments (stock in/out) with movement history
  - Low-stock indicators
  - CSV import/export of the article catalog
  - Shelf label printing (ZPL, EAN-13 barcode) via a USB Zebra-compatible label printer

- **Clients**
  - Client directory (name, address, phone, email, VAT number, website) for B2B invoicing
  - Soft delete (deactivate) with reusable name/contact fields
  - CSV import/export

- **Reports**
  - Date-range sales reports with tax breakdown

- **Settings**
  - Store info (name, address, phone, VAT number, logo), currency symbol, receipt footer text
  - Receipt printer and label printer configuration (USB vendor/product ID)

---

## Setup (Development — Linux or Windows)

### 1. Create a virtual environment
```bash
python3.12 -m venv venv
source venv/bin/activate        # Linux/Mac
venv\Scripts\activate           # Windows
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Run the app
```bash
python main.py             # full screen, no title bar (close via Alt+F4 / Task Manager)
python main.py --windowed  # normal window, for development
```

The SQLite database is created automatically at:
- **Linux:** `~/.local/share/SuperPOS/superpos.db`
- **Windows:** `%APPDATA%\SuperPOS\superpos.db`

---

## Testing

```bash
pip install -r requirements.txt
pytest
```

Tests use `pytest-qt` to exercise PyQt6 widgets/dialogs alongside the service-layer and database logic. Test dependencies (`pytest`, `pytest-qt`) are included in `requirements.txt`; there's no separate dev-requirements file or pytest config file — `pytest` uses plain discovery of `tests/`.

---

## Building a Windows Executable

On a Windows machine (or Windows VM):
```bash
pip install -r requirements.txt
pyinstaller superpos.spec
```
The standalone `.exe` will be in the `dist/` folder.

---

## Project Structure

```
pos/
├── main.py                        # Entry point
├── requirements.txt                # App deps + test deps (pytest, pytest-qt)
├── superpos.spec                  # PyInstaller build config
├── resources/
│   ├── icons/                     # Logo and app icons
│   └── styles/
│       └── main.qss               # Dark theme stylesheet
├── app/
│   ├── constants/                 # Colors, fonts, sizes, spacing shared across the UI
│   ├── models/
│   │   └── models.py              # SQLAlchemy ORM models (Product, Category, Sale, SaleItem,
│   │                               #  StockMovement, Client, Invoice, Settings)
│   ├── core/
│   │   ├── database.py            # DB init, session factory, lightweight migrations
│   │   ├── product_service.py     # Product & inventory logic
│   │   ├── sales_service.py       # Cart, checkout, invoice logic
│   │   ├── client_service.py      # Client CRUD
│   │   ├── settings_service.py    # App settings
│   │   ├── receipt_service.py     # ESC/POS receipt printing, cash drawer kick
│   │   ├── label_service.py       # ZPL shelf-label printing
│   │   ├── report_service.py      # Sales report generation
│   │   ├── erp_service.py         # Odoo JSON-2 API client (invoice create/post/send)
│   │   └── erp_worker.py          # Runs erp_service calls off the UI thread
│   ├── utils/
│   │   ├── error_handling.py      # Logging setup + global exception hook
│   │   └── utils.py                # Shared UI helpers (e.g. TicketTab)
│   └── ui/
│       ├── main_window.py         # Root window, header, V-tab bar
│       ├── pos_screen.py          # Checkout screen
│       ├── inventory_screen.py    # Product management, CSV import/export, labels
│       ├── client_screen.py       # Client management, CSV import/export
│       ├── reports_screen.py      # Sales reports
│       ├── settings_screen.py     # Configuration
│       ├── widgets/
│       │   └── form_fields.py     # Reusable form field widgets
│       └── dialogs/
│           ├── payment_dialog.py          # Cash/card payment
│           ├── stock_adjustment_dialog.py # Stock in/out
│           ├── numpad_dialog.py           # On-screen numeric entry
│           └── file_dialog.py             # CSV import/export file picker
└── tests/                         # pytest + pytest-qt test suite
```

---

## Hardware Notes

| Device | How it works |
|---|---|
| Barcode scanner (USB) | Acts as keyboard input — no driver needed |
| Receipt printer (USB) | Configure Vendor/Product ID in Settings. Uses `python-escpos`; also drives the cash drawer kick |
| Label printer (USB, Zebra-compatible) | Configure Vendor/Product ID in Settings. Prints ZPL labels (name, EAN-13 barcode, price) directly over USB via `pyusb` |
| Cash drawer | Triggered via the receipt printer port |

### Printer setup on Windows (Zadig / WinUSB)

Vendor/Product IDs belong to the printer model, not the PC, so the same printer has the same IDs everywhere. What has to be redone on **every new Windows PC** is the driver: Windows binds its own `usbprint` driver, which libusb/pyusb can't talk to.

1. **Swap the driver to WinUSB** (once per printer, per PC)
   - Download and run [Zadig](https://zadig.akeo.ie).
   - **Options → List All Devices**, then pick the receipt printer in the dropdown. If it's a composite device, pick **Interface 0**.
   - Set the target driver to **WinUSB** and click **Replace Driver**.
   - Repeat for the label printer, then unplug and replug both.
   - Windows may tie the driver to the USB port, so if a printer moves to another port, run Zadig again.
2. **Find the IDs** (if they aren't known yet)
   - Device Manager → printer → Properties → Details → *Hardware Ids*, e.g. `USB\VID_04B8&PID_0202`, or in PowerShell:
     ```powershell
     Get-PnpDevice -PresentOnly | Where-Object InstanceId -like 'USB\VID_*' | Select FriendlyName, InstanceId
     ```
3. **Enter them in Settings** as hex with `0x`: `VID_04B8` → `0x04b8`, `PID_0202` → `0x0202`. Save, then use the test print buttons.

**Troubleshooting** (details in `logs/` next to the DB):
- *"not found"*: wrong IDs, or the printer isn't connected.
- *"Could not connect…"* / access errors: the Zadig step is missing.
- Printer settings live in the DB (`%APPDATA%\SuperPOS`), so a fresh install starts with empty fields. Restoring a backup brings the IDs back but not the WinUSB driver.
- The receipt printer's USB endpoints are hardcoded (`in_ep=0x81, out_ep=0x01` in `app/core/receipt_service.py`). A different receipt printer model may need other values. The label printer detects its endpoint automatically.

On Linux, no driver swap is needed (it uses the system `libusb-1.0`), but the user needs permission to access the USB device (e.g. a udev rule).

---

## Roadmap (future versions)

- [ ] Void/refund UI
- [ ] Customer display support
- [ ] Export reports to Excel/PDF
- [ ] Supplier/purchase orders
- [ ] User accounts and shift management
- [ ] Backup and restore
