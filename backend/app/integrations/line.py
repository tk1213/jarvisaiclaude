"""LINE Messaging API: webhook signature check, reply/push, and the Flex bubble JARVIS answers with."""

import base64
import hashlib
import hmac
import logging
from functools import lru_cache
from urllib.parse import quote, urlparse

import httpx

from app.config import get_settings
from app.models import Device
from app.services import devices as svc

log = logging.getLogger(__name__)

API = "https://api.line.me/v2/bot"
# Pictures and files users send are downloaded from a different host.
DATA_API = "https://api-data.line.me/v2/bot"
# LINE rejects text over 5,000 characters; Flex text is shown in full, so keep replies well under it.
MAX_TEXT = 4000
# The only quick-reply buttons: under a document summary that waits for the owner's answer.
CONFIRM_CHOICES = ["OK", "Cancel"]
# A quotation drafted with VAT also offers dropping it (the other documents follow their quotation's VAT).
NO_VAT = "ไม่เอาแวท"


def confirm_choices(tool_calls) -> list[str] | None:
    """The buttons for a reply: OK / Cancel (+ ไม่เอาแวท for a quotation with VAT) after a draft, otherwise none."""
    drafts = [c for c in tool_calls if c.ok and c.name == "prepare_document"]
    if not drafts:
        return None
    last = drafts[-1].input
    return CONFIRM_CHOICES + [NO_VAT] if last.get("doc_type") == "quotation" and last.get("vat") else CONFIRM_CHOICES


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
        try:
            r = self.http.post(path, json=payload)
        except httpx.HTTPError as e:
            raise LineError(f"LINE {path}: {e.__class__.__name__} {e}") from None
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

    def get_content(self, message_id: str) -> bytes:
        """The picture (or file) a user sent; LINE keeps it only for a while after the message."""
        url = f"{DATA_API}/message/{message_id}/content"
        try:
            r = self.http.get(url, timeout=30)
        except httpx.HTTPError as e:
            raise LineError(f"LINE content: {e.__class__.__name__} {e}") from None
        if r.status_code >= 400:
            raise LineError(f"LINE content {r.status_code}: {r.text[:300]}")
        return r.content

    def group_name(self, group_id: str) -> str:
        """A LINE group's name (the bot must be in the group)."""
        try:
            r = self.http.get(f"/group/{group_id}/summary")
        except httpx.HTTPError as e:
            raise LineError(f"LINE group summary: {e.__class__.__name__} {e}") from None
        if r.status_code >= 400:
            raise LineError(f"LINE group summary {r.status_code}: {r.text[:300]}")
        return r.json().get("groupName") or ""

    def show_loading(self, chat_id: str, seconds: int = 20) -> None:
        """The "..." typing animation while JARVIS thinks; purely cosmetic, so failures are ignored."""
        try:
            self._post("/chat/loading/start", {"chatId": chat_id, "loadingSeconds": seconds})
        except (LineError, httpx.HTTPError) as e:
            log.info("LINE loading animation not shown: %s", e)


@lru_cache
def _client_for(access_token: str) -> LineClient:
    return LineClient(access_token)


def get_line_client() -> LineClient:
    return _client_for(get_settings().line_channel_access_token)


def line_configured() -> bool:
    s = get_settings()
    return bool(s.line_channel_secret and s.line_channel_access_token)


def maps_link(query: str) -> str:
    return f"https://www.google.com/maps/search/?api=1&query={quote(query)}"


def _https(url: str | None) -> bool:
    return bool(url) and urlparse(url).scheme == "https" and bool(urlparse(url).netloc)


def info_messages(text: str, links: list[dict] | None = None, location: dict | None = None, image_url: str | None = None) -> list[dict]:
    """What JARVIS pushes to LINE on request: a text with its links, a Google Maps link, and/or a picture."""
    body = text.strip()
    for link in links or []:
        if _https(link.get("url")):
            body += f"\n\n{link.get('label') or 'ลิงก์'}: {link['url']}"
    messages = [{"type": "text", "text": body[:MAX_TEXT]}] if body else []
    if location:
        # Always a Google Maps link (the owner's choice): it opens straight in Google Maps for directions.
        lat, lng = location.get("latitude"), location.get("longitude")
        title = (location.get("title") or "ตำแหน่ง")[:100]
        address = (location.get("address") or "").strip()
        if lat is not None and lng is not None and -90 <= lat <= 90 and -180 <= lng <= 180:
            query = f"{lat},{lng}"
        else:  # no reliable coordinates: search by name and address
            query = f"{title} {address}".strip()
        lines = [f"📍 {title}", address if address and address != title else "", maps_link(query)]
        messages.append({"type": "text", "text": "\n".join(line for line in lines if line)})
    if _https(image_url):
        messages.append({"type": "image", "originalContentUrl": image_url, "previewImageUrl": image_url})
    if not messages:
        raise LineError("nothing to send")
    return messages[:5]


def _quick_reply(choices: list[str]) -> dict:
    return {"items": [{"type": "action", "action": {"type": "message", "label": t, "text": t}} for t in choices]}


def text_message(text: str, choices: list[str] | None = None) -> dict:
    """A text bubble; `choices` become tap-to-send buttons under it (otherwise there are none)."""
    message = {"type": "text", "text": text[:MAX_TEXT]}
    if choices:
        message["quickReply"] = _quick_reply(choices)
    return message


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


def reply_message(text: str, devices: list[Device], choices: list[str] | None = None) -> dict:
    """Plain text for a plain answer; a Flex bubble listing the devices when JARVIS just changed some."""
    if not devices:
        return text_message(text, choices)
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
    message = {"type": "flex", "altText": text[:400], "contents": bubble}
    if choices:
        message["quickReply"] = _quick_reply(choices)
    return message
