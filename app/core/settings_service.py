"""
Settings Service
Read and write application settings stored in the DB.
"""
import logging
from typing import Any

from sqlalchemy.orm import Session, InstrumentedAttribute
from app.models.models import Settings

logger = logging.getLogger(__name__)

# Keys whose values must never reach pos.log or the Logs panel.
_SECRET_KEYS = ("erp_api_key", "admin_code")


class SettingsService:

    @staticmethod
    def get(session: Session, key: str, default=None) -> InstrumentedAttribute | Any:
        row = session.query(Settings).filter_by(key=key).first()
        return row.value if row else default

    @staticmethod
    def set(session: Session, key: str, value: str):
        row = session.query(Settings).filter_by(key=key).first()
        old = row.value if row else None
        if row:
            row.value = value
        else:
            session.add(Settings(key=key, value=value))
        session.commit()
        if old != value:
            if key in _SECRET_KEYS:
                logger.info("Setting changed: %s (value hidden)", key)
            else:
                logger.info("Setting changed: %s %r -> %r", key, old, value)

    @staticmethod
    def get_all(session: Session) -> dict:
        rows = session.query(Settings).all()
        return {r.key: r.value for r in rows}

def get_store_data(session: Session):
    settings = SettingsService.get_all(session)
    return {
        "name": settings.get("store_name"),
        "address": settings.get("store_address"),
        "vat": settings.get("store_vat"),
        "phone": settings.get("store_phone"),
        "email": settings.get("store_email")
    }

def get_erp_data(session: Session):
    settings = SettingsService.get_all(session)
    return {
        "url": settings.get("erp_url"),
        "db": settings.get("erp_db"),
        "api_key": settings.get("erp_api_key"),
    }
