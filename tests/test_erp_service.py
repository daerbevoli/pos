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
