"""
Tests for app.ui.dialogs.import_progress_dialog.ImportProgressDialog: a
CSV import run on a worker thread behind a progress bar.

patched_db isolates the DB; start() is called instead of exec() so the
test isn't blocked by the modal loop.
"""
from app.core.client_service import ClientService
from app.core.database import get_session
from app.core.product_service import ProductService
from app.ui.dialogs.import_progress_dialog import ImportProgressDialog


def _run(qtbot, import_fn, rows):
    d = ImportProgressDialog("articles", import_fn, rows)
    qtbot.addWidget(d)
    values = []
    d.bar.valueChanged.connect(values.append)
    with qtbot.waitSignal(d.run_finished, timeout=10000):
        d.start()
    return d, values


def test_import_runs_to_completion_with_progress(qtbot, patched_db):
    rows = [{"name": f"Article {i}", "barcode": f"BC{i}", "price": "1.5"} for i in range(250)]
    d, values = _run(qtbot, ProductService.import_rows, rows)

    assert (d.added, d.skipped) == (250, 0)
    assert d.bar.value() == 100
    assert len(values) > 2 and values == sorted(values)  # moves forward step by step
    assert "250 added, 0 skipped" in d.step_label.text()
    assert not d.btn_close.isHidden()
    with get_session() as session:
        assert len(ProductService.get_all(session)) == 250


def test_failed_import_reports_it_and_leaves_counts_unset(qtbot, patched_db):
    def boom(session, rows, progress=None):
        raise RuntimeError("database is locked")
    d, _ = _run(qtbot, boom, [{"name": "x"}])

    assert d.added is None and d.skipped is None
    assert "database is locked" in d.step_label.text()
    assert "imported before the error are kept" in d.step_label.text()
    assert not d.btn_close.isHidden()


def test_cannot_be_dismissed_while_running(qtbot, patched_db):
    d = ImportProgressDialog("clients", ClientService.import_rows, [])
    qtbot.addWidget(d)
    d.show()
    d.is_running = True
    d.reject()
    assert d.isVisible()
    d.is_running = False
    d.reject()
    assert not d.isVisible()

