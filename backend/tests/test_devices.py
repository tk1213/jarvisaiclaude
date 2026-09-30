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
    assert len(client.get("/devices", headers=owner_headers).json()) == 5


def test_sync_removes_devices_gone_from_tuya(client, owner_headers):
    from app.db import SessionLocal
    from app.models import Device

    with SessionLocal() as db:
        db.add(Device(tuya_device_id="stale", name="old device"))
        db.commit()
    names = set(_sync(client, owner_headers))
    assert "old device" not in names
    assert len(client.get("/devices", headers=owner_headers).json()) == 5


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


def test_control_reports_commanded_state_before_device_catches_up(client, owner_headers):
    """Tuya's status endpoint can lag behind an accepted command."""
    from app.integrations.tuya import get_tuya_client

    tuya = get_tuya_client()
    plug = _sync(client, owner_headers)["ปลั๊กกาต้มน้ำ"]
    stale = tuya.get_device_status("mock-plug-kitchen")
    tuya.get_device_status = lambda device_id: stale  # cloud hasn't caught up

    r = client.post(f"/devices/{plug['id']}/power", json={"on": True}, headers=owner_headers)
    assert r.json()["status"]["switch_1"] is True


def test_rename_and_room_survive_sync(client, owner_headers):
    light = _sync(client, owner_headers)["ไฟห้องนั่งเล่น"]
    r = client.patch(f"/devices/{light['id']}", json={"name": "โคมไฟโซฟา", "room": "  ห้องรับแขก "}, headers=owner_headers)
    assert r.status_code == 200
    assert (r.json()["name"], r.json()["room"]) == ("โคมไฟโซฟา", "ห้องรับแขก")

    after = _sync(client, owner_headers)
    assert "โคมไฟโซฟา" in after and "ไฟห้องนั่งเล่น" not in after
    assert after["โคมไฟโซฟา"]["room"] == "ห้องรับแขก"

    # Clearing the room also sticks.
    client.patch(f"/devices/{light['id']}", json={"room": ""}, headers=owner_headers)
    assert _sync(client, owner_headers)["โคมไฟโซฟา"]["room"] is None


def test_blank_name_rejected(client, owner_headers):
    light = _sync(client, owner_headers)["ไฟห้องนั่งเล่น"]
    assert client.patch(f"/devices/{light['id']}", json={"name": "   "}, headers=owner_headers).status_code == 422
    assert client.patch(f"/devices/{light['id']}", json={"name": ""}, headers=owner_headers).status_code == 422


def test_permission_denied_is_flagged_then_cleared(client, owner_headers):
    from app.integrations.tuya import TuyaError, get_tuya_client

    plug = _sync(client, owner_headers)["ปลั๊กกาต้มน้ำ"]
    tuya = get_tuya_client()
    real_send = tuya.send_commands

    def denied(device_id, commands):
        raise TuyaError(1106, "permission deny")

    tuya.send_commands = denied
    r = client.post(f"/devices/{plug['id']}/power", json={"on": True}, headers=owner_headers)
    assert r.status_code == 502
    assert client.get(f"/devices/{plug['id']}", headers=owner_headers).json()["control_denied"] is True

    tuya.send_commands = real_send  # permission fixed in the Tuya console
    r = client.post(f"/devices/{plug['id']}/power", json={"on": True}, headers=owner_headers)
    assert r.status_code == 200 and r.json()["control_denied"] is False


def test_sensor_readings_survive_sync_when_listing_is_empty(client, owner_headers):
    """IR hubs list no status; readings come from Pulsar or the shadow endpoint and must not be wiped."""
    from app.integrations.tuya import get_tuya_client

    tuya = get_tuya_client()
    ac = _sync(client, owner_headers)["แอร์ห้องนอน"]
    real_list = tuya.list_devices

    def listing_without_status():
        return [{**d, "status": []} for d in real_list()]

    tuya.list_devices = listing_without_status
    tuya.get_shadow_properties = lambda device_id: [{"code": "temp_current", "value": 287}]
    after = _sync(client, owner_headers)["แอร์ห้องนอน"]
    assert after["status"]["temp_current"] == 287  # from shadow properties
    assert after["status"]["temp_set"] == ac["status"]["temp_set"]  # earlier value kept
