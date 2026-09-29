import asyncio
import base64
import json
import os

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from websockets.asyncio.server import serve

from app.db import SessionLocal
from app.integrations.tuya.mock import MockTuyaClient
from app.integrations.tuya.pulsar import (
    PulsarConsumer,
    decode_message,
    default_ws_endpoint,
    pulsar_password,
    pulsar_url,
)
from app.services.devices import apply_device_event, sync_devices

ACCESS_ID, SECRET = "myaccessid", "0123456789abcdef0123456789abcdef"


def encrypt_ecb(event: dict) -> str:
    padder = padding.PKCS7(128).padder()
    data = padder.update(json.dumps(event).encode()) + padder.finalize()
    enc = Cipher(algorithms.AES(SECRET[8:24].encode()), modes.ECB()).encryptor()
    return base64.b64encode(enc.update(data) + enc.finalize()).decode()


def encrypt_gcm(event: dict) -> str:
    nonce = os.urandom(12)
    ct = AESGCM(SECRET[8:24].encode()).encrypt(nonce, json.dumps(event).encode(), None)
    return base64.b64encode(nonce + ct).decode()


def frame(message_id: str, event: dict, em: str = "") -> str:
    data = encrypt_gcm(event) if em == "aes_gcm" else encrypt_ecb(event)
    payload = base64.b64encode(json.dumps({"data": data, "protocol": 4, "pv": "2.0"}).encode()).decode()
    return json.dumps({"messageId": message_id, "payload": payload, "properties": {"em": em} if em else {}})


STATUS_EVENT = {"devId": "mock-light-living", "status": [{"code": "switch_led", "value": True, "t": 1}]}


def test_endpoints_and_password():
    assert default_ws_endpoint("https://openapi.tuyaus.com") == "wss://mqe.tuyaus.com:8285/"
    url = pulsar_url("wss://mqe.tuyaus.com:8285/", "abc", "event")
    assert url == (
        "wss://mqe.tuyaus.com:8285/ws/v2/consumer/persistent/abc/out/event/abc-sub"
        "?ackTimeoutMillis=3000&subscriptionType=Failover"
    )
    assert len(pulsar_password(ACCESS_ID, SECRET)) == 16


def test_decode_ecb_and_gcm():
    assert decode_message(frame("m1", STATUS_EVENT), SECRET) == ("m1", STATUS_EVENT)
    assert decode_message(frame("m2", STATUS_EVENT, "aes_gcm"), SECRET) == ("m2", STATUS_EVENT)


def test_apply_events_updates_device():
    with SessionLocal() as db:
        sync_devices(db, MockTuyaClient())
        device = apply_device_event(db, STATUS_EVENT)
        assert device.status == {"switch_led": True, "bright_value_v2": 800}

        apply_device_event(db, {"devId": "mock-light-living", "bizCode": "offline"})
        assert device.online is False
        assert apply_device_event(db, {"devId": "unknown", "status": []}) is None

    with SessionLocal() as db:  # persisted, not just in the session
        from app.models import Device

        stored = db.query(Device).filter_by(tuya_device_id="mock-light-living").one()
        assert stored.status["switch_led"] is True and stored.online is False


def test_consumer_authenticates_handles_and_acks():
    received, acks, headers = [], [], {}

    async def scenario():
        done = asyncio.Event()

        async def handler(ws):
            headers.update(ws.request.headers)
            await ws.send(frame("m1", STATUS_EVENT))
            await ws.send(json.dumps({"messageId": "bad", "payload": "not-base64!"}))
            await ws.send(frame("m2", {"devId": "x", "bizCode": "online"}, "aes_gcm"))
            async for msg in ws:
                acks.append(json.loads(msg)["messageId"])
                if len(acks) == 3:
                    done.set()

        async with serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            consumer = PulsarConsumer(
                url=f"ws://127.0.0.1:{port}/", access_id=ACCESS_ID, access_secret=SECRET, on_event=received.append
            )
            task = asyncio.create_task(consumer.run())
            await asyncio.wait_for(done.wait(), timeout=5)
            task.cancel()

    asyncio.run(scenario())
    assert headers["username"] == ACCESS_ID
    assert headers["password"] == pulsar_password(ACCESS_ID, SECRET)
    assert received == [STATUS_EVENT, {"devId": "x", "bizCode": "online"}]
    assert acks == ["m1", "bad", "m2"]  # a broken message is still acked


def test_consumer_only_built_in_live_mode(monkeypatch):
    from app.config import get_settings
    from app.integrations.tuya import build_pulsar_consumer

    assert build_pulsar_consumer() is None  # tests run in mock mode

    monkeypatch.setenv("TUYA_MODE", "live")
    monkeypatch.setenv("TUYA_ACCESS_ID", ACCESS_ID)
    monkeypatch.setenv("TUYA_ACCESS_SECRET", SECRET)
    monkeypatch.setenv("TUYA_ENDPOINT", "https://openapi.tuyaeu.com")
    get_settings.cache_clear()
    try:
        consumer = build_pulsar_consumer()
        assert consumer.url.startswith(f"wss://mqe.tuyaeu.com:8285/ws/v2/consumer/persistent/{ACCESS_ID}/out/event/")

        monkeypatch.setenv("TUYA_PULSAR_ENABLED", "false")
        get_settings.cache_clear()
        assert build_pulsar_consumer() is None
    finally:
        get_settings.cache_clear()
