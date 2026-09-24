# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
source venv/bin/activate        # Linux/Mac (venv/ already exists in this repo)
pip install -r requirements.txt # app deps AND test deps (pytest, pytest-qt) live in one file — no requirements-dev.txt
python main.py                  # run the app

pytest                          # run full suite (no pytest.ini/pyproject.toml — plain pytest discovery of tests/)
pytest tests/test_sales_service.py            # single file
pytest tests/test_sales_service.py::test_foo  # single test
pytest -k promo                 # by keyword

pyinstaller superpos.spec       # build Windows .exe (must run on Windows/Windows VM) -> dist/
```

The SQLite DB lives outside the repo at `~/.local/share/SuperPOS/superpos.db` (Linux) / `%APPDATA%\SuperPOS\superpos.db` (Windows), created automatically by `init_db()` on first launch. Tests never touch it — every fixture in `tests/conftest.py` uses an isolated in-memory SQLite engine (`db_session`, or `seeded_session` which runs the real `_seed_defaults()` seeding logic).

## Architecture

**Entry point** (`main.py`): sets up logging/global excepthook (`app/utils/error_handling.py`), loads `resources/styles/main.qss`, calls `init_db()`, launches `MainWindow`.

**Layers**: `app/models` (SQLAlchemy ORM) → `app/core` (services: all business logic, DB session handling, external I/O) → `app/ui` (PyQt6 screens/dialogs/widgets, no direct DB access — goes through services).

**UI structure** (`app/ui/main_window.py`): a persistent header + up to 5 independent "V-tabs" (`MAX_VTABS`), each a full ticket with its own cart/held state, switching between a `QStackedWidget` of screens (POS, Inventory, Clients, Reports, Settings). Each V-tab remembers which screen it last had open.

**Cart/checkout model** (`app/core/sales_service.py`): `Cart.entries` is a flat, ordered list of `ReceiptEntry` subclasses — `CartItem`, `SubtotalMarker`, `DiscountEntry`, `PaymentEntry` — mirroring exactly what prints on the receipt, rather than separate line-items/discounts/payments collections. Reopening a held/completed sale replays this list from `sales.cart_snapshot` (JSON) instead of reconstructing it from totals. A reversal of a line on a reopened sale is a new `CartItem` with `is_reversal=True` / `reversal_of` pointing at the original, not a mutation of the original row.

**Schema migrations** (`app/core/database.py`): no Alembic. `init_db()` calls `Base.metadata.create_all()` (creates missing tables only, never alters existing ones) then `_run_migrations()`. Simple added columns are declared in the `_COLUMN_MIGRATIONS` list (table, column, type, `why`) and applied idempotently by `_add_column_if_missing`; each carries a `why` explaining the feature that introduced it, doubling as an in-code schema changelog. Anything bigger (rename, table rebuild, data reshaping — e.g. `_migrate_promo_schema`, `_migrate_clients_to_partial_unique`) gets its own function, run unconditionally and idempotently on every startup (each checks current state before acting). When adding a schema change, follow this pattern rather than introducing a migration framework.

**VAT / invoicing**: `app/constants/countries.py` classifies a client's country as domestic (Belgium), EU (reverse-charge), or non-EU (export) — the latter two are zero-rated. `Cart._effective_price()` nets VAT out of the domestic price for non-domestic clients. `Invoice` rows are immutable, frozen snapshots (client name/address/VAT/amounts/line items as of issue time) independent of the live `Sale`/`Client` — once `sent_at` is set, an invoice can no longer be edited and corrections must go through a credit note instead (see `_INVOICE_SNAPSHOT_WHY` in `database.py`).

**ERP integration** (`app/core/erp_service.py`, `app/core/erp_worker.py`): `ErpService` talks to Odoo's JSON-2 REST API to create/post/send invoices (`account.move`), creating `res.partner` records as needed with Peppol/UBL BIS3 fields. Peppol sending in `ErpService.send_invoice()` is currently commented out (email-only for now) while that flow is validated — check current state there before assuming Peppol is live. Because these are synchronous, multi-round-trip `requests` calls, the full create→post→send sequence runs off the UI thread via `InvoiceSendWorker` (`QThread`); its `succeeded`/`duplicate`/`failed` signals are queued back onto the UI thread for the connecting slot.

**Hardware I/O**: receipt printing/cash-drawer kick via `python-escpos` (`app/core/receipt_service.py`), shelf-label printing via raw ZPL over `pyusb` (`app/core/label_service.py`). Both printers are identified by USB vendor/product ID stored in `Settings` and configured in the Settings screen. The barcode scanner needs no driver — it acts as a keyboard (wedge input).

**Constants** (`app/constants/`): shared UI sizing/spacing/colors/fonts live here rather than being hardcoded per-screen — check here before adding new magic numbers to a screen.
