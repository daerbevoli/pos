"""Tests for app.core.label_sheet_service (A4 barcode label PDF)."""
import pytest

from reportlab.lib.units import mm

from app.core.label_sheet_service import (
    LABEL_LAYOUTS, _BAR_HEIGHT, _barcode_drawing, _barcode_type, _detail_lines,
    build_label_sheet_pdf,
)


@pytest.mark.parametrize("barcode, expected", [
    ("2060000000019", "EAN13"),
    ("036000291452", "UPCA"),         # 12 digits is UPC-A, not EAN-13 data
    ("96385074", "EAN8"),
    ("2060000000018", "Code128"),     # wrong check digit: EAN-13 would print ...019
    ("206000000001", "Code128"),      # 12 digits, not a valid UPC-A
    ("9638507", "Code128"),           # EAN-8 data would print 8 digits
    ("ABC-123", "Code128"),
    ("12345", "Code128"),
])
def test_barcode_type(barcode, expected):
    assert _barcode_type(barcode) == expected


@pytest.mark.parametrize("args, expected", [
    (("ACME", "L1", "31/12/2026"), ["ACME", "Lot: L1   Exp: 31/12/2026"]),
    (("ACME", "", ""), ["ACME"]),
    (("", "L1", ""), ["Lot: L1"]),
    (("", "", "31/12/2026"), ["Exp: 31/12/2026"]),
    (("", "", ""), []),
])
def test_detail_lines_skip_empty_fields(args, expected):
    assert _detail_lines(*args) == expected


@pytest.mark.parametrize("labels_per_page", list(LABEL_LAYOUTS))
@pytest.mark.parametrize("barcode", ["5449000000996", "96385074", "ABC-123"])
def test_build_label_sheet_pdf_writes_pdf(tmp_path, labels_per_page, barcode):
    path = tmp_path / "labels.pdf"
    build_label_sheet_pdf(
        str(path), labels_per_page, barcode,
        name="A very long product name that must be truncated",
        manufacturer="ACME Food Industries International", lot_number="L2026-0042",
        expiry_date="31/12/2026",
    )
    assert path.read_bytes().startswith(b"%PDF")


def test_build_label_sheet_pdf_barcode_only(tmp_path):
    path = tmp_path / "labels.pdf"
    build_label_sheet_pdf(str(path), 24, "2060000000019")
    assert path.read_bytes().startswith(b"%PDF")


@pytest.mark.parametrize("barcode", ["2060000000019", "96385074", "ABC-123"])
def test_barcode_is_short_but_fills_the_width(barcode):
    """With room to spare, bars stay _BAR_HEIGHT tall instead of growing,
    and the barcode is sized by the label's width (wider bars = clearer)."""
    _, bw, bh = _barcode_drawing(barcode, max_w=40 * mm, max_h=100 * mm)
    assert bw == pytest.approx(40 * mm)
    assert _BAR_HEIGHT < bh < _BAR_HEIGHT + 6 * mm  # bars + human-readable digits


@pytest.mark.parametrize("barcode", ["2060000000019", "ABC-123"])
def test_barcode_shrinks_to_fit_a_cramped_label(barcode):
    _, _, bh = _barcode_drawing(barcode, max_w=50 * mm, max_h=8 * mm)
    assert bh <= 8 * mm + 0.01


def test_layouts_fill_the_page_exactly():
    for count, (cols, rows) in LABEL_LAYOUTS.items():
        assert cols * rows == count


def test_unsupported_layout_raises(tmp_path):
    with pytest.raises(ValueError):
        build_label_sheet_pdf(str(tmp_path / "x.pdf"), 17, "2060000000019")


def test_missing_barcode_raises(tmp_path):
    with pytest.raises(ValueError):
        build_label_sheet_pdf(str(tmp_path / "x.pdf"), 24, "")
