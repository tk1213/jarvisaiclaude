import json

import pytest

from app import permissions
from app.core import orchestrator as orch_module
from app.core.tools import ToolContext, run_tool
from app.db import SessionLocal
from app.models import User

from .test_line import line, link, last_text, post_event, text_event  # noqa: F401  (line is a fixture)


@pytest.fixture
def db():
    with SessionLocal() as s:
        yield s


def member(client, owner_headers, name="staff", **levels):
    r = client.post("/users", headers=owner_headers, json={"username": name, "password": "password123", "permissions": levels})
    assert r.status_code == 201
    token = client.post("/auth/login", json={"username": name, "password": "password123"}).json()["access_token"]
    return r.json(), {"Authorization": f"Bearer {token}"}


def test_new_member_starts_with_no_pages(client, owner_headers):
    body, staff = member(client, owner_headers)
    assert body["permissions"] == {"home": "none", "flowaccount": "none", "account": "none", "personal": "none", "chat": "none"}
    assert client.get("/auth/me", headers=staff).status_code == 200
    assert client.get("/devices", headers=staff).status_code == 403
    assert client.get("/documents", headers=staff).status_code == 403
    assert client.get("/product-sets", headers=staff).status_code == 403
    assert client.get("/account/summary", params={"month": "2026-10"}, headers=staff).status_code == 403
    assert client.get("/personal/accounts", headers=staff).status_code == 403
    assert client.get("/core/chat/current", headers=staff).status_code == 403
    assert client.post("/voice/tts", json={"text": "x"}, headers=staff).status_code == 403


def test_view_can_read_but_not_change(client, owner_headers):
    _, staff = member(client, owner_headers, account="view", personal="view", home="view", flowaccount="view")
    assert client.get("/account/summary", params={"month": "2026-10"}, headers=staff).status_code == 200
    assert client.get("/account/entries", params={"kind": "expense", "month": "2026-10"}, headers=staff).status_code == 200
    entry = {"kind": "expense", "date": "2026-10-03", "party": "ร้าน บี", "base": 100, "full_tax_invoice": False}
    assert client.post("/account/entries", json=entry, headers=staff).status_code == 403
    assert client.post("/account/sync", headers=staff).status_code == 403
    assert client.get("/personal/accounts", headers=staff).status_code == 200
    assert client.post("/personal/accounts", json={"bank": "KBANK", "nickname": "x"}, headers=staff).status_code == 403

    client.post("/devices/sync", headers=owner_headers)
    assert client.get("/devices", headers=staff).status_code == 200
    assert client.post("/devices/sync", headers=staff).status_code == 403
    assert client.post("/devices/1/power", json={"on": True}, headers=staff).status_code == 403
    assert client.get("/product-sets", headers=staff).status_code == 200
    assert client.put("/product-sets/1", json={"name": "ชุด A", "items": []}, headers=staff).status_code == 403


def test_edit_can_change(client, owner_headers):
    _, staff = member(client, owner_headers, account="edit", home="edit")
    entry = {"kind": "expense", "date": "2026-10-03", "party": "ร้าน บี", "base": 100, "full_tax_invoice": False}
    assert client.post("/account/entries", json=entry, headers=staff).status_code == 201
    client.post("/devices/sync", headers=owner_headers)
    assert client.post("/devices/1/power", json={"on": True}, headers=staff).status_code == 200
    assert client.get("/personal/accounts", headers=staff).status_code == 403  # only what was ticked


def test_admin_changes_levels_and_they_apply_at_once(client, owner_headers):
    body, staff = member(client, owner_headers)
    assert client.get("/account/info", headers=staff).status_code == 403
    r = client.put(f"/users/{body['id']}", json={"display_name": "พนักงาน", "permissions": {"account": "view", "chat": "view"}}, headers=owner_headers)
    assert r.status_code == 200
    assert r.json()["display_name"] == "พนักงาน"
    assert r.json()["permissions"]["account"] == "view" and r.json()["permissions"]["chat"] == "edit"  # chat has no view-only
    assert client.get("/account/info", headers=staff).status_code == 200  # same token, new rights

    # Only admins manage members, and an admin's own pages can't be narrowed.
    assert client.get("/users", headers=staff).status_code == 403
    assert client.put(f"/users/{body['id']}", json={"permissions": {"account": "edit"}}, headers=staff).status_code == 403
    owner_id = client.get("/auth/me", headers=owner_headers).json()["id"]
    assert client.put(f"/users/{owner_id}", json={"permissions": {}}, headers=owner_headers).status_code == 400
    assert set(client.get("/auth/me", headers=owner_headers).json()["permissions"].values()) == {"edit"}


def test_reset_password_and_delete(client, owner_headers):
    body, staff = member(client, owner_headers, home="view")
    assert client.post(f"/users/{body['id']}/password", json={"password": "new-password-1"}, headers=owner_headers).status_code == 204
    assert client.post("/auth/login", json={"username": "staff", "password": "password123"}).status_code == 401
    assert client.post("/auth/login", json={"username": "staff", "password": "new-password-1"}).status_code == 200
    assert client.post(f"/users/{body['id']}/password", json={"password": "short"}, headers=owner_headers).status_code == 422

    owner_id = client.get("/auth/me", headers=owner_headers).json()["id"]
    assert client.delete(f"/users/{owner_id}", headers=owner_headers).status_code == 400
    assert client.delete(f"/users/{body['id']}", headers=owner_headers).status_code == 204
    assert client.get("/auth/me", headers=staff).status_code == 401  # their old token stops working
    assert client.post("/auth/login", json={"username": "staff", "password": "new-password-1"}).status_code == 401
    assert [u["username"] for u in client.get("/users", headers=owner_headers).json()] == ["owner"]
    assert client.delete(f"/users/{body['id']}", headers=owner_headers).status_code == 404
    member(client, owner_headers)  # the username is free again


def test_older_accounts_keep_their_access(db):
    old = User(username="old", password_hash="x", can_control_devices=True, can_issue_documents=False)
    assert permissions.levels(old) == {"home": "edit", "flowaccount": "view", "account": "none", "personal": "none", "chat": "edit"}
    permissions.set_levels(old, {"home": "view", "flowaccount": "edit", "account": "bogus"})
    assert (old.can_control_devices, old.can_issue_documents) == (False, True)
    assert json.loads(old.permissions)["account"] == "none"


def test_jarvis_tools_follow_the_pages(db):
    user = User(username="staff", password_hash="x")
    permissions.set_levels(user, {"home": "view", "chat": "edit"})
    db.add(user)
    db.commit()
    ctx = ToolContext(db=db, tuya=None, user=user)
    out, err = run_tool(ctx, "control_device", {"device_id": 1, "commands": [{"code": "switch_1", "value": True}]})
    assert err and "แก้ไขหน้าบ้าน" in out
    out, err = run_tool(ctx, "list_product_sets", {})
    assert err and "เข้าหน้าFlowAccount" in out


def test_line_chat_needs_the_chat_page(client, owner_headers, line, monkeypatch):  # noqa: F811
    monkeypatch.setattr(orch_module, "_orchestrator", None)  # would fail if JARVIS were asked
    body, staff = member(client, owner_headers)
    link(client, staff, line, line_user="Ustaff")
    post_event(client, text_event("เปิดไฟ", "Ustaff"))
    assert "ยังไม่ได้รับสิทธิ์คุยกับจาร์วิส" in last_text(line)
