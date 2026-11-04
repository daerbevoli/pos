"""Tests for app.core.erp_service.ErpService, with Odoo's API faked."""
from app.core.erp_service import ErpService
from app.core.sales_service import InvoiceLine


def _line(name, rate):
    return InvoiceLine(product_name=name, quantity=1, unit_price_excl_tax=10.0, unit="pcs",
                       tax_rate=rate, line_total_excl_tax=10.0)


def test_invoice_lines_look_up_each_tax_rate_once(monkeypatch):
    erp = ErpService(url="http://odoo", db="db", api_key="key")
    lookups = []
    monkeypatch.setattr(erp, "get_sales_account_id", lambda: 700)
    monkeypatch.setattr(erp, "get_sale_tax_id", lambda rate: lookups.append(rate) or int(rate) + 100)

    lines = erp.create_invoice_lines([_line("A", 6), _line("B", 21), _line("C", 6)])

    assert lookups == [6, 21]
    assert [vals["tax_ids"] for _, _, vals in lines] == [[(6, 0, [106])], [(6, 0, [121])], [(6, 0, [106])]]


# ── A fake Odoo: answers ErpService._call() and records every call ───────

import pytest

from app.core.erp_service import ERPError

CUSTOMER = {"name": "Acme", "street": "Kerkstraat 1", "zip": "2000", "city": "Antwerpen",
            "country": "BE", "vat": "BE 0477.472.701", "phone": None, "email": "acme@example.com"}


class FakeOdoo:
    def __init__(self, partner=None, move=None, email="acme@example.com", peppol="valid"):
        self.partner = partner        # existing res.partner record (dict) or None
        self.move = move              # existing account.move record (dict) or None
        self.email = email
        self.peppol = peppol
        self.calls = []

    def __call__(self, model, method, payload):
        self.calls.append((model, method, payload))
        if (model, method) == ("res.country", "search"):
            return [32]
        if (model, method) == ("account.journal", "search"):
            return [5]
        if (model, method) == ("account.account", "search"):
            return [700]
        if (model, method) == ("account.tax", "search"):
            return [100 + payload["domain"][1][2]]
        if (model, method) == ("res.partner", "search"):
            return [self.partner["id"]] if self.partner else []
        if (model, method) == ("res.partner", "read"):
            if "peppol_verification_state" in payload["fields"]:
                return [{"email": self.email, "peppol_verification_state": self.peppol}]
            return [self.partner]
        if (model, method) == ("account.move", "search"):
            return [self.move["id"]] if self.move else []
        if (model, method) == ("account.move", "read"):
            return [self.move or {"state": "posted", "partner_id": [9, "Acme"], "peppol_move_state": False}]
        if method == "create":
            return [77]
        return True

    def made(self, model, method):
        return [payload for m, meth, payload in self.calls if (m, meth) == (model, method)]


@pytest.fixture
def erp_with(monkeypatch):
    def _make(odoo):
        erp = ErpService(url="http://odoo", db="db", api_key="key")
        monkeypatch.setattr(erp, "_call", odoo)
        return erp
    return _make


def _invoice_data(price=10.0):
    return {"inv_num": "I-041126-001", "inv_date": "2026-11-04", "due_date": "2026-11-11",
            "to": CUSTOMER, "move_type": "out_invoice", "notes": "",
            "items": [InvoiceLine(product_name="A", quantity=2, unit_price_excl_tax=price, unit="pcs",
                                  tax_rate=21, line_total_excl_tax=2 * price)]}


def _move(state="posted", sent=False):
    return {"id": 42, "state": state, "is_move_sent": sent, "peppol_move_state": False,
            "partner_id": [9, "Acme"]}


def _existing_partner(**changes):
    partner = {"id": 9, "name": "Acme", "street": "Kerkstraat 1", "zip": "2000", "city": "Antwerpen",
               "phone": "+32 3 123 45 67", "email": False, "country_id": [32, "Belgium"]}
    partner.update(changes)
    return partner


def test_partner_is_found_by_the_normalized_vat_number(erp_with):
    odoo = FakeOdoo(partner=_existing_partner())
    erp_with(odoo).get_or_create_partner(CUSTOMER)

    assert odoo.made("res.partner", "search")[0]["domain"] == [["vat", "=", "BE0477472701"]]


def test_found_partner_gets_the_pos_values_that_differ(erp_with):
    odoo = FakeOdoo(partner=_existing_partner(street="Old street 9", country_id=[21, "France"]))

    assert erp_with(odoo).get_or_create_partner(CUSTOMER) == 9

    # email was missing in Odoo, street/country differ; the phone the POS
    # doesn't have stays as Odoo has it.
    assert odoo.made("res.partner", "write") == [
        {"ids": [9], "vals": {"street": "Kerkstraat 1", "email": "acme@example.com", "country_id": 32}},
    ]


def test_found_partner_matching_the_pos_is_left_alone(erp_with):
    odoo = FakeOdoo(partner=_existing_partner(email="acme@example.com"))
    erp_with(odoo).get_or_create_partner(CUSTOMER)

    assert odoo.made("res.partner", "write") == []


def test_existing_invoice_is_logged_and_taken_as_it_is(erp_with, caplog):
    """Same reference already in Odoo: not created again, not compared or
    rewritten — only logged."""
    import logging
    odoo = FakeOdoo(partner=_existing_partner(), move=_move())

    with caplog.at_level(logging.INFO):
        assert erp_with(odoo).create_post_invoice(_invoice_data()) == (42, False)

    assert odoo.made("account.move", "create") == []
    assert odoo.made("account.move", "write") == []
    assert odoo.made("account.move", "action_post") == []
    assert odoo.made("account.move.line", "read") == []
    assert any("I-041126-001 already exists" in r.getMessage() for r in caplog.records)


def test_existing_draft_invoice_is_posted(erp_with):
    odoo = FakeOdoo(partner=_existing_partner(), move=_move(state="draft"))
    erp_with(odoo).create_post_invoice(_invoice_data())

    assert odoo.made("account.move", "action_post") == [{"ids": [42], "context": {}}]


def test_existing_sent_invoice_reports_sent(erp_with):
    odoo = FakeOdoo(partner=_existing_partner(), move=_move(sent=True))

    assert erp_with(odoo).create_post_invoice(_invoice_data()) == (42, True)


def test_existing_cancelled_invoice_is_refused(erp_with):
    odoo = FakeOdoo(partner=_existing_partner(), move=_move(state="cancel"))

    with pytest.raises(ERPError, match="cancelled"):
        erp_with(odoo).create_post_invoice(_invoice_data())


def test_new_invoice_is_created_and_posted(erp_with):
    odoo = FakeOdoo(partner=_existing_partner())

    assert erp_with(odoo).create_post_invoice(_invoice_data()) == (77, False)
    vals = odoo.made("account.move", "create")[0]["vals_list"][0]
    assert (vals["ref"], vals["partner_id"], len(vals["invoice_line_ids"])) == ("I-041126-001", 9, 1)
    assert odoo.made("account.move", "action_post") == [{"ids": [77], "context": {}}]


def _sent_with(odoo):
    return odoo.made("account.move.send.wizard", "create")[0]["vals_list"][0]["sending_methods"]


def test_partner_with_email_gets_peppol_and_email(erp_with):
    odoo = FakeOdoo(email="acme@example.com", peppol="valid")

    assert erp_with(odoo).send_invoice(42, use_peppol=True, use_email=True) == (True, "Invoice sent via peppol and email")
    assert _sent_with(odoo) == ["peppol", "email"]


def test_partner_without_email_gets_peppol_only_and_its_logged(erp_with, caplog):
    import logging
    odoo = FakeOdoo(email=False, peppol="valid")

    with caplog.at_level(logging.INFO):
        sent, message = erp_with(odoo).send_invoice(42, use_peppol=True, use_email=True)

    assert sent is True and _sent_with(odoo) == ["peppol"]
    assert "no email address" in message
    assert any("has no email address" in r.getMessage() for r in caplog.records)


def test_partner_not_on_peppol_gets_nothing_not_even_email(erp_with, caplog):
    import logging
    odoo = FakeOdoo(email="acme@example.com", peppol="not_valid")

    with caplog.at_level(logging.WARNING):
        sent, reason = erp_with(odoo).send_invoice(42, use_peppol=True, use_email=True)

    assert (sent, reason) == (False, "Partner is not on Peppol: manual sending required")
    assert odoo.made("account.move.send.wizard", "create") == []
    assert any("manual sending required" in r.getMessage() for r in caplog.records)


def test_unchecked_partner_starts_its_peppol_check_and_sends_nothing(erp_with):
    odoo = FakeOdoo(email="acme@example.com", peppol="not_verified")

    sent, reason = erp_with(odoo).send_invoice(42, use_peppol=True, use_email=True)

    assert sent is False and "send again later" in reason
    assert odoo.made("res.partner", "button_account_peppol_check_partner_endpoint") == [{"ids": [9], "context": {}}]
    assert odoo.made("account.move.send.wizard", "create") == []


def test_peppol_off_sends_email_only_without_checking_peppol(erp_with):
    """Development setting: Peppol isn't used, nor its registration checked."""
    odoo = FakeOdoo(email="acme@example.com", peppol="not_verified")

    assert erp_with(odoo).send_invoice(42, use_peppol=False, use_email=True) == (True, "Invoice sent via email")
    assert _sent_with(odoo) == ["email"]
    assert odoo.made("res.partner", "button_account_peppol_check_partner_endpoint") == []


def test_peppol_off_and_no_email_sends_nothing(erp_with):
    odoo = FakeOdoo(email=False)

    assert erp_with(odoo).send_invoice(42, use_peppol=False, use_email=True) == (False, "Partner has no email address")
    assert odoo.made("account.move.send.wizard", "create") == []


def test_email_off_sends_peppol_only(erp_with):
    odoo = FakeOdoo(email="acme@example.com", peppol="valid")

    assert erp_with(odoo).send_invoice(42, use_peppol=True, use_email=False) == (True, "Invoice sent via peppol")
