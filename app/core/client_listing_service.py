"""
Client Listing Service
Per-client purchase totals over a date range, built from the issued
invoices and credit notes (Invoice rows) — till sales are purged at each Z
report and aren't tied to a client anyway, so invoices are the only record of
what a client bought. Credit notes carry negative amounts and so net out of
their client's totals. Exported as CSV or as a PDF table.
"""
import csv
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy.orm import Session

from app.core.report_service import invoice_vat_breakdown
from app.models.models import Invoice

logger = logging.getLogger(__name__)

# Column order of the per-rate columns: amount excl. VAT sold at each rate.
LISTING_VAT_RATES = (0, 6, 12, 21)

LISTING_HEADERS = [
    "Company", "VAT number", "Total incl. VAT", "Total excl. VAT",
    *(f"VAT {rate}%" for rate in LISTING_VAT_RATES),
    "Invoices",
]


@dataclass
class ClientListingRow:
    name: str
    vat_number: str
    total_incl: float = 0.0
    total_excl: float = 0.0
    base_per_rate: dict[int, float] = field(default_factory=lambda: {r: 0.0 for r in LISTING_VAT_RATES})
    invoice_count: int = 0

    def as_cells(self) -> list:
        return [
            self.name, self.vat_number,
            f"{self.total_incl:.2f}", f"{self.total_excl:.2f}",
            *(f"{self.base_per_rate[rate]:.2f}" for rate in LISTING_VAT_RATES),
            self.invoice_count,
        ]


class ClientListingService:

    @staticmethod
    def build(session: Session, start: date, end: date) -> list[ClientListingRow]:
        """One row per client with an invoice/credit note issued between
        start and end (both inclusive), sorted by company name. Name and VAT
        number come from the client's most recent document in the range —
        the frozen snapshot, not the live Client, which may have changed since."""
        invoices = (
            session.query(Invoice)
            .filter(
                Invoice.issued_at >= datetime.combine(start, time.min),
                Invoice.issued_at < datetime.combine(end + timedelta(days=1), time.min),
            )
            .order_by(Invoice.issued_at)
            .all()
        )

        by_client: dict[int, list[Invoice]] = {}
        for invoice in invoices:
            by_client.setdefault(invoice.client_id, []).append(invoice)

        rows = []
        for client_invoices in by_client.values():
            latest = client_invoices[-1]
            final = sum(inv.final_amount or 0.0 for inv in client_invoices)
            tax = sum(inv.tax_amount or 0.0 for inv in client_invoices)
            breakdown = invoice_vat_breakdown(client_invoices)
            rows.append(ClientListingRow(
                name=latest.client_name,
                vat_number=latest.client_vat_number,
                total_incl=round(final, 2),
                total_excl=round(final - tax, 2),
                base_per_rate={rate: breakdown.get(str(rate), {}).get("base", 0.0) for rate in LISTING_VAT_RATES},
                invoice_count=len(client_invoices),
            ))
        rows.sort(key=lambda r: (r.name or "").lower())
        logger.info("Client listing %s → %s: %d client(s), %d document(s)",
                    start, end, len(rows), len(invoices))
        return rows

    @staticmethod
    def totals(rows: list[ClientListingRow]) -> ClientListingRow:
        total = ClientListingRow(name="Total", vat_number="")
        for row in rows:
            total.total_incl += row.total_incl
            total.total_excl += row.total_excl
            for rate in LISTING_VAT_RATES:
                total.base_per_rate[rate] += row.base_per_rate[rate]
            total.invoice_count += row.invoice_count
        total.total_incl = round(total.total_incl, 2)
        total.total_excl = round(total.total_excl, 2)
        total.base_per_rate = {rate: round(v, 2) for rate, v in total.base_per_rate.items()}
        return total

    @staticmethod
    def write_csv(rows: list[ClientListingRow], path: str):
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(LISTING_HEADERS)
            for row in rows:
                writer.writerow(row.as_cells())

    @staticmethod
    def write_pdf(rows: list[ClientListingRow], path: str, start: date, end: date):
        styles = getSampleStyleSheet()
        doc = SimpleDocTemplate(
            path, pagesize=landscape(A4),
            leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=12 * mm,
            title="Client listing",
        )
        cell_style = styles["BodyText"]
        cell_style.fontSize = 8
        cell_style.leading = 10

        data = [LISTING_HEADERS]
        for row in rows:
            cells = row.as_cells()
            # Paragraph lets a long company name wrap instead of overflowing its column.
            cells[0] = Paragraph(cells[0] or "", cell_style)
            data.append(cells)
        data.append(ClientListingService.totals(rows).as_cells())

        table = Table(
            data, repeatRows=1,
            colWidths=[70 * mm, 36 * mm, 26 * mm, 26 * mm, 20 * mm, 20 * mm, 20 * mm, 20 * mm, 17 * mm],
        )
        table.setStyle(TableStyle([
            ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
            ("FONT", (0, 1), (-1, -1), "Helvetica", 8),
            ("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 8),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E0E0E0")),
            ("LINEABOVE", (0, -1), (-1, -1), 1, colors.black),
            ("GRID", (0, 0), (-1, -2), 0.25, colors.grey),
            ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))

        doc.build([
            Paragraph("Client listing", styles["Title"]),
            Paragraph(f"Period: {start:%d-%m-%Y} – {end:%d-%m-%Y}", styles["Normal"]),
            Spacer(1, 6 * mm),
            table,
        ])
