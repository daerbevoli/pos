# POS

A self-contained supermarket Point of Sale application built with Python + PyQt6.

## Features
- **POS Screen** — Barcode scan, product search, cart, cash/card payment
- **Inventory** — Add/edit products, stock management, low-stock alerts
- **Reports** — Daily and date-range sales reports
- **Settings** — Store info, tax rate, receipt printer configuration

---

## Setup (Development — Linux or Windows)

### 1. Create a virtual environment
```bash
python3.13 -m venv venv
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
supermarket-pos/
├── main.py                        # Entry point
├── requirements.txt
├── superpos.spec                  # PyInstaller build config
├── resources/
│   └── styles/
│       └── main.qss               # Dark theme stylesheet
└── app/
    ├── models/
    │   └── models.py              # SQLAlchemy ORM models
    ├── core/
    │   ├── database.py            # DB init and session factory
    │   ├── product_service.py     # Product & inventory logic
    │   ├── sales_service.py       # Cart and sales logic
    │   └── settings_service.py   # App settings
    └── ui/
        ├── main_window.py         # Root window + tabs
        ├── pos_screen.py          # Checkout screen
        ├── inventory_screen.py    # Product management
        ├── reports_screen.py      # Sales reports
        ├── settings_screen.py     # Configuration
        └── dialogs/
            ├── payment_dialog.py          # Cash/card payment
            ├── product_search_dialog.py   # POS product search
            ├── product_dialog.py          # Add/edit product
            └── stock_adjustment_dialog.py # Stock in/out
```

---

## Hardware Notes

| Device | How it works |
|---|---|
| Barcode scanner (USB) | Acts as keyboard input — no driver needed |
| Receipt printer (USB) | Configure Vendor/Product ID in Settings. Uses `python-escpos` |
| Label printer (USB) | See `python-brother-label` or `python-escpos` depending on brand |
| Cash drawer | Usually triggered via receipt printer port |

---

## Roadmap (future versions)

- [ ] Receipt printing via `python-escpos`
- [ ] Label printing
- [ ] Void/refund UI
- [ ] Customer display support
- [ ] Export reports to Excel/PDF
- [ ] Supplier/purchase orders
- [ ] User accounts and shift management
- [ ] Backup and restore
