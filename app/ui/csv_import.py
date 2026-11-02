"""The UI side of a CSV import, shared by the client and inventory panels:
read the picked file, import it, refresh the list and show the outcome."""
import logging
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.core.csv_import import ImportFileError, read_csv_rows
from app.core.database import get_session

logger = logging.getLogger(__name__)


def run_csv_import(panel, path: str, import_fn: Callable[[Session, list[dict]], tuple[int, int]],
                   what: str):
    """Imports `path` with import_fn (e.g. ClientService.import_rows) on
    behalf of `panel`, a detail panel with _show_overlay() and a
    parent_screen to refresh. A file that can't be read imports nothing."""
    try:
        rows = read_csv_rows(path)
    except ImportFileError as e:
        panel._show_overlay(str(e), kind="error")
        return
    with get_session() as session:
        added, skipped = import_fn(session, rows)
    logger.info("%s import from %s: %d added, %d skipped", what, path, added, skipped)
    panel.parent_screen.refresh()
    panel._show_overlay(f"Import complete: {added} added, {skipped} skipped.")
