import json
from datetime import date

import httpx
import pytest

from app.core.tools import ToolContext, run_tool
from app.db import CatalogSession, SessionLocal
from app.integrations import flowaccount as fa
from app.models import User
from app.services import catalog
from app.services import documents as docs


@pytest.fixture
def db():
    s = CatalogSession()
    catalog.sync_products(s)  # mock list: GUTE/Top door closers + installation
    yield s
    s.close()


@pytest.fixture
def main_db():
    s = SessionLocal()
    yield s
    s.close()


def names(products):
    return [p.name for p in products]


def test_find_products_ignores_tone_marks_and_spaces(db):
    assert names(catalog.find_products(db, "โช็ค GUTE 1.5")) == ["โช๊คประตู GUTE ขนาด 1.5 เมตร"]
    assert names(catalog.find_products(db, "โชค top 1.2")) == ["โช๊คประตู Top ขนาด 1.2 เมตร"]
    # Ambiguous: every GUTE matches, so JARVIS can ask which size.
    assert len(catalog.find_products(db, "GUTE")) == 3
    assert names(catalog.find_products(db, "DC-T150")) == ["โช๊คประตู Top ขนาด 1.5 เมตร"]
    assert catalog.find_products(db, "ตู้เย็น") == []


def test_sets_use_list_prices_unless_fixed(db):
    catalog.save_set(db, "ชุด A", [{"product": "โช็คประตู GUTE ขนาด 1 เมตร", "quantity": 2}, {"product": "โช๊คประตู GUTE ขนาด 1.5 เมตร", "quantity": 3}])
    catalog.save_set(db, "ชุด C", [{"product": "โช๊คประตู Top ขนาด 1.5 เมตร", "quantity": 2}, {"product": "ค่าบริการติดตั้ง", "quantity": 1, "unit_price": 400}], customer="บริษัท เอ")
    a = catalog.expand_set(db, "ชุด a", times=2)
    assert [(i["name"], i["quantity"], i["unit_price"], i["unit"]) for i in a["items"]] == [
        ("โช๊คประตู GUTE ขนาด 1 เมตร", 4, 1200, "ตัว"),  # spelling normalized to the product list
        ("โช๊คประตู GUTE ขนาด 1.5 เมตร", 6, 1650, "ตัว"),
    ]
    c = catalog.expand_set(db, "ชุดC", 1)
    assert c["customer"] == "บริษัท เอ" and c["items"][1]["unit_price"] == 400 and c["items"][1]["price_source"] == "ราคาพิเศษของชุด"
    # Saving again replaces the set.
    catalog.save_set(db, "ชุด A", [{"product": "โช๊คประตู GUTE ขนาด 1 เมตร", "quantity": 1}])
    assert [s["name"] for s in catalog.list_sets(db)] == ["ชุด A", "ชุด C"] and len(catalog.list_sets(db)[0]["items"]) == 1
    catalog.delete_set(db, "ชุด A")
    with pytest.raises(catalog.CatalogError, match="ไม่พบชุด 'ชุด A'.*ชุด C"):
        catalog.expand_set(db, "ชุด A")


def test_item_not_in_list_has_no_price(db):
    catalog.save_set(db, "ชุด X", [{"product": "ของแถมพิเศษ", "quantity": 1}])
    assert catalog.expand_set(db, "ชุด X")["items"][0]["unit_price"] is None


def test_tools(db, main_db):
    owner = User(username="owner", password_hash="x", can_issue_documents=True)
    main_db.add(owner)
    main_db.commit()
    ctx = ToolContext(db=main_db, tuya=None, user=owner)
    out, err = run_tool(ctx, "save_product_set", {"name": "ชุด B", "items": [{"product": "โช๊คประตู Top ขนาด 1.2 เมตร", "quantity": 1}, {"product": "ลูกบิด", "quantity": 2}]})
    assert not err and json.loads(out)["not_in_product_list"] == ["ลูกบิด"]
    out, err = run_tool(ctx, "get_product_set", {"name": "ชุด B", "times": 3})
    assert not err and json.loads(out)["items"][0]["quantity"] == 3
    out, err = run_tool(ctx, "get_product_set", {"name": "ชุด Z", "times": 1})
    assert err and "ไม่พบชุด" in out

    # "เหมือนครั้งก่อน": the newest document of that customer.
    cust = {"name": "บริษัท เอ จำกัด", "tax_id": None, "address": None, "branch": None, "email": None, "phone": None}
    docs.prepare(main_db, owner, "dashboard", "quotation", cust, [{"name": "โช๊คประตู GUTE ขนาด 1 เมตร", "quantity": 2, "unit_price": 1200, "unit": "ตัว"}], True, False, 30, "", date(2026, 10, 1))
    out, err = run_tool(ctx, "last_order", {"customer": "บริษัท เอ"})
    last = json.loads(out)
    assert not err and last["items"] == [{"name": "โช๊คประตู GUTE ขนาด 1 เมตร", "quantity": 2.0, "unit": "ตัว", "unit_price": 1200.0}] and last["vat"] is True
    out, err = run_tool(ctx, "last_order", {"customer": "ร้านใหม่"})
    assert err and "ยังไม่เคยมีเอกสาร" in out


def test_endpoints(client, owner_headers):
    assert client.get("/products", headers=owner_headers).json() == []
    rows = client.post("/products/sync", headers=owner_headers).json()
    assert len(rows) == 6 and rows[0]["unit"]
    with CatalogSession() as s:
        catalog.save_set(s, "ชุด A", [{"product": "ค่าบริการติดตั้ง", "quantity": 1}])
    sets = client.get("/product-sets", headers=owner_headers).json()
    assert sets[0]["name"] == "ชุด A" and sets[0]["items"][0]["unit"] == "งาน"
    assert client.delete(f"/product-sets/{sets[0]['id']}", headers=owner_headers).status_code == 204
    assert client.get("/product-sets", headers=owner_headers).json() == []


def test_live_product_listing_pages():
    pages = {1: [{"id": "1", "name": "A", "sellPrice": 10}], 2: [{"id": "2", "name": "B", "sellPrice": 20}]}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        page = int(request.url.params["currentPage"])
        assert request.url.params["pageSize"] == "100" and request.headers["authorization"] == "Bearer t"
        return httpx.Response(200, json={"status": True, "data": {"total": 2, "currentPage": page, "list": pages.get(page, [])}})

    client = fa.FlowAccountClient("https://x/v1", "a", "b", "s", http=httpx.Client(transport=httpx.MockTransport(handler)))
    assert [p["name"] for p in client.list_products()] == ["A", "B"]


def test_set_remarks(db, main_db):
    catalog.save_set(db, "ชุด A", [{"product": "โช๊คประตู GUTE ขนาด 1 เมตร", "quantity": 2}], remarks="รับประกัน 1 ปี")
    catalog.save_set(db, "ชุด C", [{"product": "ค่าบริการติดตั้ง", "quantity": 1}], remarks="  ")
    assert catalog.expand_set(db, "ชุด A")["remarks"] == "รับประกัน 1 ปี"
    assert catalog.expand_set(db, "ชุด C")["remarks"] is None

    owner = User(username="owner", password_hash="x")
    main_db.add(owner)
    main_db.commit()
    ctx = ToolContext(db=main_db, tuya=None, user=owner)
    out, err = run_tool(ctx, "set_product_set_remarks", {"name": "ชุด C", "remarks": "ราคานี้รวมค่าติดตั้งในกรุงเทพฯ"})
    assert not err and json.loads(out) == {"set": "ชุด C", "remarks": "ราคานี้รวมค่าติดตั้งในกรุงเทพฯ"}
    # Changing the remarks leaves the items alone; clearing works too.
    assert catalog.expand_set(db, "ชุด C")["items"][0]["name"] == "ค่าบริการติดตั้ง"
    run_tool(ctx, "set_product_set_remarks", {"name": "ชุด A", "remarks": ""})
    db.expire_all()
    assert [s["remarks"] for s in catalog.list_sets(db)] == [None, "ราคานี้รวมค่าติดตั้งในกรุงเทพฯ"]


def test_catalog_lives_in_its_own_file_and_old_sets_are_moved(tmp_path, monkeypatch):
    """Products and sets saved in the main database before the split are copied over once."""
    from sqlalchemy import create_engine, text

    from app import db as db_module

    main = create_engine(f"sqlite:///{tmp_path}/main.db")
    with main.begin() as c:
        c.execute(text("CREATE TABLE product_sets (id INTEGER PRIMARY KEY, name VARCHAR(128), customer VARCHAR(256), updated_at DATETIME)"))
        c.execute(text("CREATE TABLE product_set_items (id INTEGER PRIMARY KEY, set_id INTEGER, position INTEGER, product VARCHAR(256), quantity FLOAT, unit_price FLOAT, unit VARCHAR(32))"))
        c.execute(text("INSERT INTO product_sets VALUES (7, 'ชุด A', NULL, '2026-10-01 00:00:00')"))
        c.execute(text("INSERT INTO product_set_items VALUES (1, 7, 0, 'โช๊คประตู GUTE ขนาด 1 เมตร', 2, NULL, 'ตัว')"))
    cat = db_module._catalog_engine(f"sqlite:///{tmp_path}/data/flowaccount/catalog.db")
    monkeypatch.setattr(db_module, "engine", main)
    monkeypatch.setattr(db_module, "catalog_engine", cat)

    db_module.init_catalog_db()
    db_module.init_catalog_db()  # running again doesn't copy twice
    assert (tmp_path / "data" / "flowaccount" / "catalog.db").exists()
    with cat.connect() as c:
        assert c.execute(text("SELECT id, name, remarks FROM product_sets")).all() == [(7, "ชุด A", None)]
        assert c.execute(text("SELECT set_id, product, quantity FROM product_set_items")).all() == [(7, "โช๊คประตู GUTE ขนาด 1 เมตร", 2.0)]


def test_dashboard_edits_a_set(client, owner_headers):
    client.post("/products/sync", headers=owner_headers)
    with CatalogSession() as s:
        catalog.save_set(s, "ชุด A", [{"product": "โช๊คประตู GUTE ขนาด 1 เมตร", "quantity": 2}], remarks="รับประกัน 1 ปี")
        catalog.save_set(s, "ชุด B", [{"product": "ค่าติดตั้ง", "quantity": 1}])
    set_a = next(x for x in client.get("/product-sets", headers=owner_headers).json() if x["name"] == "ชุด A")
    assert set_a["description"] is None and set_a["items"][0]["list_price"] > 0 and set_a["items"][0]["unit_price"] is None

    body = {
        "name": "ชุด A",
        "description": "โช๊คประตูบ้านเดี่ยว",
        "remarks": "รับประกัน 2 ปี",
        "items": [
            {"product": "โช๊คประตู GUTE ขนาด 1 เมตร", "quantity": 3, "unit": "กล่อง", "unit_price": 1990},  # special price
            {"product": "โช๊คประตู GUTE ขนาด 1.5 เมตร", "quantity": 1, "unit": None, "unit_price": None},  # added, FlowAccount price
        ],
    }
    r = client.put(f"/product-sets/{set_a['id']}", json=body, headers=owner_headers)
    assert r.status_code == 200
    out = r.json()
    assert (out["description"], out["remarks"]) == ("โช๊คประตูบ้านเดี่ยว", "รับประกัน 2 ปี")
    assert [(i["product"], i["quantity"], i["unit_price"]) for i in out["items"]] == [
        ("โช๊คประตู GUTE ขนาด 1 เมตร", 3, 1990),
        ("โช๊คประตู GUTE ขนาด 1.5 เมตร", 1, None),
    ]
    with CatalogSession() as s:
        expanded = catalog.expand_set(s, "ชุด A")
        assert expanded["items"][0]["unit_price"] == 1990 and expanded["remarks"] == "รับประกัน 2 ปี"
        # JARVIS re-saving the set keeps the dashboard description.
        catalog.save_set(s, "ชุด A", [{"product": "ค่าติดตั้ง", "quantity": 1}])
    assert next(x for x in client.get("/product-sets", headers=owner_headers).json() if x["name"] == "ชุด A")["description"] == "โช๊คประตูบ้านเดี่ยว"

    # Renaming onto another set, bad quantities and unknown sets are refused.
    assert client.put(f"/product-sets/{set_a['id']}", json=body | {"name": "ชุด b"}, headers=owner_headers).status_code == 400
    bad = body | {"items": [{"product": "ค่าติดตั้ง", "quantity": 0}]}
    assert client.put(f"/product-sets/{set_a['id']}", json=bad, headers=owner_headers).status_code == 422
    assert client.put(f"/product-sets/{set_a['id']}", json=body | {"items": []}, headers=owner_headers).status_code == 422
    assert client.put("/product-sets/999", json=body, headers=owner_headers).status_code == 404
