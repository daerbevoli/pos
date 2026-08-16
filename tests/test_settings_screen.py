"""
Tests for app.ui.settings_screen.SettingsScreen.

All DB access goes through the patched_db fixture, so nothing here touches
the real per-user database. QMessageBox / QFileDialog static calls are
monkeypatched since they'd otherwise pop a real modal dialog and hang.
"""
import pytest

from app.ui.settings_screen import SettingsScreen
from app.core.settings_service import SettingsService


@pytest.fixture
def screen(qtbot, patched_db):
    s = SettingsScreen()
    qtbot.addWidget(s)
    return s


def test_loads_default_settings_on_construction(screen):
    assert screen.store_name.text() == "My Supermarket"
    assert screen.currency.text() == "€"
    assert screen.receipt_footer.text() == "Thank you for shopping with us!"
    assert screen.receipt_vendor.text() == ""


def test_save_persists_edited_fields(screen, monkeypatch, patched_db):
    monkeypatch.setattr("app.ui.settings_screen.QMessageBox.information", lambda *a, **kw: None)

    screen.store_name.setText("New Shop Name")
    screen.currency.setText("$")
    screen.receipt_vendor.setText("0x04b8")

    screen._save()

    from app.core.database import get_session
    with get_session() as session:
        assert SettingsService.get(session, "store_name") == "New Shop Name"
        assert SettingsService.get(session, "currency_symbol") == "$"
        assert SettingsService.get(session, "receipt_printer_vendor_id") == "0x04b8"


def test_save_emits_settings_saved_signal(screen, monkeypatch, qtbot):
    monkeypatch.setattr("app.ui.settings_screen.QMessageBox.information", lambda *a, **kw: None)

    with qtbot.waitSignal(screen.settings_saved, timeout=1000):
        screen._save()


def test_save_shows_confirmation_dialog(screen, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.ui.settings_screen.QMessageBox.information",
        lambda *a, **kw: calls.append(a),
    )
    screen._save()
    assert len(calls) == 1


def test_test_print_shows_success_dialog(screen, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.ui.settings_screen.PrinterService.test_print",
        lambda vendor_id, product_id: None,
    )
    monkeypatch.setattr(
        "app.ui.settings_screen.QMessageBox.information",
        lambda *a, **kw: calls.append(a),
    )
    screen._test_print()
    assert len(calls) == 1


def test_test_print_shows_warning_on_failure(screen, monkeypatch):
    from app.core.receipt_service import PrinterError

    calls = []

    def _raise(vendor_id, product_id):
        raise PrinterError("Vendor ID is not configured. Set it in Settings.")

    monkeypatch.setattr("app.ui.settings_screen.PrinterService.test_print", _raise)
    monkeypatch.setattr(
        "app.ui.settings_screen.QMessageBox.warning",
        lambda *a, **kw: calls.append(a),
    )
    screen._test_print()
    assert len(calls) == 1


def test_load_logo_updates_path_and_preview(screen, monkeypatch):
    monkeypatch.setattr(
        "app.ui.settings_screen.QFileDialog.getOpenFileName",
        lambda *a, **kw: ("/fake/logo.png", "Images"),
    )
    screen._load_logo()
    assert screen._logo_path == "/fake/logo.png"


def test_load_logo_cancelled_leaves_path_unchanged(screen, monkeypatch):
    screen._logo_path = "/existing/logo.png"
    monkeypatch.setattr(
        "app.ui.settings_screen.QFileDialog.getOpenFileName",
        lambda *a, **kw: ("", ""),
    )
    screen._load_logo()
    assert screen._logo_path == "/existing/logo.png"


def test_reload_after_save_reflects_persisted_values(screen, monkeypatch):
    monkeypatch.setattr("app.ui.settings_screen.QMessageBox.information", lambda *a, **kw: None)
    screen.store_address.setText("123 Main St")
    screen._save()

    screen._load()
    assert screen.store_address.text() == "123 Main St"
