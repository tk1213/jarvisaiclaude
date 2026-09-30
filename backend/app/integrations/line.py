"""LINE Messaging API: webhook signature check, reply/push, and the Flex bubble JARVIS answers with."""

import base64
import hashlib
import hmac
import logging

import httpx

from app.models import Device
from app.services import devices as svc

log = logging.getLogger(__name__)

API = "https://api.line.me/v2/bot"
# LINE rejects text over 5,000 characters; Flex text is shown in full, so keep replies well under it.
MAX_TEXT = 4000
# Quick replies under every answer, for the commands used most from a phone.
QUICK_REPLIES = ["สถานะบ้าน", "ปิดทุกอย่าง", "อุณหภูมิตอนนี้"]


class LineError(RuntimeError):
    pass


def valid_signature(channel_secret: str, body: bytes, signature: str) -> bool:
    """X-Line-Signature is base64(HMAC-SHA256(channel secret, raw body))."""
    if not channel_secret or not signature:
        return False
    digest = hmac.new(channel_secret.encode(), body, hashlib.sha256).digest()
    return hmac.compare_digest(base64.b64encode(digest).decode(), signature)


class LineClient:
    def __init__(self, access_token: str, http: httpx.Client | None = None):
        self.http = http or httpx.Client(base_url=API, timeout=10, headers={"Authorization": f"Bearer {access_token}"})

    def _post(self, path: str, payload: dict) -> None:
        r = self.http.post(path, json=payload)
        if r.status_code >= 400:
            raise LineError(f"LINE {path} {r.status_code}: {r.text[:300]}")

    def reply(self, reply_token: str, messages: list[dict]) -> None:
        self._post("/message/reply", {"replyToken": reply_token, "messages": messages})

    def push(self, to: str, messages: list[dict]) -> None:
        self._post("/message/push", {"to": to, "messages": messages})

    def send(self, reply_token: str, to: str, messages: list[dict]) -> None:
        """Reply (free), or push when the reply token has expired (a slow answer)."""
        try:
            self.reply(reply_token, messages)
        except LineError as e:
            log.warning("LINE reply failed, pushing instead: %s", e)
            self.push(to, messages)

    def show_loading(self, chat_id: str, seconds: int = 20) -> None:
        """The "..." typing animation while JARVIS thinks; purely cosmetic, so failures are ignored."""
        try:
            self._post("/chat/loading/start", {"chatId": chat_id, "loadingSeconds": seconds})
        except (LineError, httpx.HTTPError) as e:
            log.info("LINE loading animation not shown: %s", e)


def _quick_reply() -> dict:
    return {"items": [{"type": "action", "action": {"type": "message", "label": t, "text": t}} for t in QUICK_REPLIES]}


def text_message(text: str) -> dict:
    return {"type": "text", "text": text[:MAX_TEXT], "quickReply": _quick_reply()}


def power_state(device: Device) -> str:
    """"เปิด" / "ปิด" for a device with a power switch, "" when it has none."""
    status = device.status or {}
    if device.category == svc.IR_AC_CATEGORY:
        value = status.get("switch_power")
    else:
        try:
            value = status.get(svc.power_code(device))
        except ValueError:
            return ""
    if value is None:
        return ""
    return "เปิด" if value in (True, 1, "1", "true") else "ปิด"


def reply_message(text: str, devices: list[Device]) -> dict:
    """Plain text for a plain answer; a Flex bubble listing the devices when JARVIS just changed some."""
    if not devices:
        return text_message(text)
    rows = []
    for d in devices:
        state = power_state(d) or ("ออนไลน์" if d.online else "ออฟไลน์")
        rows.append(
            {
                "type": "box",
                "layout": "horizontal",
                "contents": [
                    {"type": "text", "text": d.name, "size": "sm", "color": "#334155", "flex": 3, "wrap": True},
                    {
                        "type": "text",
                        "text": state,
                        "size": "sm",
                        "weight": "bold",
                        "align": "end",
                        "flex": 1,
                        "color": "#059669" if state == "เปิด" else "#64748b",
                    },
                ],
            }
        )
    bubble = {
        "type": "bubble",
        "size": "kilo",
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "contents": [
                {"type": "text", "text": "จาร์วิส", "weight": "bold", "size": "xs", "color": "#0284c7"},
                {"type": "text", "text": text[:MAX_TEXT], "wrap": True, "size": "md", "color": "#0f172a"},
                {"type": "separator"},
                {"type": "box", "layout": "vertical", "spacing": "sm", "contents": rows},
            ],
        },
    }
    return {"type": "flex", "altText": text[:400], "contents": bubble, "quickReply": _quick_reply()}
