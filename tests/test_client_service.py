"""Tests for app.core.client_service.ClientService."""
import pytest

from app.core.client_service import ClientService
from app.models.models import Client


def _make_client(session, **overrides):
    data = {"name": "Client A", "vatNumber": "VAT-A"}
    data.update(overrides)
    return ClientService.create(session, **data)


def test_create_returns_persisted_client(db_session):
    client = _make_client(db_session, name="Acme", vatNumber="BE01")

    assert client.id is not None
    assert client.name == "Acme"
    assert client.is_active is True


def test_get_by_id(db_session):
    client = _make_client(db_session)
    found = ClientService.get_by_id(db_session, client.id)
    assert found is client

    assert ClientService.get_by_id(db_session, 99999) is None


def test_get_by_name_only_matches_active(db_session):
    client = _make_client(db_session, name="Findme")
    assert ClientService.get_by_name(db_session, "Findme") is client

    ClientService.deactivate(db_session, client.id)
    assert ClientService.get_by_name(db_session, "Findme") is None


def test_get_all_default_active_only(db_session):
    active = _make_client(db_session, name="Active", vatNumber="V1")
    inactive = _make_client(db_session, name="Inactive", vatNumber="V2")
    ClientService.deactivate(db_session, inactive.id)

    result = ClientService.get_all(db_session)
    assert result == [active]

    result_all = ClientService.get_all(db_session, active_only=False)
    assert {c.id for c in result_all} == {active.id, inactive.id}


def test_get_all_orders_by_name(db_session):
    _make_client(db_session, name="Zebra", vatNumber="V1")
    _make_client(db_session, name="Apple", vatNumber="V2")

    result = ClientService.get_all(db_session)
    assert [c.name for c in result] == ["Apple", "Zebra"]


def test_search_matches_name_or_vat_case_insensitive(db_session):
    c1 = _make_client(db_session, name="Fruit Market", vatNumber="BE0001")
    c2 = _make_client(db_session, name="Other Shop", vatNumber="BE0002FRUIT")
    _make_client(db_session, name="Unrelated", vatNumber="XYZ")

    result = ClientService.search(db_session, "fruit")
    assert {c.id for c in result} == {c1.id, c2.id}


def test_search_excludes_inactive(db_session):
    client = _make_client(db_session, name="Hidden")
    ClientService.deactivate(db_session, client.id)

    assert ClientService.search(db_session, "Hidden") == []


def test_search_limits_to_50(db_session):
    for i in range(60):
        _make_client(db_session, name=f"Bulk {i}", vatNumber=f"V{i}")
    result = ClientService.search(db_session, "Bulk")
    assert len(result) == 50


def test_update_modifies_fields(db_session):
    client = _make_client(db_session, name="Old Name")
    updated = ClientService.update(db_session, client.id, name="New Name", phone="123")

    assert updated.name == "New Name"
    assert updated.phone == "123"


def test_update_nonexistent_returns_none(db_session):
    assert ClientService.update(db_session, 99999, name="X") is None


def test_deactivate_soft_deletes(db_session):
    client = _make_client(db_session)
    result = ClientService.deactivate(db_session, client.id)

    assert result is True
    refreshed = ClientService.get_by_id(db_session, client.id)
    assert refreshed.is_active is False


def test_deactivate_nonexistent_returns_false(db_session):
    assert ClientService.deactivate(db_session, 99999) is False


def test_deactivate_preserves_row_not_deletes(db_session):
    client = _make_client(db_session)
    ClientService.deactivate(db_session, client.id)

    still_there = db_session.query(Client).filter_by(id=client.id).first()
    assert still_there is not None
