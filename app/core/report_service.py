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

from app.core.sales_service import Cart, calc_tax, SalesService, OpenTicketData, load_open_tickets
from app.models.models import Invoice, Product, Sale, ZReport

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


def _sum_payment_breakdowns(sources) -> list[dict]:
    """Per-method totals over sales (or invoices — same payment fields)."""
    payment_totals: dict[str, float] = {}
    for source in sources:
        for leg in _payment_breakdown(source):
            method = leg.get("method", "unknown")
            payment_totals[method] = payment_totals.get(method, 0.0) + leg.get("amount", 0.0)
    return [
        {"method": method, "amount": round(amount, 2)}
        for method, amount in payment_totals.items()
    ]


def _amount_for_method(sale, method: str) -> float:
    return sum(leg.get("amount", 0.0) for leg in _payment_breakdown(sale) if leg.get("method") == method)


def _vat_breakdown(lines) -> dict:
    """{"0"/"6"/"21": {"base", "tax", "total"}} from (tax_rate, tax_amount,
    line_total) tuples; an unknown rate is counted under 0%."""
    vat_totals = {rate: [0.0, 0.0] for rate in VAT_RATES}  # rate -> [tax_sum, total_sum]
    for tax_rate, tax_amount, line_total in lines:
        rate = tax_rate if tax_rate in vat_totals else 0
        vat_totals[rate][0] += tax_amount
        vat_totals[rate][1] += line_total
    return {
        str(rate): {
            "base": round(total_sum - tax_sum, 2),
            "tax": round(tax_sum, 2),
            "total": round(total_sum, 2),
        }
        for rate, (tax_sum, total_sum) in vat_totals.items()
    }


def invoice_vat_breakdown(invoices) -> dict:
    """VAT breakdown rebuilt from each invoice's frozen line_items_snapshot,
    so it still works after a Z report has purged the invoices' sales.
    Uses the same discounted line amounts as checkout (Cart.net_line_totals),
    so it matches the sale-based breakdown."""
    lines = []
    for invoice in invoices:
        try:
            cart = Cart.from_snapshot(invoice.line_items_snapshot)
        except (ValueError, TypeError, KeyError):
            continue
        for entry, net_total in cart.net_line_totals():
            if entry.quantity is None:
                continue
            lines.append((entry.tax_rate, calc_tax(net_total, entry.tax_rate), net_total))
    return _vat_breakdown(lines)


def invoice_payment_breakdown(invoices) -> list[dict]:
    """Per-method payment totals from each invoice's own frozen payment
    snapshot, so it still works after a Z report has purged the invoices'
    sales. An invoice issued before that snapshot existed falls back to its
    sale; if that's been purged too, how it was paid is lost and it's left out."""
    sources = []
    for invoice in invoices:
        if invoice.payment_method is not None:
            sources.append(invoice)
        elif invoice.sale is not None:
            sources.append(invoice.sale)
    return _sum_payment_breakdowns(sources)


def invoice_category_breakdown(session: Session, invoices) -> dict:
    """{category: [qty, amount]} rebuilt from each invoice's frozen
    line_items_snapshot, like compute_totals() does from SaleItems — so it
    still works after a Z report has purged the invoices' sales. Amounts are
    the discounted line totals (Cart.net_line_totals). The category is the
    product's current one: categories aren't frozen on the invoice, and
    products are only ever deactivated, never deleted."""
    category_names: dict[int, str] = {}
    breakdown: dict[str, list[float]] = {}
    for invoice in invoices:
        try:
            cart = Cart.from_snapshot(invoice.line_items_snapshot)
        except (ValueError, TypeError, KeyError):
            continue
        for entry, net_total in cart.net_line_totals():
            if entry.quantity is None:
                continue
            if entry.product_id not in category_names:
                product = session.get(Product, entry.product_id)
                category_names[entry.product_id] = (
                    product.category.name if product is not None and product.category else "Uncategorized"
                )
            name = category_names[entry.product_id]
            qty_sum, amount_sum = breakdown.get(name, [0.0, 0.0])
            breakdown[name] = [qty_sum + entry.quantity, round(amount_sum + net_total, 2)]
    return breakdown


def _discounts_and_mistakes(sales) -> tuple[dict, list[dict]]:
    """Read off each sale's cart_snapshot (the receipt as printed):
    discounts split into manual vs promo, and "mistakes" — lines voided on
    a reopened sale / unsent invoice (reversal lines). Refund-mode and
    credit-note lines are ordinary negative-quantity items, not reversals,
    so they never count as mistakes. A mistake's qty/amount are those of
    the line it voided."""
    discounts = {"manual": 0.0, "promo": 0.0}
    mistakes = []
    for sale in sales:
        try:
            entries = json.loads(sale.cart_snapshot) if sale.cart_snapshot else []
        except (ValueError, TypeError):
            continue
        for raw in entries:
            kind = raw.get("type")
            if kind == "discount":
                discounts["promo" if raw.get("is_promo") else "manual"] += raw.get("amount", 0.0)
            elif kind == "item" and raw.get("is_reversal") and raw.get("quantity") is not None:
                qty = -raw["quantity"]
                mistakes.append({
                    "name": raw.get("product_name", ""),
                    "quantity": qty,
                    "unit": raw.get("unit", "pcs"),
                    "amount": round(raw.get("unit_price", 0.0) * qty, 2),
                })
    return {k: round(v, 2) for k, v in discounts.items()}, mistakes


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

        category_breakdown = {}
        for sale in sales:
            for item in sale.items:
                category_name = item.product.category.name if item.product.category else "Uncategorized"
                qty_sum, amount_sum = category_breakdown.get(category_name, [0.0, 0.0])
                category_breakdown[category_name] = [qty_sum + item.quantity, amount_sum + item.line_total]
        vat_breakdown = _vat_breakdown(
            (item.tax_rate, item.tax_amount, item.line_total) for sale in sales for item in sale.items
        )

        payment_breakdown = _sum_payment_breakdowns(sales)

        discounts, mistakes = _discounts_and_mistakes(sales)

        return {
            "discounts": discounts,
            "mistakes": mistakes,
            "transaction_count": transaction_count,
            "total_amount": total_amount,
            "tax_amount": tax_amount,
            "final_amount": final_amount,
            "vat_breakdown": vat_breakdown,
            "category_breakdown": category_breakdown,
            "payment_breakdown": payment_breakdown,
        }

    @staticmethod
    def current_period_number(session: Session) -> int:
        """Sequence number of the open period: 1 before the first Z report,
        +1 after each close. Every X report of a period shares it, and the
        Z report closing that period takes it too."""
        return (session.query(func.count(ZReport.id)).scalar() or 0) + 1

    @staticmethod
    def generate_x_report(session: Session) -> dict:
        """Read-only preview — no persistence, no deletion."""
        sales = session.query(Sale).order_by(Sale.created_at.asc()).all()
        totals = XZReportService.compute_totals(session, sales)
        totals["report_number"] = f"X-{XZReportService.current_period_number(session):04d}"
        totals["period_start"] = sales[0].created_at if sales else datetime.now()
        totals["period_end"] = datetime.now()
        return totals

    @staticmethod
    def unsent_invoice_numbers(session: Session) -> list[str]:
        """Invoices/credit notes of the current period not yet sent to the
        ERP. Only those whose sale still exists count — the POS finds an
        invoice through its sale, so one orphaned by an earlier Z report
        can't be sent anymore and mustn't block every future close."""
        rows = (
            session.query(Invoice.invoice_number)
            .join(Sale, Invoice.sale_id == Sale.id)
            .filter(Invoice.sent_at.is_(None))
            .order_by(Invoice.invoice_number)
            .all()
        )
        return [number for (number,) in rows]

    @staticmethod
    def open_tickets(session: Session) -> bool:
        if load_open_tickets(session):
            return True
        return False


    @staticmethod
    def close_z_report(session: Session) -> ZReport:
        """Snapshot current sales into a new ZReport row, then purge them.
        Runs as one transaction: the snapshot and the purge succeed or fail
        together. Printing happens separately, after this commits, so a
        printer failure can never lose sales data.

        Refuses (ValueError, nothing changed) while any invoice of the period
        is still unsent: purging its sale unlinks the invoice from it, and
        the POS can then no longer reach it to send it."""
        unsent = XZReportService.unsent_invoice_numbers(session)
        open_tickets = XZReportService.open_tickets(session)
        if unsent or open_tickets:
            raise ValueError(f"Unsent invoices: {', '.join(unsent)}")

        sales = session.query(Sale).order_by(Sale.created_at.asc()).all()
        totals = XZReportService.compute_totals(session, sales)

        report_number = f"Z-{XZReportService.current_period_number(session):04d}"

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
            discounts=json.dumps(totals["discounts"]),
            mistakes=json.dumps(totals["mistakes"]),
        )
        session.add(z_report)

        for sale in sales:
            session.delete(sale)
        SalesService.reset_sale_sequences(session)

        session.commit()
        session.refresh(z_report)
        return z_report
