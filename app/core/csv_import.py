"""
CSV import shared by the client and article imports: reading the file, and
adding its rows one savepoint at a time. What a row means (which columns,
when it's skipped) lives with each service: ClientService.import_rows(),
ProductService.import_rows().
"""
import csv
import logging
from collections.abc import Callable

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class ImportFileError(Exception):
    """The file can't be imported at all; the message is for the cashier."""


def read_csv_rows(path: str) -> list[dict[str, str]]:
    """The file's rows, with header names lowercased and trimmed so "Street"
    and "street" are the same column. Raises ImportFileError if the file
    isn't a readable UTF-8 .csv/.txt."""
    if not path.lower().endswith((".csv", ".txt")):
        raise ImportFileError("Only csv and txt files allowed to import")
    try:
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except UnicodeDecodeError:
        raise ImportFileError(
            "This file isn't valid UTF-8 text. Re-save it as UTF-8 CSV and try again."
        ) from None
    except (OSError, csv.Error) as e:
        raise ImportFileError(f"Couldn't read file: {e}") from e
    # DictReader keys extra cells beyond the header under None: dropped.
    return [{key.strip().lower(): value for key, value in row.items() if key is not None}
            for row in rows]


def import_rows(session: Session, rows: list[dict], build_row: Callable[[dict], object | None],
                what: str, progress: Callable[[float], None] | None = None) -> tuple[int, int]:
    """Adds build_row(row) for every row; returns (added, skipped). build_row
    returns None to skip a row. Each row gets its own savepoint: a row that
    fails undoes only itself. progress(0..1), if given, is called about once
    per percent and at the end.

    Each row is saved as soon as it's added: under pysqlite's default
    transaction handling (see database.py) releasing a savepoint opened
    outside a transaction commits it. So SQLite's write lock is only held
    per row, and if the import stops partway the rows before are kept."""
    added = skipped = 0
    step = max(1, len(rows) // 100)
    for i, row in enumerate(rows, start=1):
        try:
            record = build_row(row)
            if record is None:
                skipped += 1
            else:
                with session.begin_nested():
                    session.add(record)
                    session.flush()
                added += 1
        except Exception as e:  # noqa: BLE001 — one bad row must not stop the import
            skipped += 1
            logger.warning("%s import: skipped %r: %s", what, row.get("name"), e)
        if progress is not None and (i % step == 0 or i == len(rows)):
            progress(i / len(rows))
    session.commit()
    return added, skipped
