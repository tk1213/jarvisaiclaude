def test_bootstrap_only_once(client):
    r = client.post("/auth/bootstrap", json={"username": "owner", "password": "password123"})
    assert r.status_code == 201
    body = r.json()
    assert body["is_admin"] and body["can_control_devices"] and body["can_issue_documents"]

    r = client.post("/auth/bootstrap", json={"username": "intruder", "password": "password123"})
    assert r.status_code == 409


def test_login_and_me(client, owner_headers):
    assert client.get("/auth/me", headers=owner_headers).json()["username"] == "owner"


def test_wrong_password(client, owner_headers):
    r = client.post("/auth/login", json={"username": "owner", "password": "nope-nope"})
    assert r.status_code == 401


def test_endpoints_require_auth(client):
    assert client.get("/devices").status_code == 401
    assert client.get("/devices", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_admin_creates_user_without_device_permission(client, owner_headers):
    r = client.post(
        "/users",
        headers=owner_headers,
        json={"username": "guest", "password": "password123", "can_control_devices": False},
    )
    assert r.status_code == 201
    token = client.post("/auth/login", json={"username": "guest", "password": "password123"}).json()["access_token"]
    guest = {"Authorization": f"Bearer {token}"}

    client.post("/devices/sync", headers=owner_headers)
    assert client.get("/devices", headers=guest).status_code == 200
    assert client.post("/devices/1/power", headers=guest, json={"on": True}).status_code == 403
    assert client.post("/users", headers=guest, json={"username": "x", "password": "password123"}).status_code == 403
