"""
Tests for app.models.models: schema behavior, defaults, relationships,
constraints, and computed properties.
"""
import pytest
from sqlalchemy.exc import IntegrityError

from app.models.models import (
    Category, Product, Sale, SaleItem, StockMovement, Settings, Client, Invoice,
)


# ── Category ─────────────────────────────────────────────────────────────

def test_category_repr_and_defaults(db_session):
    cat = Category(name="Bakery")
    db_session.add(cat)
    db_session.commit()

    assert cat.id is not None
    assert cat.description is None
    assert cat.created_at is not None
    assert repr(cat) == "<Category Bakery>"


def test_category_name_must_be_unique(db_session):
    db_session.add(Category(name="Dairy"))
    db_session.commit()
    db_session.add(Category(name="Dairy"))
    with pytest.raises(IntegrityError):
        db_session.commit()


# ── Product ──────────────────────────────────────────────────────────────

def test_product_defaults(db_session):
    p = Product(name="Milk", price=1.5)
    db_session.add(p)
    db_session.commit()

    assert p.stock_quantity == 0
    assert p.min_stock_level == 5
    assert p.unit == "pcs"
    assert p.tax == 21
    assert p.is_active is True
    assert p.barcode is None


@pytest.mark.parametrize(
    "stock, min_level, expected",
    [(5, 5, True), (4, 5, True), (6, 5, False), (0, 0, True)],
)
def test_product_is_low_stock(db_session, stock, min_level, expected):
    p = Product(name="Widget", price=1.0, stock_quantity=stock, min_stock_level=min_level)
    assert p.is_low_stock is expected


def test_product_barcode_unique(db_session):
    db_session.add(Product(name="A", price=1.0, barcode="123"))
    db_session.commit()
    db_session.add(Product(name="B", price=2.0, barcode="123"))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_product_category_relationship(db_session):
    cat = Category(name="Snacks")
    db_session.add(cat)
    db_session.commit()

    p = Product(name="Chips", price=2.0, category_id=cat.id)
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)

    assert p.category.name == "Snacks"
    assert cat.products == [p]


def test_product_repr(db_session):
    p = Product(name="Bread", price=2.0, barcode="999")
    assert repr(p) == "<Product Bread (999)>"


# ── Sale / SaleItem ──────────────────────────────────────────────────────

def test_sale_defaults_and_repr(db_session):
    sale = Sale(sale_number="S-1", total_amount=10.0, final_amount=10.0)
    db_session.add(sale)
    db_session.commit()

    assert sale.tax_amount == 0.0
    assert sale.payment_method == "cash"
    assert sale.status == "completed"
    assert repr(sale) == "<Sale S-1 €10.00>"


def test_sale_number_unique(db_session):
    db_session.add(Sale(sale_number="S-DUP", total_amount=1, final_amount=1))
    db_session.commit()
    db_session.add(Sale(sale_number="S-DUP", total_amount=2, final_amount=2))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_sale_items_cascade_delete(db_session):
    p = Product(name="X", price=1.0)
    db_session.add(p)
    db_session.commit()

    sale = Sale(sale_number="S-2", total_amount=1.0, final_amount=1.0)
    db_session.add(sale)
    db_session.commit()

    item = SaleItem(
        sale_id=sale.id, product_id=p.id, product_name="X",
        quantity=1, unit_price=1.0, line_total=1.0,
    )
    db_session.add(item)
    db_session.commit()

    assert len(sale.items) == 1
    item_id = item.id

    db_session.delete(sale)
    db_session.commit()

    assert db_session.get(SaleItem, item_id) is None


def test_sale_item_repr(db_session):
    item = SaleItem(
        sale_id=1, product_id=1, product_name="Cola",
        quantity=3, unit_price=1.0, line_total=3.0,
    )
    assert repr(item) == "<SaleItem Cola x3>"


# ── StockMovement ────────────────────────────────────────────────────────

def test_stock_movement_repr(db_session):
    mv = StockMovement(
        product_id=1, movement_type="purchase", quantity=5,
        quantity_before=0, quantity_after=5,
    )
    assert repr(mv) == "<StockMovement 1 purchase 5>"


# ── Settings ─────────────────────────────────────────────────────────────

def test_settings_key_unique(db_session):
    db_session.add(Settings(key="foo", value="1"))
    db_session.commit()
    db_session.add(Settings(key="foo", value="2"))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_settings_repr(db_session):
    s = Settings(key="k", value="v")
    assert repr(s) == "<Setting k=v>"


# ── Client ───────────────────────────────────────────────────────────────

def test_client_defaults(db_session):
    c = Client(name="ACME", vatNumber="BE0123456789")
    db_session.add(c)
    db_session.commit()

    assert c.is_active is True
    assert c.address is None
    assert repr(c) == "<Client ACME BE0123456789>"


def test_client_unique_fields_enforced_only_while_active(db_session):
    c1 = Client(name="Dup Client", vatNumber="VAT1")
    db_session.add(c1)
    db_session.commit()

    # Same name, active — should violate the partial unique index.
    c2 = Client(name="Dup Client", vatNumber="VAT2")
    db_session.add(c2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # Deactivate the first, then the name should be free again.
    c1.is_active = False
    db_session.commit()

    c3 = Client(name="Dup Client", vatNumber="VAT3")
    db_session.add(c3)
    db_session.commit()  # should not raise

    assert c3.id is not None


def test_client_unique_vat_while_active(db_session):
    db_session.add(Client(name="A", vatNumber="SAMEVAT"))
    db_session.commit()
    db_session.add(Client(name="B", vatNumber="SAMEVAT"))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_client_null_optional_fields_do_not_collide(db_session):
    """address/phone/email/website are nullable; multiple NULLs must not
    trip the partial unique indexes (SQL NULL != NULL)."""
    db_session.add(Client(name="A", vatNumber="V1", address=None, phone=None, email=None, website=None))
    db_session.add(Client(name="B", vatNumber="V2", address=None, phone=None, email=None, website=None))
    db_session.commit()  # should not raise


# ── Invoice ──────────────────────────────────────────────────────────────

def test_invoice_relationships(db_session):
    client = Client(name="Client", vatNumber="V1")
    sale = Sale(sale_number="S-INV", total_amount=5.0, final_amount=5.0)
    db_session.add_all([client, sale])
    db_session.commit()

    invoice = Invoice(sale_id=sale.id, client_id=client.id, invoice_number="I-1")
    db_session.add(invoice)
    db_session.commit()
    db_session.refresh(sale)
    db_session.refresh(client)

    assert sale.invoice is invoice
    assert invoice.sale is sale
    assert invoice.client is client
    assert client.invoices == [invoice]


def test_invoice_snapshot_fields_default_to_none_and_issued_at_is_set(db_session):
    sale = Sale(sale_number="S-SNAP", total_amount=1, final_amount=1)
    db_session.add(sale)
    db_session.commit()

    invoice = Invoice(sale_id=sale.id, invoice_number="I-SNAP")
    db_session.add(invoice)
    db_session.commit()

    assert invoice.issued_at is not None
    assert invoice.client_name is None
    assert invoice.client_vat_number is None
    assert invoice.client_address is None
    assert invoice.total_amount is None
    assert invoice.tax_amount is None
    assert invoice.final_amount is None
    assert invoice.line_items_snapshot is None


def test_invoice_snapshot_survives_client_mutation(db_session):
    """The whole point of the snapshot: once written, it must not change
    even if the live client it was copied from is later edited."""
    client = Client(name="Original Name", vatNumber="V-ORIG", address="Old Address")
    sale = Sale(sale_number="S-SNAP2", total_amount=10.0, final_amount=10.0)
    db_session.add_all([client, sale])
    db_session.commit()

    invoice = Invoice(
        sale_id=sale.id, client_id=client.id, invoice_number="I-SNAP2",
        client_name=client.name, client_vat_number=client.vatNumber, client_address=client.address,
        total_amount=sale.total_amount, tax_amount=0.0, final_amount=sale.final_amount,
    )
    db_session.add(invoice)
    db_session.commit()

    client.name = "Renamed Later"
    client.vatNumber = "V-CHANGED"
    client.is_active = False
    db_session.commit()
    db_session.refresh(invoice)

    assert invoice.client_name == "Original Name"
    assert invoice.client_vat_number == "V-ORIG"
    assert invoice.client_address == "Old Address"


def test_invoice_number_unique(db_session):
    sale1 = Sale(sale_number="S-A", total_amount=1, final_amount=1)
    sale2 = Sale(sale_number="S-B", total_amount=1, final_amount=1)
    db_session.add_all([sale1, sale2])
    db_session.commit()

    db_session.add(Invoice(sale_id=sale1.id, invoice_number="I-DUP"))
    db_session.commit()
    db_session.add(Invoice(sale_id=sale2.id, invoice_number="I-DUP"))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_invoice_sale_id_unique_one_to_one(db_session):
    sale = Sale(sale_number="S-ONE", total_amount=1, final_amount=1)
    db_session.add(sale)
    db_session.commit()

    db_session.add(Invoice(sale_id=sale.id, invoice_number="I-1"))
    db_session.commit()
    db_session.add(Invoice(sale_id=sale.id, invoice_number="I-2"))
    with pytest.raises(IntegrityError):
        db_session.commit()
