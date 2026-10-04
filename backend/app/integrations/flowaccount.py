"""FlowAccount Open API client (spec §4.3): OAuth2 client-credentials token + document creation."""

import itertools
import logging
import time
from dataclasses import dataclass
from functools import lru_cache

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

# JARVIS document type -> FlowAccount v1 path
DOC_PATHS = {
    "quotation": "/quotations",
    "billing_note": "/billing-notes",
    "tax_invoice": "/tax-invoices",
    "receipt": "/receipts",
}
# Documents read back for the Account page: sales tax invoices (incl. cash sales) and expenses.
INCOME_PATHS = ("/tax-invoices", "/cash-invoices")
EXPENSE_PATH = "/expenses"


class FlowAccountError(RuntimeError):
    pass


@dataclass
class IssuedDocument:
    record_id: str
    serial: str
    raw: dict


class DbTokenStore:
    """The access token, encrypted in the `tokens` table like Tuya's."""

    provider = "flowaccount"

    def load(self) -> tuple[str, float] | None:
        from app.db import SessionLocal
        from app.models import ProviderToken
        from app.security import decrypt

        with SessionLocal() as db:
            row = db.get(ProviderToken, self.provider)
            if not row or not row.expires_at:
                return None
            return decrypt(row.encrypted_value), row.expires_at.timestamp()

    def save(self, token: str, expires_at: float) -> None:
        from datetime import datetime, timezone

        from app.db import SessionLocal
        from app.models import ProviderToken
        from app.security import encrypt

        with SessionLocal() as db:
            row = db.get(ProviderToken, self.provider) or ProviderToken(provider=self.provider)
            row.encrypted_value = encrypt(token)
            row.expires_at = datetime.fromtimestamp(expires_at, tz=timezone.utc)
            db.add(row)
            db.commit()


class FlowAccountClient:
    def __init__(self, base_url: str, client_id: str, client_secret: str, scope: str, token_store=None, http: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.scope = scope
        self.token_store = token_store
        self.http = http or httpx.Client(timeout=30)
        self._token: tuple[str, float] | None = None

    def _send(self, url: str, **kwargs) -> httpx.Response:
        try:
            return self.http.post(url, **kwargs)
        except httpx.HTTPError as e:
            raise FlowAccountError(f"ติดต่อ FlowAccount ไม่ได้ ({e.__class__.__name__}: {e})") from None

    def _access_token(self, refresh: bool = False) -> str:
        if not refresh:
            if self._token is None and self.token_store:
                self._token = self.token_store.load()
            if self._token and self._token[1] - 60 > time.time():
                return self._token[0]
        r = self._send(
            f"{self.base_url}/token",
            data={"grant_type": "client_credentials", "scope": self.scope, "client_id": self.client_id, "client_secret": self.client_secret},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        body = _json(r)
        if r.status_code >= 400 or not body.get("access_token"):
            raise FlowAccountError(f"ขอ token จาก FlowAccount ไม่สำเร็จ ({r.status_code}): {body.get('error') or r.text[:200]}")
        self._token = (body["access_token"], time.time() + int(body.get("expires_in") or 3600))
        if self.token_store:
            self.token_store.save(*self._token)
        return self._token[0]

    def list_products(self) -> list[dict]:
        """Every product in the FlowAccount account (paged GET /products)."""
        return self._list("/products", "รายการสินค้า", page_size=100)

    def list_documents(self, path: str) -> list[dict]:
        """Every document of one kind, e.g. "/tax-invoices" or "/expenses" (FlowAccount allows 200 per page)."""
        return self._list(path, f"เอกสาร {path}", page_size=200)

    def _list(self, path: str, what: str, page_size: int) -> list[dict]:
        rows: list[dict] = []
        for page in range(1, 201):
            r = self._get(f"{self.base_url}{path}", params={"currentPage": page, "pageSize": page_size})
            body = _json(r)
            if r.status_code >= 400 or body.get("status") is False:
                raise FlowAccountError(f"ดึง{what}จาก FlowAccount ไม่ได้ ({r.status_code}): {body.get('message') or r.text[:300]}")
            data = body.get("data") or {}
            batch = data.get("list") or []
            rows += batch
            if not batch or len(rows) >= int(data.get("total") or 0):
                break
        return rows

    def _get(self, url: str, params: dict) -> httpx.Response:
        try:
            r = self.http.get(url, params=params, headers={"Authorization": f"Bearer {self._access_token()}"})
            if r.status_code == 401:
                r = self.http.get(url, params=params, headers={"Authorization": f"Bearer {self._access_token(refresh=True)}"})
            return r
        except httpx.HTTPError as e:
            raise FlowAccountError(f"ติดต่อ FlowAccount ไม่ได้ ({e.__class__.__name__}: {e})") from None

    def create_document(self, doc_type: str, payload: dict) -> IssuedDocument:
        path = DOC_PATHS[doc_type]
        r = self._send(f"{self.base_url}{path}", json=payload, headers={"Authorization": f"Bearer {self._access_token()}"})
        if r.status_code == 401:
            # Expired early or revoked (the stored copy too): one fresh token, one retry.
            r = self._send(f"{self.base_url}{path}", json=payload, headers={"Authorization": f"Bearer {self._access_token(refresh=True)}"})
        body = _json(r)
        if r.status_code >= 400 or body.get("status") is False:
            raise FlowAccountError(f"FlowAccount ไม่รับเอกสาร ({r.status_code}): {body.get('message') or r.text[:300]}")
        data = body.get("data") or {}
        return IssuedDocument(
            record_id=str(data.get("recordId") or data.get("documentId") or ""),
            serial=str(data.get("documentSerial") or ""),
            raw=data,
        )


def _json(r: httpx.Response) -> dict:
    try:
        body = r.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


class MockFlowAccountClient:
    """Pretends to issue documents: serials look real, nothing leaves the machine."""

    _counter = itertools.count(1)
    PREFIX = {"quotation": "QT", "billing_note": "BL", "tax_invoice": "IV", "receipt": "RE"}

    def list_products(self) -> list[dict]:
        return [
            {"id": "m1", "code": "DC-G100", "name": "โช๊คประตู GUTE ขนาด 1 เมตร", "unitName": "ตัว", "sellPrice": 1200, "sellVatType": 3, "type": 3},
            {"id": "m2", "code": "DC-G120", "name": "โช๊คประตู GUTE ขนาด 1.2 เมตร", "unitName": "ตัว", "sellPrice": 1400, "sellVatType": 3, "type": 3},
            {"id": "m3", "code": "DC-G150", "name": "โช๊คประตู GUTE ขนาด 1.5 เมตร", "unitName": "ตัว", "sellPrice": 1650, "sellVatType": 3, "type": 3},
            {"id": "m4", "code": "DC-T120", "name": "โช๊คประตู Top ขนาด 1.2 เมตร", "unitName": "ตัว", "sellPrice": 1100, "sellVatType": 3, "type": 3},
            {"id": "m5", "code": "DC-T150", "name": "โช๊คประตู Top ขนาด 1.5 เมตร", "unitName": "ตัว", "sellPrice": 1350, "sellVatType": 3, "type": 3},
            {"id": "m6", "code": "SV-INST", "name": "ค่าบริการติดตั้ง", "unitName": "งาน", "sellPrice": 500, "sellVatType": 3, "type": 1},
        ]

    def list_documents(self, path: str) -> list[dict]:
        """A few made-up documents in the current month, so the Account page can be tried without an account."""
        from datetime import date

        day = date.today().replace(day=1).isoformat()
        samples = {
            "/tax-invoices": [
                {"recordId": 7001, "documentSerial": "IV-MOCK-0001", "publishedOn": day, "contactName": "บริษัท ทดสอบ จำกัด", "contactTaxId": "0105555555555",
                 "contactBranch": "สำนักงานใหญ่", "contactGroup": 3, "subTotal": 10000, "totalAfterDiscount": 10000, "isVat": True, "vatAmount": 700,
                 "grandTotal": 10700, "documentWithholdingTaxPercentage": 3, "documentWithholdingTaxAmount": 300, "statusString": "Approved"},
            ],
            "/cash-invoices": [
                {"recordId": 7101, "documentSerial": "CA-MOCK-0001", "publishedOn": day, "contactName": "ร้าน ตัวอย่าง", "contactTaxId": "",
                 "contactGroup": 1, "subTotal": 2000, "totalAfterDiscount": 2000, "isVat": True, "vatAmount": 140, "grandTotal": 2140, "statusString": "Approved"},
            ],
            "/expenses": [
                {"recordId": 8001, "documentSerial": "EXP-MOCK-0001", "publishedOn": day, "contactName": "บริษัท ผู้ขาย จำกัด", "contactTaxId": "0105666666666",
                 "contactGroup": 3, "subTotal": 3000, "totalAfterDiscount": 3000, "isVat": True, "vatAmount": 210, "grandTotal": 3210,
                 "documentWithholdingTaxPercentage": 3, "documentWithholdingTaxAmount": 90, "remarks": "ค่าบริการขนส่ง", "statusString": "Approved"},
            ],
        }
        return samples.get(path, [])

    def create_document(self, doc_type: str, payload: dict) -> IssuedDocument:
        n = next(self._counter)
        serial = f"{self.PREFIX[doc_type]}-MOCK-{n:04d}"
        return IssuedDocument(record_id=str(900000 + n), serial=serial, raw={"documentSerial": serial, **payload})


@lru_cache
def get_flowaccount_client() -> FlowAccountClient | MockFlowAccountClient:
    s = get_settings()
    if s.flowaccount_mode == "mock":
        return MockFlowAccountClient()
    if not (s.flowaccount_client_id and s.flowaccount_client_secret):
        raise FlowAccountError("ยังไม่ได้ตั้งค่า FLOWACCOUNT_CLIENT_ID / FLOWACCOUNT_CLIENT_SECRET")
    return FlowAccountClient(s.flowaccount_base_url, s.flowaccount_client_id, s.flowaccount_client_secret, s.flowaccount_scope, token_store=DbTokenStore())
