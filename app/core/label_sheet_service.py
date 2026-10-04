"""
Label Sheet Service
Builds an A4 PDF of barcode labels (name, manufacturer, lot number, expiry
date + barcode) for printing on standard adhesive label sheets with an
ordinary printer — unlike label_service.py, which drives the dedicated ZPL
shelf-label printer.
"""
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import createBarcodeDrawing
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

# Labels per page -> (columns, rows). The grids divide A4 edge to edge, which
# matches common margin-less sheets (e.g. 24 = 70 x 37 mm, 40 = 52.5 x 29.7 mm).
LABEL_LAYOUTS = {
    16: (2, 8),
    21: (3, 7),
    24: (3, 8),
    40: (4, 10),
}

_PADDING = 2 * mm
_NAME_FONT = "Helvetica-Bold"
_DETAIL_FONT = "Helvetica"
_LINE_GAP = 1
_TEXT_BARCODE_GAP = 1.5 * mm
_BAR_HEIGHT = 5 * mm
_MIN_SCALE, _MAX_SCALE = 0.8, 1.5


def _barcode_type(barcode: str) -> str:
    """EAN-13/EAN-8 where the code fits, otherwise Code128 (accepts any text)."""
    if barcode.isdigit():
        if len(barcode) in (12, 13):
            return "EAN13"
        if len(barcode) in (7, 8):
            return "EAN8"
    return "Code128"


def _fit_text(text: str, font: str, size: float, max_width: float) -> str:
    if stringWidth(text, font, size) <= max_width:
        return text
    while text and stringWidth(text + "…", font, size) > max_width:
        text = text[:-1]
    return text + "…"


def _detail_lines(manufacturer: str, lot_number: str, expiry_date: str) -> list[str]:
    """Small-print lines under the name; lot and expiry share one line to
    leave the barcode room on the smaller layouts. Empty fields are left out."""
    lines = []
    if manufacturer:
        lines.append(manufacturer)
    lot_exp = "   ".join(part for part in (
        f"Lot: {lot_number}" if lot_number else "",
        f"Exp: {expiry_date}" if expiry_date else "",
    ) if part)
    if lot_exp:
        lines.append(lot_exp)
    return lines


def _barcode_drawing(barcode: str, max_w: float, max_h: float):
    """The barcode drawing, scaled to fill `max_w`, with bars _BAR_HEIGHT tall
    (shorter only if the label has no room). Returns (drawing, width, height)."""
    kind = _barcode_type(barcode)
    # Probe with tall bars: a very short barcode gets padded up to its digits' height.
    probe = createBarcodeDrawing(kind, value=barcode, humanReadable=True, barHeight=100)
    scale = max(_MIN_SCALE, min(max_w / probe.width, _MAX_SCALE))
    # Code128 prints its digits below the bars (adding height); EAN prints them
    # inside the bar area, so the bars must be that much taller to stay _BAR_HEIGHT
    # above the digits.
    below = probe.height - 100
    inside = 0 if below > 0 else probe.contents[0].fontSize * 1.2

    bar_h = min(_BAR_HEIGHT / scale + inside, max_h / scale - below)
    drawing = createBarcodeDrawing(kind, value=barcode, humanReadable=True, barHeight=bar_h)
    drawing.scale(scale, scale)
    return drawing, drawing.width * scale, drawing.height * scale


def _draw_label(c: canvas.Canvas, x: float, y: float, w: float, h: float,
                name: str, details: list[str], barcode: str):
    inner_w = w - 2 * _PADDING
    cx = x + w / 2

    name_size = min(10, h * 0.16)
    detail_size = min(7, h * 0.11)
    lines = [(name, _NAME_FONT, name_size)] if name else []
    lines += [(line, _DETAIL_FONT, detail_size) for line in details]
    text_h = sum(size + _LINE_GAP for _, _, size in lines)
    gap = _TEXT_BARCODE_GAP if lines else 0

    drawing, bw, bh = _barcode_drawing(barcode, inner_w, h - 2 * _PADDING - text_h - gap)

    # Centre the text + barcode block vertically on the label.
    top = y + (h + text_h + gap + bh) / 2
    for text, font, size in lines:
        top -= size
        c.setFont(font, size)
        c.drawCentredString(cx, top, _fit_text(text, font, size, inner_w))
        top -= _LINE_GAP
    renderPDF.draw(drawing, c, x + (w - bw) / 2, top - gap - bh)


def build_label_sheet_pdf(path: str, labels_per_page: int, barcode: str, name: str = "",
                          manufacturer: str = "", lot_number: str = "", expiry_date: str = ""):
    """Write one A4 page filled with `labels_per_page` identical labels."""
    if labels_per_page not in LABEL_LAYOUTS:
        raise ValueError(f"Unsupported layout: {labels_per_page} labels per page")
    if not barcode:
        raise ValueError("A barcode is required")

    cols, rows = LABEL_LAYOUTS[labels_per_page]
    page_w, page_h = A4
    w, h = page_w / cols, page_h / rows
    details = _detail_lines(manufacturer, lot_number, expiry_date)

    c = canvas.Canvas(path, pagesize=A4)
    c.setTitle(f"Labels - {name or barcode}")
    for row in range(rows):
        for col in range(cols):
            # PDF origin is bottom-left; fill from the top-left like a sheet.
            _draw_label(c, col * w, page_h - (row + 1) * h, w, h, name, details, barcode)
    c.showPage()
    c.save()
