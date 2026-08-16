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
python main.py
```

The SQLite database is created automatically at:
- **Linux:** `~/.local/share/SuperPOS/superpos.db`
- **Windows:** `%APPDATA%\SuperPOS\superpos.db`

---

## Testing

```bash
pip install -r requirements-dev.txt
pytest
```

Tests use `pytest-qt` to exercise PyQt6 widgets/dialogs alongside the service-layer and database logic. Configuration lives in `pytest.ini`.

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
├── requirements.txt
├── requirements-dev.txt           # Test dependencies (pytest, pytest-qt, pytest-cov)
├── pytest.ini
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
│   │   ├── sales_service.py       # Cart, checkout, invoice/void logic
│   │   ├── client_service.py      # Client CRUD
│   │   ├── settings_service.py    # App settings
│   │   ├── receipt_service.py     # ESC/POS receipt printing, cash drawer kick
│   │   └── label_service.py       # ZPL shelf-label printing
│   ├── reports/                   # Sales report generation
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

---

## Roadmap (future versions)

- [ ] Void/refund UI
- [ ] Customer display support
- [ ] Export reports to Excel/PDF
- [ ] Supplier/purchase orders
- [ ] User accounts and shift management
- [ ] Backup and restore
