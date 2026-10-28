# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
source venv/bin/activate        # Linux/Mac (venv/ already exists in this repo)
pip install -r requirements.txt # app deps AND test deps (pytest, pytest-qt) live in one file — no requirements-dev.txt
python main.py                  # run the app (currently always a normal window: the full-screen switch in main.py is commented out)

pytest                          # run full suite (no pytest.ini/pyproject.toml — plain pytest discovery of tests/)
pytest tests/test_sales_service.py            # single file
pytest tests/test_sales_service.py::test_foo  # single test
pytest -k promo                 # by keyword

pyinstaller superpos.spec       # build Windows .exe (must run on Windows/Windows VM) -> dist/
```

Logs go to a `logs/` folder next to the DB (never the working directory: the one-file .exe may start anywhere; bundled resources are read via `sys._MEIPASS`, see `main.py`). The SQLite DB lives outside the repo at `~/.local/share/SuperPOS/superpos.db` (Linux) / `%APPDATA%\SuperPOS\superpos.db` (Windows), created automatically by `init_db()` on first launch. Tests never touch it — every fixture in `tests/conftest.py` uses an isolated in-memory SQLite engine (`db_session`, or `seeded_session` which runs the real `_seed_defaults()` seeding logic).

## Architecture

**Entry point** (`main.py`): sets up logging/global excepthook (`app/utils/error_handling.py`), loads `resources/styles/main.qss`, calls `init_db()`, launches `MainWindow`.

**Layers**: `app/models` (SQLAlchemy ORM) → `app/core` (services: all business logic, DB session handling, external I/O) → `app/ui` (PyQt6 screens/dialogs/widgets, no direct DB access — goes through services).

**UI structure** (`app/ui/main_window.py`): a persistent header + up to 5 independent "V-tabs" (`MAX_VTABS`), each a full ticket with its own cart/held state, switching between a `QStackedWidget` of screens (POS, Inventory, Clients, Reports, Settings). Each V-tab remembers which screen it last had open.

**Cart/checkout model** (`app/core/cart.py`, pure in-memory, no DB; saving/invoicing lives in `app/core/sales_service.py`): `Cart.entries` is a flat, ordered list of `ReceiptEntry` subclasses — `CartItem`, `SubtotalMarker`, `DiscountEntry`, `PaymentEntry` — mirroring exactly what prints on the receipt, rather than separate line-items/discounts/payments collections. Reopening a held/completed sale replays this list from `sales.cart_snapshot` (JSON) instead of reconstructing it from totals. A reversal of a line on a reopened sale is a new `CartItem` with `is_reversal=True` / `reversal_of` pointing at the original, not a mutation of the original row. Discounts store explicit `allocations` (which items they reduce, and by how much) in the snapshot; `Cart.net_lines()` is the single source of per-line net amounts used by the till total, receipts, reports and invoices — `tests/test_cart_invariants.py` checks they all agree on random tickets.

**Schema migrations** (`app/core/database.py`): no Alembic. `init_db()` calls `Base.metadata.create_all()` (creates missing tables only, never alters existing ones) then `_run_migrations()`. Simple added columns are declared in the `_COLUMN_MIGRATIONS` list (table, column, type, `why`) and applied idempotently by `_add_column_if_missing`; each carries a `why` explaining the feature that introduced it, doubling as an in-code schema changelog. Anything bigger (rename, table rebuild, data reshaping) gets its own function called from `_run_migrations()`, run unconditionally and idempotently on every startup (each checks current state before acting). The list is currently empty: the schema was reset to a clean baseline before the first shop went live, so add entries only for changes made after that. When adding a schema change, follow this pattern rather than introducing a migration framework.

**VAT / invoicing**: `app/constants/countries.py` classifies a client's country as domestic (Belgium), EU (reverse-charge), or non-EU (export) — the latter two are zero-rated. `Cart._effective_price()` nets VAT out of the domestic price for non-domestic clients. `Invoice` rows are immutable, frozen snapshots (client name/address/VAT/amounts/line items as of issue time) independent of the live `Sale`/`Client` — once `sent_at` is set, an invoice can no longer be edited and corrections must go through a credit note instead.

**ERP integration** (`app/core/erp_service.py`, `app/core/erp_worker.py`): `ErpService` talks to Odoo's JSON-2 REST API to create/post/send invoices (`account.move`), creating `res.partner` records as needed with Peppol/UBL BIS3 fields. Peppol is a `send_invoice()` parameter; the POS currently passes `use_peppol=False, use_email=True` (email-only while Peppol is validated) — check `_send_invoice` in `pos_screen.py` before assuming Peppol is live. Because these are synchronous, multi-round-trip `requests` calls, the full create→post→send sequence runs off the UI thread via `InvoiceSendWorker` (`QThread`); its `succeeded`/`failed` signals are queued back onto the UI thread for the connecting slot. Quitting waits for running sends (`InvoiceSendWorker.wait_for_all`).

**Backups** (`app/core/backup_service.py`): zip archives written to `<db dir>/backups` and an optional extra folder (`backup_extra_dir` setting, e.g. a USB stick). Snapshots use SQLite's online backup API (never a file copy — the DB is in WAL mode), are integrity-checked, written as `.partial` and renamed only after re-verification. Taken daily at noon (`MainWindow` checks `daily_backup_due()` every minute, catching up if the POS was off at noon → `BackupWorker`), before and after every Z report, on demand, and before a restore. Quitting waits for running workers (`BackupWorker.wait_for_all`). Restore (admin-only, `BackupDialog`) verifies the archive, takes a pre-restore backup, copies into the live DB in one transaction, then restarts the app. Once a backup password is set (Backup dialog, admin), archives are format 2: `superpos.db.enc` (zlib + AES-256-GCM, key from scrypt with a per-archive salt; the manifest is authenticated as AAD and holds no data). Without one they're format 1 (`superpos.db` + manifest with SHA-256/row counts). The password is stored DPAPI-protected in `backup_password.bin` next to the DB (`app/core/backup_key.py`), never in the DB; an unreadable stored password makes backups fail rather than fall back to plaintext. Restoring an encrypted archive always asks for its password. Tests: `patched_db` points `DB_PATH` at tmp_path, so nothing touches the real backups folder or password file.

**Z report flow** (`app/ui/dialogs/z_report_progress_dialog.py`): after confirmation, `ZReportProgressDialog` runs backup before → `close_z_report()` → backup after → print, each step on a `_StepWorker` thread feeding a progress bar, decisions (e.g. "continue without a backup?") on the UI thread between steps. The popup is modal with no close button until done, so no sale can be rung up between the pre-Z backup and the purge.

**Hardware I/O**: receipt printing/cash-drawer kick via `python-escpos` (`app/core/receipt_service.py`), shelf-label printing via raw ZPL over `pyusb` (`app/core/label_service.py`). Both printers are identified by USB vendor/product ID stored in `Settings` and configured in the Settings screen. The barcode scanner needs no driver — it acts as a keyboard (wedge input).

**Constants** (`app/constants/`): shared UI sizing/spacing/colors/fonts live here rather than being hardcoded per-screen — check here before adding new magic numbers to a screen.
