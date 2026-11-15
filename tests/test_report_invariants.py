"""
The reports checked against sales whose effect is known: random sales from
tools/sales_factory.py (tickets as a cashier could ring them up, paid in
cash, card or both, some invoiced, some reopened), saved through the real
services into an in-memory database, against expected_totals() worked out
from what was rung up and handed over.

A failure names its seed: `python -m tools.seed_sales <empty folder> --seed N
--days 3 --per-day 20` builds the same kind of sales in a demo database to
look at in the app (dates differ: it ends today).
"""
import json
import random
from datetime import date, timedelta

import pytest
from pytest import approx

from app.core.sale.report_service import (
    XZReportService,
    invoice_payment_breakdown,
    invoice_vat_breakdown,
)
from app.core.sale.sales_service import SalesService
from app.models.models import Sale, ZReport
from tools.sales_factory import expected_totals, seed_sales

SEEDS = range(8)
CENT = 0.005  # same amount, allowing for float noise
DAYS = [date(2026, 6, 8) + timedelta(days=i) for i in range(3)]
# Brussels switches to summer time on 29 March 2026: these days span it.
DST_DAYS = [date(2026, 3, 28) + timedelta(days=i) for i in range(3)]


def _assert_report(report: dict, expected: dict, where: str):
    """`report` as compute_totals() returns it (or a Z report's stored copy)
    against expected_totals(), and adding up with itself."""
    assert report["transaction_count"] == expected["count"], where
    assert report["final_amount"] == approx(expected["final"], abs=CENT), where
    assert report["tax_amount"] == approx(expected["tax"], abs=CENT), where
    assert report["total_amount"] == approx(expected["final"] - expected["tax"], abs=2 * CENT), where

    for rate, amounts in report["vat_breakdown"].items():
        want = expected["vat"][int(rate)]
        assert amounts["total"] == approx(want["total"], abs=CENT), f"{where}, VAT {rate}%"
        assert amounts["tax"] == approx(want["tax"], abs=CENT), f"{where}, VAT {rate}%"
        assert amounts["base"] == approx(want["total"] - want["tax"], abs=2 * CENT), f"{where}, VAT {rate}%"

    payments = {leg["method"]: leg["amount"] for leg in report["payment_breakdown"]}
    for method in payments.keys() | expected["payments"].keys():
        assert payments.get(method, 0.0) == approx(expected["payments"].get(method, 0.0), abs=CENT), \
            f"{where}, paid by {method}"

    assert report["discounts"] == approx(expected["discounts"], abs=CENT), where
    assert sorted(m["name"] for m in report["mistakes"]) == expected["mistakes"], where
    categories = {name: amount for name, (_qty, amount) in report["category_breakdown"].items()}
    assert categories == approx(expected["categories"], abs=CENT), where

    # Each breakdown adds up to the total (each part is rounded on its own).
    slack = 0.01 * len(report["vat_breakdown"])
    assert sum(a["total"] for a in report["vat_breakdown"].values()) == approx(report["final_amount"], abs=slack), where
    assert sum(payments.values()) == approx(report["final_amount"], abs=slack), where
    assert sum(categories.values()) == approx(report["final_amount"], abs=0.01 * len(categories) + CENT), where


def _z_as_totals(z: ZReport) -> dict:
    return {
        "transaction_count": z.transaction_count,
        "final_amount": z.final_amount,
        "tax_amount": z.tax_amount,
        "total_amount": z.total_amount,
        "vat_breakdown": json.loads(z.vat_breakdown),
        "payment_breakdown": json.loads(z.payment_breakdown),
        "discounts": json.loads(z.discounts),
        "mistakes": json.loads(z.mistakes),
        "category_breakdown": json.loads(z.category_breakdown),
    }


@pytest.mark.parametrize("seed", SEEDS)
def test_z_and_x_reports_match_the_sales_rung_up(db_session, seed):
    seeded = seed_sales(db_session, random.Random(seed), DAYS, per_day=20)
    records, category_of = seeded.records, seeded.category_of
    till = [r for r in records if r.invoice_number is None]
    expected = lambda rs: expected_totals(rs, category_of)  # noqa: E731

    # Every day but the last closed by its own Z report, numbered in order.
    z_reports = db_session.query(ZReport).order_by(ZReport.id).all()
    assert [z.report_number for z in z_reports] == ["Z-0001", "Z-0002"], f"seed {seed}"
    for z, day in zip(z_reports, DAYS):
        _assert_report(_z_as_totals(z), expected([r for r in till if r.day == day]), f"seed {seed}, {z.report_number}")

    # The open period holds exactly the last day's sales; the X report covers its till part.
    last = DAYS[-1]
    assert {s.id for s in db_session.query(Sale)} == {r.sale_id for r in records if r.day == last}, f"seed {seed}"
    x_report = XZReportService.generate_x_report(db_session)
    assert x_report["report_number"] == "X-0003", f"seed {seed}"
    _assert_report(x_report, expected([r for r in till if r.day == last]), f"seed {seed}, X report")

    # Nothing lost or counted twice across the Z reports and the open period.
    total = sum(z.final_amount for z in z_reports) + x_report["final_amount"]
    assert total == approx(expected(till)["final"], abs=0.01 * len(DAYS)), f"seed {seed}"

    # The Reports screen's sales view of the open day: every sale, invoiced ones too.
    on_screen = SalesService.get_sales_range(db_session, last, last)
    _assert_report(XZReportService.compute_totals(db_session, on_screen),
                   expected([r for r in records if r.day == last]), f"seed {seed}, Reports screen")

    # Invoices outlive the Z reports: all of them, from their own snapshots.
    invoiced = [r for r in records if r.invoice_number is not None]
    invoices = SalesService.get_invoices_range(db_session, DAYS[0], last)
    assert sorted(i.invoice_number for i in invoices) == sorted(r.invoice_number for r in invoiced), f"seed {seed}"
    want = expected(invoiced)
    vat = invoice_vat_breakdown(invoices)
    for rate, amounts in vat.items():
        assert amounts["total"] == approx(want["vat"][int(rate)]["total"], abs=CENT), f"seed {seed}, invoice VAT {rate}%"
        assert amounts["tax"] == approx(want["vat"][int(rate)]["tax"], abs=CENT), f"seed {seed}, invoice VAT {rate}%"
    payments = {leg["method"]: leg["amount"] for leg in invoice_payment_breakdown(invoices)}
    for method in payments.keys() | want["payments"].keys():
        assert payments.get(method, 0.0) == approx(want["payments"].get(method, 0.0), abs=CENT), \
            f"seed {seed}, invoices paid by {method}"
    assert sum(i.final_amount for i in invoices) == approx(want["final"], abs=CENT), f"seed {seed}"


@pytest.mark.parametrize("seed", SEEDS)
def test_day_ranges_follow_local_days_across_midnight_and_dst(brussels_tz, db_session, seed):
    """No Z report: every sale stays, and each local day's range must hold
    exactly that day's sales, including those a minute after midnight or
    before the next, and across the switch to summer time."""
    seeded = seed_sales(db_session, random.Random(seed), DST_DAYS, per_day=40, close_z=False)
    records = seeded.records
    for day in DST_DAYS:
        found = {s.id for s in SalesService.get_sales_range(db_session, day, day)}
        assert found == {r.sale_id for r in records if r.day == day}, f"seed {seed}, {day}"
    found = SalesService.get_sales_range(db_session, DST_DAYS[0], DST_DAYS[-1])
    assert len(found) == len(records), f"seed {seed}"

    till = [r for r in records if r.invoice_number is None]
    _assert_report(XZReportService.generate_x_report(db_session),
                   expected_totals(till, seeded.category_of), f"seed {seed}, X report")
