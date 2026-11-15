"""
Fills a separate demo database with random sales (tools/sales_factory.py,
the same generator tests/test_report_invariants.py checks the reports
with) to look at the reports in the app, and prints what they should show.

Never touches the real database: it only writes into a data folder that
has no database yet, which the app is then started on.

    python -m tools.seed_sales C:\\temp\\superpos-demo --days 30 --per-day 60 --seed 1

    $env:APPDATA = "C:\\temp\\superpos-demo"; python main.py    # Windows (PowerShell)
    XDG_DATA_HOME=/tmp/superpos-demo python main.py              # Linux

Every day but today is closed with a Z report; today stays open (Reports
screen, X report). The same --seed and --days/--per-day give the same sales.
"""
import argparse
import os
import random
import sys
from datetime import date, timedelta

# The variable app.core.database.get_db_path() builds the data folder from.
DATA_DIR_VAR = "APPDATA" if sys.platform == "win32" else "XDG_DATA_HOME"


def _real_data_dir() -> str:
    """The folder the app uses when started normally (see get_db_path())."""
    default = os.path.expanduser("~") if sys.platform == "win32" else os.path.expanduser("~/.local/share")
    return os.environ.get(DATA_DIR_VAR, default)


def _same_path(a: str, b: str) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _print_totals(title: str, totals: dict):
    print(f"\n{title}")
    print(f"  transactions {totals['count']}, total {totals['final']:.2f}, VAT {totals['tax']:.2f}")
    print("  paid: " + ", ".join(f"{m} {a:.2f}" for m, a in sorted(totals["payments"].items())))
    for rate, amounts in totals["vat"].items():
        if amounts["total"]:
            base = amounts["total"] - amounts["tax"]
            print(f"  VAT {rate:>2}%: base {base:.2f}, tax {amounts['tax']:.2f}, total {amounts['total']:.2f}")
    print(f"  discounts: manual {totals['discounts']['manual']:.2f}, promo {totals['discounts']['promo']:.2f};"
          f" mistakes {len(totals['mistakes'])}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("data_dir", help="folder to put the demo database in (not the real data folder)")
    parser.add_argument("--days", type=int, default=30, help="days of sales, ending today (default 30)")
    parser.add_argument("--per-day", type=int, default=60, help="sales per day (default 60)")
    parser.add_argument("--seed", type=int, default=1, help="same seed, same sales (default 1)")
    args = parser.parse_args(argv)
    if not 1 <= args.days <= 365 or not 1 <= args.per_day <= 500:
        parser.error("--days must be 1-365 and --per-day 1-500 (sale numbers run out at 999 a day)")
    if args.days * args.per_day > 5000:
        # Invoice numbers carry on across Z reports and all get today's date: 999 at most.
        parser.error("at most 5000 sales in all (--days x --per-day), or the invoice numbers run out")

    data_dir = os.path.abspath(args.data_dir)
    if _same_path(data_dir, _real_data_dir()):
        sys.exit(f"{data_dir} is the app's real data folder: pick another one.")
    os.environ[DATA_DIR_VAR] = data_dir
    # Imported only now: the database path is fixed when app.core.database is imported.
    from app.core.database import DB_PATH, get_session, init_db
    from tools.sales_factory import expected_totals, seed_sales

    if os.path.exists(DB_PATH):
        sys.exit(f"{DB_PATH} already exists: pick an empty folder.")
    init_db()
    today = date.today()
    days = [today - timedelta(days=n) for n in range(args.days - 1, -1, -1)]
    print(f"Seeding {args.days} days x {args.per_day} sales (seed {args.seed}) into {DB_PATH} ...")
    with get_session() as session:
        seeded = seed_sales(session, random.Random(args.seed), days, args.per_day)
    records, category_of = seeded.records, seeded.category_of
    till = [r for r in records if r.invoice_number is None]
    invoiced = [r for r in records if r.invoice_number is not None]

    print("\nZ reports (Reports > Z reports), one per closed day:")
    for number, day in enumerate(days[:-1], start=1):
        totals = expected_totals([r for r in till if r.day == day], category_of)
        print(f"  Z-{number:04d}  {day}  {totals['count']:>4} transactions  total {totals['final']:>9.2f}")
    _print_totals(f"X report (today, {today}: till sales only)",
                  expected_totals([r for r in till if r.day == today], category_of))
    _print_totals(f"Reports screen, sales, today ({today}: every sale, invoiced ones too)",
                  expected_totals([r for r in records if r.day == today], category_of))
    print(f"  Sales revenue {expected_totals([r for r in till if r.day == today], category_of)['final']:.2f},"
          f" invoice revenue {expected_totals([r for r in invoiced if r.day == today], category_of)['final']:.2f}")
    _print_totals(f"Reports screen, invoices only, {days[0]} to {today}", expected_totals(invoiced, category_of))

    start = (f'$env:{DATA_DIR_VAR} = "{data_dir}"; python main.py' if sys.platform == "win32"
             else f'{DATA_DIR_VAR}="{data_dir}" python main.py')
    print(f"\nStart the app on it:\n  {start}")


if __name__ == "__main__":
    main()
