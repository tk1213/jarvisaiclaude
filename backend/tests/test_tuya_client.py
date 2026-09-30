import hashlib
import hmac
import json
import time

import httpx
import pytest

from app.integrations.tuya.client import TuyaClient, TuyaError, TuyaToken, canonical_url, sign_request

ID, SECRET = "test-id", "test-secret"


def expected_sign(method, url, body, t, token=""):
    sts = f"{method}\n{hashlib.sha256(body).hexdigest()}\n\n{url}"
    return hmac.new(SECRET.encode(), (ID + token + t + sts).encode(), hashlib.sha256).hexdigest().upper()


def test_canonical_url_sorts_query():
    assert canonical_url("/v1.0/x", {"b": 2, "a": "h i"}) == "/v1.0/x?a=h%20i&b=2"
    assert canonical_url("/v1.0/x") == "/v1.0/x"


def test_sign_request_matches_spec_format():
    sign = sign_request(
        access_id=ID, access_secret=SECRET, method="get", url="/v1.0/token?grant_type=1", body=b"", t="1588925778000"
    )
    assert sign == expected_sign("GET", "/v1.0/token?grant_type=1", b"", "1588925778000")


class FakeTuya:
    """Minimal fake of Tuya's HTTP API that verifies every signature."""

    def __init__(self):
        self.tokens_issued = 0
        self.valid_token = None
        self.expire_next_business_call = False
        self.commands = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = request.url.raw_path.decode()
        token = request.headers.get("access_token", "")
        body = request.content or b""
        assert request.headers["sign"] == expected_sign(request.method, url, body, request.headers["t"], token)

        if url.startswith("/v1.0/token"):
            self.tokens_issued += 1
            self.valid_token = f"tok{self.tokens_issued}"
            result = {"access_token": self.valid_token, "refresh_token": "ref", "expire_time": 7200, "uid": "u"}
            return httpx.Response(200, json={"success": True, "result": result})

        if token != self.valid_token or self.expire_next_business_call:
            self.expire_next_business_call = False
            return httpx.Response(200, json={"success": False, "code": 1010, "msg": "token invalid"})
        if url.endswith("/commands"):
            self.commands.append(json.loads(body))
            return httpx.Response(200, json={"success": True, "result": True})
        if url == "/v1.0/users/app-uid/devices":
            return httpx.Response(200, json={"success": True, "result": [{"id": "d1", "name": "Lamp"}]})
        return httpx.Response(200, json={"success": False, "code": 1108, "msg": "uri path invalid"})


class MemoryStore:
    def __init__(self):
        self.token = None

    def load(self):
        return self.token

    def save(self, token):
        self.token = token


@pytest.fixture
def fake():
    return FakeTuya()


def make_client(fake, store=None):
    return TuyaClient(
        endpoint="https://tuya.test",
        access_id=ID,
        access_secret=SECRET,
        user_uid="app-uid",
        token_store=store,
        http=httpx.Client(transport=httpx.MockTransport(fake)),
    )


def test_fetches_token_then_calls_api(fake):
    store = MemoryStore()
    client = make_client(fake, store)
    assert client.list_devices() == [{"id": "d1", "name": "Lamp"}]
    assert client.list_devices()
    assert fake.tokens_issued == 1
    assert store.token.access_token == "tok1"


def test_send_commands_signs_body(fake):
    client = make_client(fake)
    assert client.send_commands("d1", [{"code": "switch_led", "value": True}])
    assert fake.commands == [{"commands": [{"code": "switch_led", "value": True}]}]


def test_retries_once_on_invalid_token(fake):
    client = make_client(fake)
    client.list_devices()
    fake.expire_next_business_call = True
    assert client.list_devices()
    assert fake.tokens_issued == 2


def test_reuses_persisted_token(fake):
    fake.valid_token = "saved"
    store = MemoryStore()
    store.token = TuyaToken(access_token="saved", refresh_token="r", expires_at=time.time() + 3600)
    make_client(fake, store).list_devices()
    assert fake.tokens_issued == 0


def test_refreshes_expired_token(fake):
    store = MemoryStore()
    store.token = TuyaToken(access_token="old", refresh_token="r", expires_at=time.time() - 1)
    make_client(fake, store).list_devices()
    assert fake.tokens_issued == 1
    assert store.token.access_token == "tok1"


def test_api_error_raises(fake):
    client = make_client(fake)
    with pytest.raises(TuyaError) as e:
        client.get_device_status("d1")
    assert e.value.code == 1108
