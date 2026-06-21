"""
Seed dummy products into the POS database for testing.
Run once: python seed_dummy_data.py
"""
from app.core.database import init_db, get_session
from app.models.models import Category, Product, Client

DUMMY_PRODUCTS = [
    # Fruit & Vegetables
    {"barcode": "01", "name": "Banana (kg)",       "price": 1.49, "stock_quantity": 50,  "unit": "kg",  "tax": 6,  "category": "Fruit & Vegetables"},
    {"barcode": "02", "name": "Apple Gala (kg)",   "price": 1.99, "stock_quantity": 40,  "unit": "kg",  "tax": 6,  "category": "Fruit & Vegetables"},
    {"barcode": "03", "name": "Tomato (kg)",        "price": 2.29, "stock_quantity": 30,  "unit": "kg",  "tax": 6,  "category": "Fruit & Vegetables"},
    {"barcode": "04", "name": "Carrot (kg)",        "price": 0.99, "stock_quantity": 35,  "unit": "kg",  "tax": 6,  "category": "Fruit & Vegetables"},
    {"barcode": "05", "name": "Broccoli",           "price": 1.29, "stock_quantity": 20,  "unit": "pcs", "tax": 6,  "category": "Fruit & Vegetables"},

    # Dairy & Eggs
    {"barcode": "10", "name": "Whole Milk 1L",      "price": 1.09, "stock_quantity": 60,  "unit": "pcs", "tax": 6,  "category": "Dairy & Eggs"},
    {"barcode": "11", "name": "Butter 250g",        "price": 2.49, "stock_quantity": 25,  "unit": "pcs", "tax": 6,  "category": "Dairy & Eggs"},
    {"barcode": "12", "name": "Eggs x12",           "price": 3.29, "stock_quantity": 30,  "unit": "pcs", "tax": 6,  "category": "Dairy & Eggs"},
    {"barcode": "13", "name": "Greek Yogurt 500g",  "price": 1.89, "stock_quantity": 20,  "unit": "pcs", "tax": 6,  "category": "Dairy & Eggs"},
    {"barcode": "14", "name": "Cheddar Cheese 200g","price": 2.99, "stock_quantity": 18,  "unit": "pcs", "tax": 6,  "category": "Dairy & Eggs"},

    # Meat & Fish
    {"barcode": "20", "name": "Chicken Breast (kg)","price": 7.99, "stock_quantity": 15,  "unit": "kg",  "tax": 6,  "category": "Meat & Fish"},
    {"barcode": "21", "name": "Ground Beef (kg)",   "price": 9.49, "stock_quantity": 10,  "unit": "kg",  "tax": 6,  "category": "Meat & Fish"},
    {"barcode": "22", "name": "Salmon Fillet (kg)", "price": 14.99,"stock_quantity": 8,   "unit": "kg",  "tax": 6,  "category": "Meat & Fish"},
    {"barcode": "23", "name": "Bacon 200g",         "price": 3.49, "stock_quantity": 22,  "unit": "pcs", "tax": 6,  "category": "Meat & Fish"},

    # Bakery
    {"barcode": "30", "name": "White Bread 800g",   "price": 1.69, "stock_quantity": 25,  "unit": "pcs", "tax": 6,  "category": "Bakery"},
    {"barcode": "31", "name": "Croissant",          "price": 0.89, "stock_quantity": 30,  "unit": "pcs", "tax": 6,  "category": "Bakery"},
    {"barcode": "32", "name": "Sourdough Loaf",     "price": 3.29, "stock_quantity": 12,  "unit": "pcs", "tax": 6,  "category": "Bakery"},
    {"barcode": "33", "name": "Baguette",           "price": 1.19, "stock_quantity": 20,  "unit": "pcs", "tax": 6,  "category": "Bakery"},

    # Frozen
    {"barcode": "40", "name": "Frozen Pizza Margherita","price": 3.99,"stock_quantity": 15,"unit": "pcs","tax": 21, "category": "Frozen"},
    {"barcode": "41", "name": "Frozen Peas 500g",   "price": 1.49, "stock_quantity": 20,  "unit": "pcs", "tax": 6,  "category": "Frozen"},
    {"barcode": "42", "name": "Ice Cream Vanilla 1L","price": 4.49, "stock_quantity": 10,  "unit": "pcs", "tax": 21, "category": "Frozen"},
    {"barcode": "43", "name": "Frozen Fries 1kg",   "price": 2.29, "stock_quantity": 18,  "unit": "pcs", "tax": 6,  "category": "Frozen"},

    # Beverages
    {"barcode": "50", "name": "Still Water 1.5L",   "price": 0.69, "stock_quantity": 80,  "unit": "pcs", "tax": 6,  "category": "Beverages"},
    {"barcode": "51", "name": "Orange Juice 1L",    "price": 2.19, "stock_quantity": 35,  "unit": "pcs", "tax": 6,  "category": "Beverages"},
    {"barcode": "52", "name": "Cola 330ml Can",     "price": 1.09, "stock_quantity": 60,  "unit": "pcs", "tax": 21, "category": "Beverages"},
    {"barcode": "53", "name": "Beer 330ml",         "price": 1.49, "stock_quantity": 48,  "unit": "pcs", "tax": 21, "category": "Beverages"},
    {"barcode": "54", "name": "Coffee Beans 250g",  "price": 5.99, "stock_quantity": 20,  "unit": "pcs", "tax": 21, "category": "Beverages"},

    # Snacks & Confectionery
    {"barcode": "60", "name": "Potato Chips 150g",  "price": 1.99, "stock_quantity": 40,  "unit": "pcs", "tax": 21, "category": "Snacks & Confectionery"},
    {"barcode": "61", "name": "Milk Chocolate 100g","price": 1.49, "stock_quantity": 35,  "unit": "pcs", "tax": 21, "category": "Snacks & Confectionery"},
    {"barcode": "62", "name": "Mixed Nuts 200g",    "price": 3.79, "stock_quantity": 25,  "unit": "pcs", "tax": 21, "category": "Snacks & Confectionery"},
    {"barcode": "63", "name": "Gummy Bears 200g",   "price": 1.29, "stock_quantity": 30,  "unit": "pcs", "tax": 21, "category": "Snacks & Confectionery"},

    # Cleaning & Household
    {"barcode": "70", "name": "Washing Liquid 1L",  "price": 4.99, "stock_quantity": 15,  "unit": "pcs", "tax": 21, "category": "Cleaning & Household"},
    {"barcode": "71", "name": "Toilet Paper x8",    "price": 3.49, "stock_quantity": 20,  "unit": "pcs", "tax": 6,  "category": "Cleaning & Household"},
    {"barcode": "72", "name": "Dish Soap 500ml",    "price": 1.79, "stock_quantity": 18,  "unit": "pcs", "tax": 21, "category": "Cleaning & Household"},

    # Personal Care
    {"barcode": "80", "name": "Shampoo 300ml",      "price": 3.29, "stock_quantity": 15,  "unit": "pcs", "tax": 21, "category": "Personal Care"},
    {"barcode": "81", "name": "Toothpaste 75ml",    "price": 1.99, "stock_quantity": 20,  "unit": "pcs", "tax": 21, "category": "Personal Care"},
    {"barcode": "82", "name": "Deodorant 150ml",    "price": 2.49, "stock_quantity": 12,  "unit": "pcs", "tax": 21, "category": "Personal Care"},

    # Other
    {"barcode": "90", "name": "Plastic Bag",        "price": 0.10, "stock_quantity": 500, "unit": "pcs", "tax": 21, "category": "Other"},
    {"barcode": "91", "name": "Gift Wrapping",      "price": 1.50, "stock_quantity": 50,  "unit": "pcs", "tax": 21, "category": "Other"},
]


DUMMY_CLIENTS = [
    {"name": "De Groene Mand",       "address": "Kerkstraat 12, 2000 Antwerpen",    "phone": "+32 3 123 45 67",  "email": "info@degroenemand.be",      "vatNumber": "BE0123456789", "website": "www.degroenemand.be"},
    {"name": "Boulangerie Dupont",   "address": "Rue du Marché 5, 1000 Bruxelles",  "phone": "+32 2 234 56 78",  "email": "dupont@boulangerie.be",     "vatNumber": "BE0234567890", "website": None},
    {"name": "Horeca Supplies NV",   "address": "Industrielaan 88, 9000 Gent",      "phone": "+32 9 345 67 89",  "email": "orders@horecasupplies.be",  "vatNumber": "BE0345678901", "website": "www.horecasupplies.be"},
    {"name": "Frituur 't Hoekske",   "address": "Dorpsplein 3, 3000 Leuven",        "phone": "+32 16 456 78 90", "email": "hoekske@frituur.be",        "vatNumber": "BE0456789012", "website": None},
    {"name": "Café De Kroon",        "address": "Grote Markt 1, 8000 Brugge",       "phone": "+32 50 567 89 01", "email": "dekroon@cafe.be",           "vatNumber": "BE0567890123", "website": None},
    {"name": "Slagerij Vermeersch",  "address": "Steenweg 44, 8500 Kortrijk",       "phone": "+32 56 678 90 12", "email": "info@vermeersch.be",        "vatNumber": "BE0678901234", "website": "www.vermeersch-slagerij.be"},
    {"name": "Biomarkt Leuven",      "address": "Naamsestraat 60, 3000 Leuven",     "phone": "+32 16 789 01 23", "email": "bio@marktleuven.be",        "vatNumber": "BE0789012345", "website": "www.biomarktleuven.be"},
    {"name": "Quick Lunch BVBA",     "address": "Stationsplein 9, 2018 Antwerpen",  "phone": "+32 3 890 12 34",  "email": "quicklunch@bvba.be",        "vatNumber": "BE0890123456", "website": None},
    {"name": "Taverne Het Anker",    "address": "Vismarkt 7, 9000 Gent",            "phone": "+32 9 901 23 45",  "email": "anker@taverne.be",          "vatNumber": "BE0901234567", "website": None},
    {"name": "Épicerie Fine Moreau", "address": "Avenue Louise 34, 1050 Ixelles",   "phone": "+32 2 012 34 56",  "email": "moreau@epicerie.be",        "vatNumber": "BE0012345678", "website": "www.epiceriemoreau.be"},
    {"name": "Supermarkt Vandenberghe", "address": "Leopoldlaan 15, 2300 Turnhout", "phone": "+32 14 111 22 33", "email": "info@vandenberghe-sm.be",  "vatNumber": "BE0111223344", "website": None},
    {"name": "Pizzeria Da Luca",     "address": "Mechelsesteenweg 22, 2018 Antwerpen","phone": "+32 3 222 33 44","email": "luca@pizzeria.be",          "vatNumber": "BE0222334455", "website": "www.daluca.be"},
]


def seed():
    init_db()
    session = get_session()
    try:
        added = 0
        skipped = 0
        for data in DUMMY_PRODUCTS:
            existing = session.query(Product).filter_by(barcode=data["barcode"]).first()
            if existing:
                skipped += 1
                continue

            cat = session.query(Category).filter_by(name=data["category"]).first()
            session.add(Product(
                barcode=data["barcode"],
                name=data["name"],
                price=data["price"],
                stock_quantity=data["stock_quantity"],
                min_stock_level=5,
                unit=data["unit"],
                tax=data["tax"],
                category_id=cat.id if cat else None,
                is_active=True,
            ))
            added += 1

        session.commit()
        print(f"Done — {added} products added, {skipped} already existed.")

        clients_added = 0
        clients_skipped = 0
        for data in DUMMY_CLIENTS:
            existing = session.query(Client).filter_by(vatNumber=data["vatNumber"]).first()
            if existing:
                clients_skipped += 1
                continue
            session.add(Client(**data, is_active=True))
            clients_added += 1

        session.commit()
        print(f"Done — {clients_added} clients added, {clients_skipped} already existed.")
    finally:
        session.close()


if __name__ == "__main__":
    seed()
