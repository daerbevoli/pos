"""
Client & Inventory Service
All business logic for managing Clients and stock.
"""
import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.models.models import Client

logger = logging.getLogger(__name__)

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

    @staticmethod
    def get_by_name(session: Session, name: str) -> Client | None:
        return session.query(Client).filter_by(name=name, is_active=True).first()

    @staticmethod
    def search(session: Session, query: str, include_inactive: bool = False) -> list[type[Client]]:
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
    def create(session: Session, **kwargs) -> Client:
        client = Client(**kwargs)
        session.add(client)
        session.commit()
        session.refresh(client)
        logger.info("Client created: %s %r", client.id, client.name)
        return client

    @staticmethod
    def update(session: Session, client_id: int, **kwargs) -> Client | None:
        client = session.query(Client).filter_by(id=client_id).first()
        if not client:
            logger.warning("Client update: client %s not found", client_id)
            return None
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
        if an active client has since taken one of its unique fields (name,
        address, phone, email, VAT, website — unique among active clients only)."""
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
