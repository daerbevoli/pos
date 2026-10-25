"""
Tests for app.ui.dialogs.z_reports_dialog.ZReportsDialog and reprinting a
Z report. All DB access goes through patched_db; the printer is faked.
"""
from datetime import datetime

import pytest

from app.core.database import get_session
from app.core.receipt_service import PrinterError, ReceiptService
from app.models.models import ZReport
from app.ui.dialogs.z_reports_dialog import ZReportsDialog


def _add_z(number, final_amount=100.0):
    with get_session() as session:
        now = datetime(2026, 10, 24, 20, 0)
        session.add(ZReport(report_number=number, period_start=now, period_end=now,
                            transaction_count=3, final_amount=final_amount))
        session.commit()


@pytest.fixture
def dialog(qtbot, patched_db):
    def make():
        d = ZReportsDialog()
        qtbot.addWidget(d)
        d.shown = []
        d.overlay.show_message = lambda msg, kind="info": d.shown.append((msg, kind))
        return d
    return make


def test_lists_every_z_report_newest_first(dialog):
    _add_z("Z-0001", 10.0)
    _add_z("Z-0002", 25.5)
    d = dialog()
    assert d.table.rowCount() == 2
    assert d.table.item(0, 0).text() == "Z-0002"
    assert d.table.item(0, 4).text() == "25.50"
    assert d.table.currentRow() == 0  # newest preselected


def test_print_reprints_the_selected_one_as_a_copy(dialog, monkeypatch):
    _add_z("Z-0001")
    _add_z("Z-0002")
    printed = []
    monkeypatch.setattr(ReceiptService, "print_z_report",
                        lambda session, z, reprint=False: printed.append((z.report_number, reprint)))
    d = dialog()
    d.table.selectRow(1)

    d._print_selected()

    assert printed == [("Z-0001", True)]
    assert d.shown == [("Z-0001 printed.", "info")]


def test_print_without_z_reports_asks_for_a_selection(dialog, monkeypatch):
    printed = []
    monkeypatch.setattr(ReceiptService, "print_z_report", lambda *a, **k: printed.append(a))
    d = dialog()
    d._print_selected()
    assert printed == [] and d.shown == [("Select a Z report first.", "info")]


def test_printer_failure_is_shown(dialog, monkeypatch):
    _add_z("Z-0001")

    def fail(*a, **k):
        raise PrinterError("no paper")
    monkeypatch.setattr(ReceiptService, "print_z_report", fail)
    d = dialog()
    d._print_selected()
    assert d.shown[0][1] == "error" and "no paper" in d.shown[0][0]


def test_reprint_is_titled_as_a_copy(patched_db, monkeypatch):
    class FakePrinter:
        def __init__(self):
            self.out = []

        def text(self, t):
            self.out.append(t)

        def set(self, *a, **k):
            pass

        def cut(self, *a, **k):
            pass

        def close(self):
            pass

    printer = FakePrinter()
    monkeypatch.setattr("app.core.receipt_service._open", lambda *a: printer)
    _add_z("Z-0001")
    with get_session() as session:
        z = session.query(ZReport).one()
        ReceiptService.print_z_report(session, z, reprint=True)
    text = "".join(printer.out)
    assert "Z-REPORT (COPY)" in text and "Copy printed on" in text

    printer.out.clear()
    with get_session() as session:
        ReceiptService.print_z_report(session, session.query(ZReport).one())
    assert "(COPY)" not in "".join(printer.out)
