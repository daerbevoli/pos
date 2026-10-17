"""
Inventory Report Service
Freezes the active product list at the moment it's taken and writes it out as
a PDF or CSV: one line per product (barcode, name, VAT rate, price excl. VAT,
price incl. VAT) and the totals at the bottom.

Stock isn't counted in on every delivery yet, so each product is valued as
a quantity of 1, the total is the sum of the prices. Prices are the shelf
prices (VAT included); open-price products have no fixed price and count 0.
"""

import csv
import logging
from dataclasses import dataclass
from datetime import datetime
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy.orm import Session

from app.core.product_service import ProductService
from app.core.sales_service import calc_tax

logger = logging.getLogger(__name__)

HEADERS = ("Barcode", "Product", "VAT %", "Excl. VAT", "Price")


@dataclass(frozen=True)
class InventoryLine:
    barcode: str
    name: str
    tax_rate: int  # 0, 6, 12, 21
    price: float  # VAT included

    @property
    def price_excl_vat(self) -> float:
        return round(self.price - calc_tax(self.price, self.tax_rate), 2)


@dataclass(frozen=True)
class InventorySnapshot:
    taken_at: datetime
    lines: list[InventoryLine]

    @property
    def total(self) -> float:
        return round(sum(line.price for line in self.lines), 2)

    @property
    def total_excl_vat(self) -> float:
        # Sum of the rounded line amounts, so the column adds up on paper.
        return round(sum(line.price_excl_vat for line in self.lines), 2)


class InventoryReportService:

    @staticmethod
    def take_snapshot(session: Session) -> InventorySnapshot:
        # By barcode, products without one last.
        products = sorted(ProductService.get_all(session, active_only=True),
                          key=lambda p: (not p.barcode, p.barcode or "", p.id))
        lines = []
        for p in products:
            if p.is_open_price:
                continue
            lines.append(InventoryLine(p.barcode, p.name, p.tax, round(p.price, 2)))
        snapshot = InventorySnapshot(datetime.now(), lines)
        logger.info("Inventory taken: %d products, total %.2f (excl. VAT %.2f)",
                    len(lines), snapshot.total, snapshot.total_excl_vat)
        return snapshot

    @staticmethod
    def write_csv(path: str, snapshot: InventorySnapshot) -> None:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(HEADERS)
            for line in snapshot.lines:
                writer.writerow([line.barcode, line.name, line.tax_rate,
                                 f"{line.price_excl_vat:.2f}", f"{line.price:.2f}"])
            writer.writerow(["", "Total", "", f"{snapshot.total_excl_vat:.2f}", f"{snapshot.total:.2f}"])

    @staticmethod
    def write_pdf(path: str, snapshot: InventorySnapshot) -> None:
        styles = getSampleStyleSheet()
        doc = SimpleDocTemplate(
            path, pagesize=A4,
            leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
            title="Inventory",
        )
        rows = [list(HEADERS)]
        rows += [[line.barcode, Paragraph(escape(line.name), styles["BodyText"]), f"{line.tax_rate}%",
                  f"€{line.price_excl_vat:.2f}", f"€{line.price:.2f}"]
                 for line in snapshot.lines]
        rows.append(["", "Total", "", f"{snapshot.total_excl_vat:.2f}", f"{snapshot.total:.2f}"])

        id_width, vat_width, price_width = 35 * mm, 16 * mm, 28 * mm  # EAN-13 fits the ID column
        name_width = doc.width - id_width - vat_width - 2 * price_width
        table = Table(rows, colWidths=[id_width, name_width, vat_width, price_width, price_width],
                      repeatRows=1)
        table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("LINEBELOW", (0, 0), (-1, 0), 0.75, colors.black),
            ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("LINEABOVE", (0, -1), (-1, -1), 0.75, colors.black),
        ]))

        story = [
            Paragraph("Inventory", styles["Title"]),
            Paragraph(f"Taken on {snapshot.taken_at:%d/%m/%Y} — "
                      f"{len(snapshot.lines)} products", styles["Normal"]),
            Spacer(1, 6 * mm),
            table,
        ]
        doc.build(story)
