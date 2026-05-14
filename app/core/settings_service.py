"""
Settings Service
Read and write application settings stored in the DB.
"""
from typing import Any

from sqlalchemy.orm import Session, InstrumentedAttribute
from app.models.models import Settings


class SettingsService:

    @staticmethod
    def get(session: Session, key: str, default=None) -> InstrumentedAttribute | Any:
        row = session.query(Settings).filter_by(key=key).first()
        return row.value if row else default

    @staticmethod
    def set(session: Session, key: str, value: str):
        row = session.query(Settings).filter_by(key=key).first()
        if row:
            row.value = value
        else:
            session.add(Settings(key=key, value=value))
        session.commit()

    @staticmethod
    def get_all(session: Session) -> dict:
        rows = session.query(Settings).all()
        return {r.key: r.value for r in rows}
