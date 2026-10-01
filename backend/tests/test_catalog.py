import json
from datetime import date

import httpx
import pytest

from app.core.tools import ToolContext, run_tool
from app.db import SessionLocal
from app.integrations import flowaccount as fa
from app.models import User
from app.services import catalog
from app.services import documents as docs


@pytest.fixture
def db():
    s = SessionLocal()
    catalog.sync_products(s)  # mock list: GUTE/Top door closers + installation
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


def test_tools(db):
    owner = User(username="owner", password_hash="x", can_issue_documents=True)
    db.add(owner)
    db.commit()
    ctx = ToolContext(db=db, tuya=None, user=owner)
    out, err = run_tool(ctx, "save_product_set", {"name": "ชุด B", "items": [{"product": "โช๊คประตู Top ขนาด 1.2 เมตร", "quantity": 1}, {"product": "ลูกบิด", "quantity": 2}]})
    assert not err and json.loads(out)["not_in_product_list"] == ["ลูกบิด"]
    out, err = run_tool(ctx, "get_product_set", {"name": "ชุด B", "times": 3})
    assert not err and json.loads(out)["items"][0]["quantity"] == 3
    out, err = run_tool(ctx, "get_product_set", {"name": "ชุด Z", "times": 1})
    assert err and "ไม่พบชุด" in out

    # "เหมือนครั้งก่อน": the newest document of that customer.
    cust = {"name": "บริษัท เอ จำกัด", "tax_id": None, "address": None, "branch": None, "email": None, "phone": None}
    docs.prepare(db, owner, "dashboard", "quotation", cust, [{"name": "โช๊คประตู GUTE ขนาด 1 เมตร", "quantity": 2, "unit_price": 1200, "unit": "ตัว"}], True, False, 30, "", date(2026, 10, 1))
    out, err = run_tool(ctx, "last_order", {"customer": "บริษัท เอ"})
    last = json.loads(out)
    assert not err and last["items"] == [{"name": "โช๊คประตู GUTE ขนาด 1 เมตร", "quantity": 2.0, "unit": "ตัว", "unit_price": 1200.0}] and last["vat"] is True
    out, err = run_tool(ctx, "last_order", {"customer": "ร้านใหม่"})
    assert err and "ยังไม่เคยมีเอกสาร" in out


def test_endpoints(client, owner_headers):
    assert client.get("/products", headers=owner_headers).json() == []
    rows = client.post("/products/sync", headers=owner_headers).json()
    assert len(rows) == 6 and rows[0]["unit"]
    with SessionLocal() as s:
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


def test_set_remarks(db):
    catalog.save_set(db, "ชุด A", [{"product": "โช๊คประตู GUTE ขนาด 1 เมตร", "quantity": 2}], remarks="รับประกัน 1 ปี")
    catalog.save_set(db, "ชุด C", [{"product": "ค่าบริการติดตั้ง", "quantity": 1}], remarks="  ")
    assert catalog.expand_set(db, "ชุด A")["remarks"] == "รับประกัน 1 ปี"
    assert catalog.expand_set(db, "ชุด C")["remarks"] is None

    owner = User(username="owner", password_hash="x")
    db.add(owner)
    db.commit()
    ctx = ToolContext(db=db, tuya=None, user=owner)
    out, err = run_tool(ctx, "set_product_set_remarks", {"name": "ชุด C", "remarks": "ราคานี้รวมค่าติดตั้งในกรุงเทพฯ"})
    assert not err and json.loads(out) == {"set": "ชุด C", "remarks": "ราคานี้รวมค่าติดตั้งในกรุงเทพฯ"}
    # Changing the remarks leaves the items alone; clearing works too.
    assert catalog.expand_set(db, "ชุด C")["items"][0]["name"] == "ค่าบริการติดตั้ง"
    run_tool(ctx, "set_product_set_remarks", {"name": "ชุด A", "remarks": ""})
    assert [s["remarks"] for s in catalog.list_sets(db)] == [None, "ราคานี้รวมค่าติดตั้งในกรุงเทพฯ"]
