"""Phase 2 smoke test: talk to FlowAccount directly, no LLM involved.

    python -m app.scripts.flowaccount_check              # settings + get an access token
    python -m app.scripts.flowaccount_check quotation    # also create a small test quotation (use the sandbox!)
"""

import json
import sys
from datetime import date

from app.config import get_settings
from app.db import init_db
from app.integrations.flowaccount import FlowAccountClient, FlowAccountError, get_flowaccount_client


def main(argv: list[str]) -> int:
    init_db()  # the live client keeps its token in the database
    s = get_settings()
    print(f"FlowAccount mode: {s.flowaccount_mode}")
    print(f"Base URL:         {s.flowaccount_base_url}")
    print(f"Client ID set:    {'yes' if s.flowaccount_client_id else 'NO'}")
    print(f"Client secret:    {'set' if s.flowaccount_client_secret else 'NOT SET'}")
    try:
        client = get_flowaccount_client()
    except FlowAccountError as e:
        print(f"\n✗ {e}")
        return 1
    if not isinstance(client, FlowAccountClient):
        print("\nmock mode: nothing to check (set FLOWACCOUNT_MODE=live)")
        return 0

    try:
        client._access_token(refresh=True)
    except FlowAccountError as e:
        print(f"\n✗ token: {e}")
        print("  Check FLOWACCOUNT_CLIENT_ID / SECRET and that they belong to this server (sandbox vs production).")
        return 1
    print("\n✓ got an access token")

    if argv[:1] == ["quotation"]:
        today = date.today().isoformat()
        payload = {
            "contactName": "ลูกค้าทดสอบ JARVIS",
            "contactGroup": 1,
            "publishedOn": today,
            "creditType": 1,
            "creditDays": 30,
            "dueDate": today,
            "isVat": False,
            "isVatInclusive": False,
            "subTotal": 100.0,
            "discountAmount": 0,
            "totalAfterDiscount": 100.0,
            "vatAmount": 0.0,
            "grandTotal": 100.0,
            "remarks": "เอกสารทดสอบจาก JARVIS ลบได้",
            "items": [{"type": 3, "name": "ทดสอบ", "quantity": 1, "unitName": "ชิ้น", "pricePerUnit": 100.0, "total": 100.0}],
        }
        try:
            doc = client.create_document("quotation", payload)
        except FlowAccountError as e:
            print(f"✗ quotation: {e}")
            return 1
        print(f"✓ quotation created: {doc.serial or '(no serial)'} recordId={doc.record_id}")
        print(json.dumps(doc.raw, ensure_ascii=False, indent=2)[:1500])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
