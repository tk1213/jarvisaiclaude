def _sync(client, headers):
    return {d["name"]: d for d in client.post("/devices/sync", headers=headers).json()}


def test_sync_links_ir_remote_to_hub(client, owner_headers):
    devices = _sync(client, owner_headers)
    assert devices["แอร์ห้องทำงาน"]["ir_hub_id"] == "mock-ir-hub"
    assert devices["รีโมท IR ห้องทำงาน"]["ir_hub_id"] is None


def test_set_ac_settings(client, owner_headers):
    ac = _sync(client, owner_headers)["แอร์ห้องทำงาน"]
    r = client.post(f"/devices/{ac['id']}/ac", json={"temp": 24, "mode": "cool", "fan": "high"}, headers=owner_headers)
    assert r.status_code == 200
    # Changing a setting also turns it on, like a real remote.
    assert r.json()["status"] | {} == {"switch_power": True, "mode": 0, "temperature": 24, "fan": 3}

    r = client.post(f"/devices/{ac['id']}/ac", json={"power": False}, headers=owner_headers)
    assert r.json()["status"]["switch_power"] is False
    assert r.json()["status"]["temperature"] == 24  # unchanged settings are kept


def test_power_endpoint_routes_to_ir(client, owner_headers):
    ac = _sync(client, owner_headers)["แอร์ห้องทำงาน"]
    r = client.post(f"/devices/{ac['id']}/power", json={"on": True}, headers=owner_headers)
    assert r.status_code == 200 and r.json()["status"]["switch_power"] is True


def test_ac_validation(client, owner_headers):
    devices = _sync(client, owner_headers)
    ac, plug = devices["แอร์ห้องทำงาน"], devices["ปลั๊กกาต้มน้ำ"]
    assert client.post(f"/devices/{ac['id']}/ac", json={"temp": 40}, headers=owner_headers).status_code == 422
    assert client.post(f"/devices/{ac['id']}/ac", json={"mode": "turbo"}, headers=owner_headers).status_code == 422
    assert client.post(f"/devices/{plug['id']}/ac", json={"power": True}, headers=owner_headers).status_code == 422


def test_unlinked_remote_gives_clear_error(client, owner_headers):
    from app.db import SessionLocal
    from app.models import Device

    ac = _sync(client, owner_headers)["แอร์ห้องทำงาน"]
    with SessionLocal() as db:
        db.get(Device, ac["id"]).ir_hub_id = None
        db.commit()
    r = client.post(f"/devices/{ac['id']}/ac", json={"power": True}, headers=owner_headers)
    assert r.status_code == 422 and "sync" in r.json()["detail"]


def test_jarvis_tool_controls_ac(client, owner_headers):
    import json

    from app.core.tools import ToolContext, run_tool
    from app.db import SessionLocal
    from app.integrations.tuya import get_tuya_client
    from app.models import User

    ac = _sync(client, owner_headers)["แอร์ห้องทำงาน"]
    with SessionLocal() as db:
        ctx = ToolContext(db, get_tuya_client(), db.query(User).first())
        args = {"device_id": ac["id"], "power": None, "mode": None, "temperature": 26, "fan": None}
        content, is_error = run_tool(ctx, "control_air_conditioner", args)
        assert not is_error
        assert json.loads(content)["status"]["temperature"] == 26

        # control_device refuses IR ACs and points Claude to the right tool.
        content, is_error = run_tool(ctx, "control_device", {"device_id": ac["id"], "commands": [{"code": "mode", "value": 1}]})
        assert is_error and "control_air_conditioner" in content


def test_changes_made_in_tuya_app_are_picked_up(client, owner_headers):
    from app.db import SessionLocal
    from app.integrations.tuya import get_tuya_client
    from app.services.devices import refresh_ir_acs

    ac = _sync(client, owner_headers)["แอร์ห้องทำงาน"]
    tuya = get_tuya_client()
    # Someone turns the AC on from the Tuya app: only the IR API knows.
    tuya.ir_ac_set("mock-ir-hub", "mock-ir-ac", power=1, mode=4, temp=27, wind=2)
    with SessionLocal() as db:
        changed = refresh_ir_acs(db, tuya)
        assert [d.id for d in changed] == [ac["id"]]
        assert refresh_ir_acs(db, tuya) == []  # nothing new on the next poll
    status = client.get(f"/devices/{ac['id']}", headers=owner_headers).json()["status"]
    assert (status["switch_power"], status["mode"], status["temperature"], status["fan"]) == (True, 4, 27, 2)
