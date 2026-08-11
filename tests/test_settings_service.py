"""Tests for app.core.settings_service.SettingsService."""
from app.core.settings_service import SettingsService
from app.models.models import Settings


def test_get_returns_default_when_missing(db_session):
    assert SettingsService.get(db_session, "missing_key") is None
    assert SettingsService.get(db_session, "missing_key", "fallback") == "fallback"


def test_set_creates_new_row(db_session):
    SettingsService.set(db_session, "store_name", "My Shop")
    row = db_session.query(Settings).filter_by(key="store_name").first()
    assert row is not None
    assert row.value == "My Shop"


def test_set_updates_existing_row_without_duplicating(db_session):
    SettingsService.set(db_session, "currency_symbol", "$")
    SettingsService.set(db_session, "currency_symbol", "€")

    rows = db_session.query(Settings).filter_by(key="currency_symbol").all()
    assert len(rows) == 1
    assert rows[0].value == "€"


def test_get_after_set_round_trip(db_session):
    SettingsService.set(db_session, "foo", "bar")
    assert SettingsService.get(db_session, "foo") == "bar"


def test_get_all_returns_dict_of_all_settings(db_session):
    SettingsService.set(db_session, "a", "1")
    SettingsService.set(db_session, "b", "2")

    result = SettingsService.get_all(db_session)
    assert result == {"a": "1", "b": "2"}


def test_get_all_empty_when_no_settings(db_session):
    assert SettingsService.get_all(db_session) == {}
