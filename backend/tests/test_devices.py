def _sync(client, headers):
    r = client.post("/devices/sync", headers=headers)
    assert r.status_code == 200
    return {d["name"]: d for d in r.json()}


def test_sync_assigns_rooms(client, owner_headers):
    devices = _sync(client, owner_headers)
    assert devices["แอร์ห้องนอน"]["room"] == "ห้องนอน"
    assert devices["ไฟห้องนั่งเล่น"]["status"]["switch_led"] is False


def test_sync_is_idempotent(client, owner_headers):
    _sync(client, owner_headers)
    _sync(client, owner_headers)
    assert len(client.get("/devices", headers=owner_headers).json()) == 3


def test_filter_by_room(client, owner_headers):
    _sync(client, owner_headers)
    found = client.get("/devices", params={"room": "ห้องนอน"}, headers=owner_headers).json()
    assert [d["name"] for d in found] == ["แอร์ห้องนอน"]


def test_power_uses_right_code_per_device(client, owner_headers):
    devices = _sync(client, owner_headers)
    light = devices["ไฟห้องนั่งเล่น"]
    plug = devices["ปลั๊กกาต้มน้ำ"]

    r = client.post(f"/devices/{light['id']}/power", json={"on": True}, headers=owner_headers)
    assert r.json()["status"]["switch_led"] is True
    r = client.post(f"/devices/{plug['id']}/power", json={"on": True}, headers=owner_headers)
    assert r.json()["status"]["switch_1"] is True


def test_raw_commands(client, owner_headers):
    ac = _sync(client, owner_headers)["แอร์ห้องนอน"]
    r = client.post(
        f"/devices/{ac['id']}/commands",
        json={"commands": [{"code": "switch", "value": True}, {"code": "temp_set", "value": 23}]},
        headers=owner_headers,
    )
    assert r.status_code == 200
    assert r.json()["status"] == {"switch": True, "temp_set": 23, "mode": "cold"}


def test_unsupported_command_is_502(client, owner_headers):
    light = _sync(client, owner_headers)["ไฟห้องนั่งเล่น"]
    r = client.post(
        f"/devices/{light['id']}/commands",
        json={"commands": [{"code": "temp_set", "value": 20}]},
        headers=owner_headers,
    )
    assert r.status_code == 502


def test_rename_and_unknown_device(client, owner_headers):
    light = _sync(client, owner_headers)["ไฟห้องนั่งเล่น"]
    r = client.patch(f"/devices/{light['id']}", json={"room": "โถง"}, headers=owner_headers)
    assert r.json()["room"] == "โถง"
    assert client.get("/devices/999", headers=owner_headers).status_code == 404


def test_scenes(client, owner_headers):
    light = _sync(client, owner_headers)["ไฟห้องนั่งเล่น"]
    scenes = {s["name"]: s["scene_id"] for s in client.get("/scenes", headers=owner_headers).json()}
    assert client.post(f"/scenes/{scenes['กลับถึงบ้าน']}/trigger", headers=owner_headers).status_code == 204
    r = client.get(f"/devices/{light['id']}", params={"refresh": True}, headers=owner_headers)
    assert r.json()["status"]["switch_led"] is True
