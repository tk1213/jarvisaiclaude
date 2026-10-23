from app import page_names, permissions
from app.db import CompanySession, PersonalSession
from app.services import personal


def test_admin_renames_pages_and_everyone_sees_it(client, owner_headers):
    assert client.get("/page-names", headers=owner_headers).json() == page_names.DEFAULTS
    r = client.put("/page-names", headers=owner_headers, json={"company": "  🏢   บัญชีบริษัท TK ", "nope": "x"})
    assert r.status_code == 200
    assert r.json()["company"] == "🏢 บัญชีบริษัท TK" and "nope" not in r.json()
    assert r.json()["personal"] == page_names.DEFAULTS["personal"]

    client.post("/users", headers=owner_headers, json={"username": "staff", "password": "password123"})
    staff = {"Authorization": "Bearer " + client.post("/auth/login", json={"username": "staff", "password": "password123"}).json()["access_token"]}
    assert client.get("/page-names", headers=staff).json()["company"] == "🏢 บัญชีบริษัท TK"
    assert client.put("/page-names", headers=staff, json={"company": "x"}).status_code == 403
    assert client.get("/page-names").status_code == 401

    # The new name is used in errors and LINE replies too.
    r = client.get("/company/accounts", headers=staff)
    assert r.status_code == 403 and "🏢 บัญชีบริษัท TK" in r.json()["detail"]
    assert "บัญชีบริษัท TK" in permissions.denied_text("company")
    with CompanySession() as db:
        assert "🏢 บัญชีบริษัท TK" in personal.no_accounts(db)
    with PersonalSession() as db:
        assert page_names.DEFAULTS["personal"] in personal.no_accounts(db)

    # Blank = back to the default; long names are cut.
    r = client.put("/page-names", headers=owner_headers, json={"company": " ", "home": "บ" * 100})
    assert r.json()["company"] == page_names.DEFAULTS["company"]
    assert r.json()["home"] == "บ" * page_names.MAX_LENGTH
