"""Tuya Cloud OpenAPI client (spec §4.2).

Implements Tuya's HMAC-SHA256 request signing, token acquisition/refresh and
the handful of endpoints JARVIS needs: list devices, read status, send
commands, list and trigger scenes.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote

import httpx

# Tuya response codes that mean "your access token is no longer valid".
_TOKEN_INVALID_CODES = {1010, 1011}


class TuyaError(RuntimeError):
    def __init__(self, code: Any, msg: str):
        super().__init__(f"Tuya API error {code}: {msg}")
        self.code = code
        self.msg = msg


@dataclass
class TuyaToken:
    access_token: str
    refresh_token: str
    expires_at: float  # unix seconds
    uid: str = ""

    def is_expired(self, skew: float = 60) -> bool:
        return time.time() >= self.expires_at - skew

    def to_json(self) -> str:
        return json.dumps(self.__dict__)

    @classmethod
    def from_json(cls, raw: str) -> TuyaToken:
        return cls(**json.loads(raw))


class TokenStore(Protocol):
    def load(self) -> TuyaToken | None: ...
    def save(self, token: TuyaToken) -> None: ...


def canonical_url(path: str, params: dict[str, Any] | None = None) -> str:
    """Path plus query sorted by key, exactly as Tuya expects it in the signature."""
    if not params:
        return path
    query = "&".join(f"{k}={quote(str(params[k]), safe='')}" for k in sorted(params))
    return f"{path}?{query}"


def sign_request(
    *,
    access_id: str,
    access_secret: str,
    method: str,
    url: str,
    body: bytes,
    t: str,
    access_token: str = "",
    nonce: str = "",
) -> str:
    content_sha256 = hashlib.sha256(body).hexdigest()
    # No Signature-Headers are used, so the headers segment is empty.
    string_to_sign = "\n".join([method.upper(), content_sha256, "", url])
    message = access_id + access_token + t + nonce + string_to_sign
    return hmac.new(access_secret.encode(), message.encode(), hashlib.sha256).hexdigest().upper()


class TuyaClient:
    def __init__(
        self,
        *,
        endpoint: str,
        access_id: str,
        access_secret: str,
        user_uid: str,
        home_id: str = "",
        token_store: TokenStore | None = None,
        http: httpx.Client | None = None,
    ):
        if not (access_id and access_secret):
            raise ValueError("TUYA_ACCESS_ID and TUYA_ACCESS_SECRET are required in live mode")
        self.endpoint = endpoint.rstrip("/")
        self.access_id = access_id
        self.access_secret = access_secret
        self.user_uid = user_uid
        self.home_id = home_id
        self._store = token_store
        self._http = http or httpx.Client(timeout=10)
        self._token: TuyaToken | None = None
        self._lock = threading.Lock()

    # ---- low level -------------------------------------------------------

    def _send(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: Any = None,
        access_token: str = "",
    ) -> dict:
        url = canonical_url(path, params)
        body = json.dumps(payload, separators=(",", ":")).encode() if payload is not None else b""
        t = str(int(time.time() * 1000))
        headers = {
            "client_id": self.access_id,
            "t": t,
            "sign_method": "HMAC-SHA256",
            "sign": sign_request(
                access_id=self.access_id,
                access_secret=self.access_secret,
                method=method,
                url=url,
                body=body,
                t=t,
                access_token=access_token,
            ),
        }
        if access_token:
            headers["access_token"] = access_token
        if body:
            headers["Content-Type"] = "application/json"
        resp = self._http.request(method, self.endpoint + url, content=body or None, headers=headers)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _result(data: dict) -> Any:
        if not data.get("success"):
            raise TuyaError(data.get("code"), data.get("msg", "unknown error"))
        return data.get("result")

    def _store_token(self, result: dict) -> TuyaToken:
        token = TuyaToken(
            access_token=result["access_token"],
            refresh_token=result["refresh_token"],
            expires_at=time.time() + int(result["expire_time"]),
            uid=result.get("uid", ""),
        )
        self._token = token
        if self._store:
            self._store.save(token)
        return token

    def _fetch_new_token(self) -> TuyaToken:
        return self._store_token(self._result(self._send("GET", "/v1.0/token", params={"grant_type": 1})))

    def _refresh_token(self, token: TuyaToken) -> TuyaToken:
        try:
            return self._store_token(self._result(self._send("GET", f"/v1.0/token/{token.refresh_token}")))
        except TuyaError:
            return self._fetch_new_token()

    def _get_token(self, force_new: bool = False) -> TuyaToken:
        with self._lock:
            if self._token is None and self._store:
                self._token = self._store.load()
            if force_new or self._token is None:
                return self._fetch_new_token()
            if self._token.is_expired():
                return self._refresh_token(self._token)
            return self._token

    def request(self, method: str, path: str, *, params=None, payload=None) -> Any:
        token = self._get_token()
        data = self._send(method, path, params=params, payload=payload, access_token=token.access_token)
        if not data.get("success") and data.get("code") in _TOKEN_INVALID_CODES:
            token = self._get_token(force_new=True)
            data = self._send(method, path, params=params, payload=payload, access_token=token.access_token)
        return self._result(data)

    # ---- high level ------------------------------------------------------

    def _require_uid(self) -> str:
        if not self.user_uid:
            raise ValueError("TUYA_USER_UID is required (UID of the linked Tuya Smart app account)")
        return self.user_uid

    def list_devices(self) -> list[dict]:
        return self.request("GET", f"/v1.0/users/{self._require_uid()}/devices") or []

    def get_device_status(self, device_id: str) -> list[dict]:
        return self.request("GET", f"/v1.0/devices/{device_id}/status") or []

    def send_commands(self, device_id: str, commands: list[dict]) -> bool:
        return bool(self.request("POST", f"/v1.0/devices/{device_id}/commands", payload={"commands": commands}))

    def list_homes(self) -> list[dict]:
        return self.request("GET", f"/v1.0/users/{self._require_uid()}/homes") or []

    def _resolve_home_id(self) -> str:
        if not self.home_id:
            homes = self.list_homes()
            if not homes:
                raise TuyaError("no_home", "No Tuya home found for this user")
            self.home_id = str(homes[0]["home_id"])
        return self.home_id

    def list_rooms(self) -> list[dict]:
        result = self.request("GET", f"/v1.0/homes/{self._resolve_home_id()}/rooms") or {}
        return result.get("rooms", []) if isinstance(result, dict) else result

    def list_room_devices(self, room_id: str) -> list[dict]:
        return self.request("GET", f"/v1.0/homes/{self._resolve_home_id()}/rooms/{room_id}/devices") or []

    def list_scenes(self) -> list[dict]:
        return self.request("GET", f"/v1.0/homes/{self._resolve_home_id()}/scenes") or []

    def trigger_scene(self, scene_id: str) -> bool:
        return bool(self.request("POST", f"/v1.0/homes/{self._resolve_home_id()}/scenes/{scene_id}/trigger"))
