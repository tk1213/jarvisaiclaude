import pytest
from starlette.websockets import WebSocketDisconnect


def _token(headers):
    return headers["Authorization"].split()[1]


def test_rejects_missing_or_bad_token(client):
    for url in ("/ws/devices", "/ws/devices?token=garbage"):
        with pytest.raises(WebSocketDisconnect) as e:
            with client.websocket_connect(url) as ws:
                ws.receive_json()
        assert e.value.code == 4401


def test_pushes_device_changes(client, owner_headers):
    client.post("/devices/sync", headers=owner_headers)
    with client.websocket_connect(f"/ws/devices?token={_token(owner_headers)}") as ws:
        r = client.post("/devices/1/power", json={"on": True}, headers=owner_headers)
        assert r.status_code == 200
        event = ws.receive_json()
        assert event["type"] == "device"
        assert event["device"]["id"] == 1
        assert event["device"]["status"]["switch_led"] is True


def test_pushes_pulsar_events_and_removals(client, owner_headers):
    from app.db import SessionLocal
    from app.models import Device
    from app.services.devices import apply_device_event

    client.post("/devices/sync", headers=owner_headers)
    with client.websocket_connect(f"/ws/devices?token={_token(owner_headers)}") as ws:
        with SessionLocal() as db:  # what the Pulsar consumer does on its worker thread
            apply_device_event(db, {"devId": "mock-plug-kitchen", "bizCode": "offline"})
        event = ws.receive_json()
        assert event["device"]["name"] == "ปลั๊กกาต้มน้ำ" and event["device"]["online"] is False

        with SessionLocal() as db:
            db.delete(db.query(Device).filter_by(tuya_device_id="mock-plug-kitchen").one())
            db.commit()
        assert ws.receive_json()["type"] == "device_removed"
