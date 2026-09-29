"""Tuya Pulsar message service consumer (spec §4.2).

Tuya pushes device status reports and online/offline events over a Pulsar
WebSocket, so JARVIS stays in sync without polling the OpenAPI.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
from collections.abc import Callable
from urllib.parse import urlparse

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from websockets.asyncio.client import connect

log = logging.getLogger(__name__)


def default_ws_endpoint(openapi_endpoint: str) -> str:
    """https://openapi.tuyaus.com -> wss://mqe.tuyaus.com:8285/"""
    host = urlparse(openapi_endpoint).hostname or ""
    return f"wss://mqe.{host.removeprefix('openapi.')}:8285/"


def pulsar_url(ws_endpoint: str, access_id: str, env: str) -> str:
    return (
        f"{ws_endpoint.rstrip('/')}/ws/v2/consumer/persistent/{access_id}/out/{env}/"
        f"{access_id}-sub?ackTimeoutMillis=3000&subscriptionType=Failover"
    )


def pulsar_password(access_id: str, access_secret: str) -> str:
    inner = hashlib.md5(access_secret.encode()).hexdigest()
    return hashlib.md5((access_id + inner).encode()).hexdigest()[8:24]


def _decrypt(data: str, access_secret: str, mode: str) -> bytes:
    key = access_secret[8:24].encode()
    raw = base64.b64decode(data)
    if mode == "aes_gcm":
        return AESGCM(key).decrypt(raw[:12], raw[12:], None)
    decryptor = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
    plain = decryptor.update(raw) + decryptor.finalize()
    pad = plain[-1] if plain else 0
    return plain[:-pad] if 0 < pad <= 16 and plain.endswith(bytes([pad]) * pad) else plain


def decode_message(message: str, access_secret: str) -> tuple[str, dict]:
    """Return (message_id, decrypted event) from one raw Pulsar frame."""
    frame = json.loads(message)
    payload = json.loads(base64.b64decode(frame["payload"]))
    mode = (frame.get("properties") or {}).get("em", "")
    event = json.loads(_decrypt(payload["data"], access_secret, mode))
    return frame["messageId"], event


class PulsarConsumer:
    def __init__(
        self,
        *,
        url: str,
        access_id: str,
        access_secret: str,
        on_event: Callable[[dict], object],
        max_backoff: float = 60,
    ):
        self.url = url
        self.access_id = access_id
        self.access_secret = access_secret
        self.on_event = on_event
        self.max_backoff = max_backoff

    async def _consume(self, ws) -> None:
        async for message in ws:
            message_id = None
            try:
                message_id, event = decode_message(message, self.access_secret)
                await asyncio.to_thread(self.on_event, event)
            except Exception:
                log.exception("failed to handle Tuya Pulsar message")
            finally:
                # Ack even on failure so one bad message can't block the subscription.
                if message_id is None:
                    try:
                        message_id = json.loads(message)["messageId"]
                    except Exception:
                        pass
                if message_id is not None:
                    await ws.send(json.dumps({"messageId": message_id}))

    async def run(self) -> None:
        headers = {"username": self.access_id, "password": pulsar_password(self.access_id, self.access_secret)}
        backoff = 1.0
        while True:
            try:
                async with connect(self.url, additional_headers=headers, ping_interval=30) as ws:
                    log.info("connected to Tuya Pulsar")
                    backoff = 1.0
                    await self._consume(ws)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("Tuya Pulsar connection lost (%s); retrying in %.0fs", e, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, self.max_backoff)
