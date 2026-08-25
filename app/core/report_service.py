"""
X / Z Report Service
X report: read-only snapshot of all sales currently in the table (i.e.
everything since the last Z report). Z report: persists that snapshot as a
sequentially-numbered ZReport row, then purges the Sale/SaleItem rows it
summarized — the ZReport row becomes the sole permanent record of that
period (invoices are unaffected).
"""
import json
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.models import Sale, ZReport

VAT_RATES = (0, 6, 21)


def _payment_breakdown(sale) -> list[dict]:
    """Per-method split of a sale's payment; falls back to a single-method
    entry for sales recorded before split payments existed."""
    if sale.payment_breakdown:
        try:
            return json.loads(sale.payment_breakdown)
        except (ValueError, TypeError):
            pass
    return [{"method": sale.payment_method, "amount": sale.final_amount}]


def _amount_for_method(sale, method: str) -> float:
    return sum(leg.get("amount", 0.0) for leg in _payment_breakdown(sale) if leg.get("method") == method)


class XZReportService:

    @staticmethod
    def compute_totals(session: Session, sales: list[Sale] = None) -> dict:
        """Aggregate totals/VAT/payment breakdown over the given sales (all
        current sales in the table if not given — safe since Sale rows only
        ever hold the current open period, per the Z-report purge)."""
        if sales is None:
            sales = session.query(Sale).all()

        final_amount = round(sum(s.final_amount for s in sales), 2)
        tax_amount = round(sum(s.tax_amount for s in sales), 2)
        total_amount = round(final_amount - tax_amount, 2)
        transaction_count = len(sales)

        vat_totals = {rate: [0.0, 0.0] for rate in VAT_RATES}  # rate -> [tax_sum, total_sum]
        category_breakdown = {}
        for sale in sales:
            for item in sale.items:
                rate = item.tax_rate if item.tax_rate in vat_totals else 0
                vat_totals[rate][0] += item.tax_amount
                vat_totals[rate][1] += item.line_total

                category_name = item.product.category.name if item.product.category else "Uncategorized"
                qty_sum, amount_sum = category_breakdown.get(category_name, [0.0, 0.0])
                category_breakdown[category_name] = [qty_sum + item.quantity, amount_sum + item.line_total]
        vat_breakdown = {
            str(rate): {
                "base": round(total_sum - tax_sum, 2),
                "tax": round(tax_sum, 2),
                "total": round(total_sum, 2),
            }
            for rate, (tax_sum, total_sum) in vat_totals.items()
        }

        payment_totals: dict[str, float] = {}
        for sale in sales:
            for leg in _payment_breakdown(sale):
                method = leg.get("method", "unknown")
                payment_totals[method] = payment_totals.get(method, 0.0) + leg.get("amount", 0.0)
        payment_breakdown = [
            {"method": method, "amount": round(amount, 2)}
            for method, amount in payment_totals.items()
        ]

        return {
            "transaction_count": transaction_count,
            "total_amount": total_amount,
            "tax_amount": tax_amount,
            "final_amount": final_amount,
            "vat_breakdown": vat_breakdown,
            "category_breakdown": category_breakdown,
            "payment_breakdown": payment_breakdown,
        }

    @staticmethod
    def generate_x_report(session: Session) -> dict:
        """Read-only preview — no persistence, no deletion."""
        sales = session.query(Sale).order_by(Sale.created_at.asc()).all()
        totals = XZReportService.compute_totals(session, sales)
        totals["period_start"] = sales[0].created_at if sales else datetime.now()
        totals["period_end"] = datetime.now()
        return totals

    @staticmethod
    def close_z_report(session: Session) -> ZReport:
        """Snapshot current sales into a new ZReport row, then purge them.
        Runs as one transaction: the snapshot and the purge succeed or fail
        together. Printing happens separately, after this commits, so a
        printer failure can never lose sales data."""
        sales = session.query(Sale).order_by(Sale.created_at.asc()).all()
        totals = XZReportService.compute_totals(session, sales)

        count = session.query(func.count(ZReport.id)).scalar() or 0
        report_number = f"Z-{count + 1:04d}"

        last_report = session.query(ZReport).order_by(ZReport.id.desc()).first()
        if last_report is not None:
            period_start = last_report.created_at
        elif sales:
            period_start = sales[0].created_at
        else:
            period_start = datetime.now()
        period_end = datetime.now()

        z_report = ZReport(
            report_number=report_number,
            period_start=period_start,
            period_end=period_end,
            transaction_count=totals["transaction_count"],
            total_amount=totals["total_amount"],
            tax_amount=totals["tax_amount"],
            final_amount=totals["final_amount"],
            vat_breakdown=json.dumps(totals["vat_breakdown"]),
            category_breakdown=json.dumps(totals["category_breakdown"]),
            payment_breakdown=json.dumps(totals["payment_breakdown"]),
        )
        session.add(z_report)

        for sale in sales:
            session.delete(sale)

        session.commit()
        session.refresh(z_report)
        return z_report
