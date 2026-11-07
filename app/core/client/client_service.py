"""
Client & Inventory Service
All business logic for managing Clients and stock.
"""
import logging
from collections.abc import Callable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.constants.countries import BELGIUM, COUNTRY_NAMES
from app.core import csv_import
from app.models.models import Client
from app.utils.validators import is_valid_vat, normalize_vat

logger = logging.getLogger(__name__)

# Fields unique among active clients (the partial unique indexes on Client),
# with the name the cashier sees.
_UNIQUE_FIELDS = {
    ("name",): "Name",
    ("vatNumber",): "VAT number",
}

class ClientService:

    # ── Client CRUD ──────────────────────────────────────────────────────────

    @staticmethod
    def get_all(session: Session, active_only=True) -> list[Client]:
        q = session.query(Client)
        if active_only:
            q = q.filter(Client.is_active == True)
        return q.order_by(Client.name).all()

    @staticmethod
    def get_by_id(session: Session, client_id: int) -> Client | None:
        return session.query(Client).filter_by(id=client_id).first()

    # ── CSV import ───────────────────────────────────────────────────────────

    @staticmethod
    def import_rows(session: Session, rows: list[dict],
                    progress: Callable[[float], None] | None = None) -> tuple[int, int]:
        """Adds the clients of a CSV import (see read_csv_rows()); returns
        (added, skipped). progress: see csv_import.import_rows()."""
        return csv_import.import_rows(session, rows, lambda row: ClientService._from_import_row(session, row), "Client", progress)

    @staticmethod
    def _from_import_row(session: Session, row: dict) -> Client | None:
        """A new Client from one import row, or None to skip it: no name, no
        street, no or an invalid VAT number, or that VAT number is already a
        client (already imported; a shared email is fine)."""
        vat = normalize_vat(row.get("vat"))
        street =(row.get("street") or "").strip()
        zip_code = (row.get("zip") or row.get("zip_code") or "").strip()
        city = (row.get("city") or "").strip()
        if not street and not zip_code and not city and row.get("address"):
            # Old export format (one free-text address column) — best effort.
            street = row.get("address")
        country = (row.get("country") or "").strip().upper()
        if country not in COUNTRY_NAMES:
            country = BELGIUM
        if not vat or not row.get("name") or not street or not is_valid_vat(vat, country):
            return None
        if session.query(Client).filter_by(vatNumber=vat).first() is not None:
            return None
        return Client(
            name=row.get("name"),
            vatNumber=vat,
            street=street,
            zip_code=zip_code,
            city=city,
            country=country,
            phone=(row.get("phone") or "").lstrip("'") or None,
            email=row.get("email") or None,
            is_active=True,
        )

    @staticmethod
    def get_by_name(session: Session, name: str) -> Client | None:
        return session.query(Client).filter_by(name=name, is_active=True).first()

    @staticmethod
    def search(session: Session, query: str, include_inactive: bool = False) -> list[Client]:
        """Search by name or vat."""
        term = f"%{query}%"
        q = session.query(Client).filter(
            (Client.name.ilike(term)) | (Client.vatNumber.ilike(term))
        )
        if not include_inactive:
            q = q.filter(Client.is_active == True)

        return (
            q.order_by(Client.name)
            .limit(50)
            .all()
        )

    @staticmethod
    def find_clash(session: Session, data: dict, exclude_id: int | None = None) -> str | None:
        """Why saving `data` would break a unique index, e.g. "VAT number
        already used by Acme", or None if it wouldn't. Checked before saving
        so the cashier gets a reason instead of an IntegrityError."""
        for columns, label in _UNIQUE_FIELDS.items():
            values = {column: data.get(column) for column in columns}
            if any(value is None for value in values.values()):
                continue  # NULLs never clash, and a field not being saved can't either
            if "vatNumber" in values:
                values["vatNumber"] = normalize_vat(values["vatNumber"])  # as create()/update() store it
            q =session.query(Client).filter_by(is_active=True, **values)
            if exclude_id is not None:
                q = q.filter(Client.id != exclude_id)
            other = q.first()
            if other is not None:
                return f"{label} already used by {other.name}"
        return None

    @staticmethod
    def create(session: Session, **kwargs) -> Client:
        if "vatNumber" in kwargs:
            kwargs["vatNumber"] = normalize_vat(kwargs["vatNumber"])
        client = Client(**kwargs)
        session.add(client)
        session.commit()
        session.refresh(client)
        logger.info("Client created: %s %r", client.id, client.name)
        return client

    @staticmethod
    def update(session: Session, client_id: int, **kwargs) -> type[Client] | None:
        client = session.query(Client).filter_by(id=client_id).first()
        if not client:
            logger.warning("Client update: client %s not found", client_id)
            return None
        if "vatNumber" in kwargs:
            kwargs["vatNumber"] = normalize_vat(kwargs["vatNumber"])
        for key, value in kwargs.items():
            setattr(client, key, value)
        session.commit()
        session.refresh(client)
        # Field names only: values are customer contact details.
        logger.info("Client updated: %s %r (%s)", client.id, client.name, ", ".join(kwargs))
        return client

    @staticmethod
    def deactivate(session: Session, client_id: int) -> bool:
        """Soft delete — keeps sales history intact."""
        client = session.query(Client).filter_by(id=client_id).first()
        if not client:
            logger.warning("Client deactivate: client %s not found", client_id)
            return False
        client.is_active = False
        session.commit()
        logger.info("Client deactivated: %s %r", client.id, client.name)
        return True

    @staticmethod
    def reactivate(session: Session, client_id: int) -> bool:
        """Undoes deactivate(). Returns False if the client doesn't exist, or
        if an active client has since taken its name or VAT number (unique
        among active clients only)."""
        client = session.query(Client).filter_by(id=client_id).first()
        if not client:
            logger.warning("Client reactivate: client %s not found", client_id)
            return False
        client.is_active = True
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            logger.warning("Client reactivate: client %s clashes with an active client", client_id)
            return False
        logger.info("Client reactivated: %s %r", client.id, client.name)
        return True
