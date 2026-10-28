"""Tests for app.core.client_service.ClientService."""
import pytest

from app.core.client_service import ClientService
from app.models.models import Client


def _make_client(session, **overrides):
    data = {"name": "Client A", "vatNumber": "VAT-A"}
    data.update(overrides)
    data.setdefault("street", f"1 Main St, {data['name']}")
    data.setdefault("zip_code", "1000")
    data.setdefault("city", "Brussels")
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


def test_reactivate_restores_client(db_session):
    client = _make_client(db_session)
    ClientService.deactivate(db_session, client.id)
    assert ClientService.reactivate(db_session, client.id) is True
    assert ClientService.get_by_id(db_session, client.id).is_active is True


def test_reactivate_nonexistent_returns_false(db_session):
    assert ClientService.reactivate(db_session, 99999) is False


def test_reactivate_clashing_with_active_client_returns_false(db_session):
    old = _make_client(db_session, name="Dup", vatNumber="BE1")
    ClientService.deactivate(db_session, old.id)
    _make_client(db_session, name="Dup", vatNumber="BE2", street="2 Other St")

    assert ClientService.reactivate(db_session, old.id) is False
    assert ClientService.get_by_id(db_session, old.id).is_active is False


def test_search_include_inactive(db_session):
    client = _make_client(db_session, name="Retired")
    ClientService.deactivate(db_session, client.id)
    assert ClientService.search(db_session, "Ret") == []
    assert [c.id for c in ClientService.search(db_session, "Ret", include_inactive=True)] == [client.id]


def test_deactivate_preserves_row_not_deletes(db_session):
    client = _make_client(db_session)
    ClientService.deactivate(db_session, client.id)

    still_there = db_session.query(Client).filter_by(id=client.id).first()
    assert still_there is not None


# ── find_clash: unique fields checked before saving ──────────────────────

def _data(**overrides):
    data = {"name": "New", "vatNumber": "VAT-NEW", "street": "9 Other St", "zip_code": "2000",
            "city": "Antwerp", "phone": None, "email": None}
    data.update(overrides)
    return data


def test_find_clash_none_for_unique_data(db_session):
    _make_client(db_session, name="Acme", email="a@x.com")
    assert ClientService.find_clash(db_session, _data()) is None


@pytest.mark.parametrize("field,value,label", [
    ("name", "Acme", "Name"),
    ("vatNumber", "VAT-A", "VAT number"),
])
def test_find_clash_names_the_field_and_the_other_client(db_session, field, value, label):
    _make_client(db_session, name="Acme", vatNumber="VAT-A", email="a@x.com")
    assert ClientService.find_clash(db_session, _data(**{field: value})) == f"{label} already used by Acme"


def test_find_clash_allows_shared_address_phone_and_email(db_session):
    """Two companies in one building, or with one accountant, are fine."""
    _make_client(db_session, name="Acme", street="1 Main St", zip_code="1000", city="Brussels",
                 phone="021234567", email="books@x.com")
    shared = _data(street="1 Main St", zip_code="1000", city="Brussels", phone="021234567", email="books@x.com")
    assert ClientService.find_clash(db_session, shared) is None
    ClientService.create(db_session, **shared)  # and the database agrees


def test_find_clash_ignores_the_client_being_edited_and_inactive_ones(db_session):
    acme = _make_client(db_session, name="Acme")
    old = _make_client(db_session, name="Old", vatNumber="VAT-OLD")
    ClientService.deactivate(db_session, old.id)

    assert ClientService.find_clash(db_session, _data(name="Acme"), exclude_id=acme.id) is None
    assert ClientService.find_clash(db_session, _data(name="Old", vatNumber="VAT-OLD")) is None
