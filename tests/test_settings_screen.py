"""
Tests for app.ui.settings_screen.SettingsScreen.

All DB access goes through the patched_db fixture, so nothing here touches
the real per-user database. QMessageBox / QFileDialog static calls are
monkeypatched since they'd otherwise pop a real modal dialog and hang.
"""
import pytest

from app.ui.settings_screen import SettingsScreen
from app.core.settings_service import SettingsService


class _FakeNumpad:
    """Stands in for the admin-code NumpadDialog: "types" `code` and presses
    OK, or the next of `queue` when a test sets one (None = Cancel)."""
    code = "2060"
    queue: list = []

    def __init__(self, *args, **kwargs):
        self.value = None

    def exec(self):
        self.value = _FakeNumpad.queue.pop(0) if _FakeNumpad.queue else _FakeNumpad.code
        return self.value is not None


@pytest.fixture(autouse=True)
def _admin_code_typed(monkeypatch):
    """Settings' Admin button asks for the code; type the right one unless a
    test sets _FakeNumpad.code to something else."""
    monkeypatch.setattr("app.ui.settings_screen.NumpadDialog", _FakeNumpad)
    monkeypatch.setattr(_FakeNumpad, "code", "2060")
    monkeypatch.setattr(_FakeNumpad, "queue", [])


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


def test_save_emits_settings_saved(screen, qtbot):
    with qtbot.waitSignal(screen.settings_saved, timeout=1000):
        screen._save()


def test_test_print_shows_success_overlay(screen, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.ui.settings_screen.ReceiptService.test_print",
        lambda vendor_id, product_id: None,
    )
    monkeypatch.setattr(screen, "_show_overlay", lambda *a, **kw: calls.append((a, kw)))
    screen._test_print()
    assert len(calls) == 1
    assert calls[0][1].get("kind", "info") == "info"


def test_test_print_shows_error_overlay_on_failure(screen, monkeypatch):
    from app.core.receipt_service import PrinterError

    calls = []

    def _raise(vendor_id, product_id):
        raise PrinterError("Vendor ID is not configured. Set it in Settings.")

    monkeypatch.setattr("app.ui.settings_screen.ReceiptService.test_print", _raise)
    monkeypatch.setattr(screen, "_show_overlay", lambda *a, **kw: calls.append((a, kw)))
    screen._test_print()
    assert len(calls) == 1
    assert calls[0][1].get("kind") == "error"


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


# ── Shortcuts ────────────────────────────────────────────────────────────

def _shortcut_rows(screen):
    return [screen.shortcuts_list.item(i).text() for i in range(screen.shortcuts_list.count())]


def test_add_shortcut_creates_and_lists_it(screen, monkeypatch):
    from app.core.database import get_session
    from app.core.product_service import ProductService

    with get_session() as session:
        pid = ProductService.create(session, name="Cola", price=1.0, tax=21).id

    def fake_exec(self):
        self.sc_name = "Lunch"
        self.product_ids = [pid]
        return True

    monkeypatch.setattr("app.ui.settings_screen.ShortcutDialog.exec", fake_exec)
    screen._on_add_sc()

    assert "Lunch" in _shortcut_rows(screen)
    with get_session() as session:
        sc_id = ProductService.get_all_shortcuts(session)[0].id
        assert ProductService.get_shortcut_product_ids(session, sc_id) == [pid]


def test_edit_shortcut_renames_and_updates_items(screen, monkeypatch):
    from app.core.database import get_session
    from app.core.product_service import ProductService

    with get_session() as session:
        a = ProductService.create(session, name="A", price=1.0, tax=21).id
        b = ProductService.create(session, name="B", price=1.0, tax=21).id
        sc_id = ProductService.create_shortcut(session, "Old").id
        ProductService.set_shortcut_items(session, sc_id, [a])
    screen._reload_shortcuts()
    screen.shortcuts_list.setCurrentRow(0)

    def fake_exec(self):
        self.sc_name = "New"
        self.product_ids = [b, a]
        return True

    monkeypatch.setattr("app.ui.settings_screen.ShortcutDialog.exec", fake_exec)
    screen._on_edit_sc()

    assert _shortcut_rows(screen) == ["New"]
    with get_session() as session:
        assert ProductService.get_shortcut_product_ids(session, sc_id) == [b, a]


def test_remove_shortcut_deletes_it(screen, monkeypatch):
    from app.core.database import get_session
    from app.core.product_service import ProductService

    with get_session() as session:
        ProductService.create_shortcut(session, "Doomed")
    screen._reload_shortcuts()
    screen.shortcuts_list.setCurrentRow(0)

    monkeypatch.setattr(
        "app.ui.settings_screen.QMessageBox.question",
        lambda *a, **kw: __import__("PyQt6.QtWidgets", fromlist=["QMessageBox"]).QMessageBox.StandardButton.Yes,
    )
    screen._on_remove_sc()

    assert _shortcut_rows(screen) == []


def test_edit_shortcut_without_selection_does_nothing(screen, monkeypatch):
    opened = []
    monkeypatch.setattr("app.ui.settings_screen.ShortcutDialog", lambda *a, **kw: opened.append(a))
    screen.shortcuts_list.setCurrentRow(-1)
    screen._on_edit_sc()
    assert opened == []


# ── Buttons tab (Admin / RF-CN / Reports) ─────────────────────────────────

def test_admin_sets_flag_and_emits_signals(screen, qtbot):
    with qtbot.waitSignals([screen.admin_changed, screen.salesperson_changed], timeout=1000) as blocker:
        screen._admin()
    assert screen.is_admin is True
    assert [sig.args for sig in blocker.all_signals_and_args] == [(True,), ("Admin",)]


def test_admin_refused_with_wrong_code(screen, monkeypatch):
    monkeypatch.setattr(_FakeNumpad, "code", "1234")
    emitted = []
    screen.admin_changed.connect(emitted.append)

    screen._admin()

    assert screen.is_admin is False
    assert emitted == []
    assert screen.overlay.message_label.text() == "Wrong code."


def test_admin_button_again_leaves_admin_mode(screen, qtbot):
    from app.core.database import get_session
    with get_session() as session:
        SettingsService.set(session, "cashier_name", "Ann")
    screen._admin()

    with qtbot.waitSignals([screen.admin_changed, screen.salesperson_changed], timeout=1000) as blocker:
        screen._admin()

    assert screen.is_admin is False
    assert [sig.args for sig in blocker.all_signals_and_args] == [(False,), ("Ann",)]


def test_admin_code_change_needs_admin_mode(screen, monkeypatch):
    from app.core.admin import check_admin_code
    monkeypatch.setattr(_FakeNumpad, "queue", ["5555", "5555"])
    screen._change_admin_code()
    assert screen.overlay.message_label.text() == "Only admin."
    assert not check_admin_code("5555")


def test_admin_code_change_typed_twice_takes_effect(screen, monkeypatch):
    from app.core.admin import check_admin_code
    screen._admin()
    monkeypatch.setattr(_FakeNumpad, "queue", ["5555", "5555"])

    screen._change_admin_code()

    assert screen.overlay.message_label.text() == "Admin code changed."
    assert check_admin_code("5555") and not check_admin_code("2060")


@pytest.mark.parametrize("typed, message", [
    (["5555", "5556"], "The codes didn't match. Admin code not changed."),
    (["55"], "The admin code needs at least 4 digits."),
    (["5555", None], "The codes didn't match. Admin code not changed."),
])
def test_admin_code_change_refused_keeps_the_old_code(screen, monkeypatch, typed, message):
    from app.core.admin import check_admin_code
    screen._admin()
    monkeypatch.setattr(_FakeNumpad, "queue", typed)

    screen._change_admin_code()

    assert screen.overlay.message_label.text() == message
    assert check_admin_code("2060")


def test_admin_code_never_reaches_the_log(screen, monkeypatch, caplog):
    import logging
    screen._admin()
    monkeypatch.setattr(_FakeNumpad, "queue", ["8642", "8642"])
    with caplog.at_level(logging.INFO):
        screen._change_admin_code()
    assert "8642" not in caplog.text


def test_reports_blocked_without_admin(screen, monkeypatch, qtbot):
    warnings = []
    monkeypatch.setattr(screen, "_show_overlay", lambda *a, **kw: warnings.append(a))
    with qtbot.assertNotEmitted(screen.navigate):
        screen._open_reports()
    assert warnings


def test_reports_navigates_for_admin(screen, qtbot):
    screen._admin()
    with qtbot.waitSignal(screen.navigate, timeout=1000) as blocker:
        screen._open_reports()
    assert blocker.args == [4]


def test_rf_cn_blocked_without_admin(screen, monkeypatch, qtbot):
    warnings = []
    monkeypatch.setattr(screen, "_show_overlay", lambda *a, **kw: warnings.append(a))
    with qtbot.assertNotEmitted(screen.rf_cn_requested):
        screen._rf_cn()
    assert warnings


def test_rf_cn_requested_for_admin(screen, qtbot):
    screen._admin()
    with qtbot.waitSignal(screen.rf_cn_requested, timeout=1000):
        screen._rf_cn()


def test_close_pos_blocked_without_admin(screen, monkeypatch):
    warnings, quits = [], []
    monkeypatch.setattr(screen, "_show_overlay", lambda *a, **kw: warnings.append(a))
    monkeypatch.setattr("app.ui.settings_screen.QApplication.quit", lambda: quits.append(True))
    screen._close_pos()
    assert warnings
    assert quits == []


@pytest.mark.parametrize("answer, should_quit", [("Yes", True), ("No", False)])
def test_close_pos_asks_confirmation_for_admin(screen, monkeypatch, answer, should_quit):
    from app.ui.settings_screen import QMessageBox
    quits = []
    monkeypatch.setattr("app.ui.settings_screen.QMessageBox.question",
                        lambda *a, **kw: getattr(QMessageBox.StandardButton, answer))
    monkeypatch.setattr("app.ui.settings_screen.QApplication.quit", lambda: quits.append(True))
    screen._admin()
    screen._close_pos()
    assert bool(quits) is should_quit
