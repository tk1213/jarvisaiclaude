"""The dashboard's page names (tab labels), which an admin can change with the ✏️ next to the tabs.

Stored in jarvis.db (`app_settings`, key "page_names") so every screen and member sees the same names, and used
wherever a page is named: the tabs, the money pages' headings, the 👥 สมาชิก ticks, API errors and LINE replies.
Page ids (#company, #personal ...) never change.
"""

import json

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import AppSetting

DEFAULTS = {
    "home": "🏠 บ้าน",
    "flowaccount": "📄 FlowAccount",
    "account": "💰 Account ภาษี",
    "personal": "💳 การเงินส่วนตัว",
    "company": "🏢 การเงินบริษัท",
    "members": "👥 สมาชิก",
}
MAX_LENGTH = 40
_KEY = "page_names"


def get_all(db: Session) -> dict[str, str]:
    row = db.get(AppSetting, _KEY)
    try:
        stored = json.loads(row.value) if row else {}
    except ValueError:
        stored = {}
    return {page: (stored.get(page) if isinstance(stored, dict) and stored.get(page) else default) for page, default in DEFAULTS.items()}


def save(db: Session, names: dict[str, str]) -> dict[str, str]:
    """Keep the given names (blank = back to the default; unknown pages are ignored)."""
    current = get_all(db)
    for page in DEFAULTS:
        if page in names:
            text = " ".join(str(names[page]).split())[:MAX_LENGTH]
            current[page] = text or DEFAULTS[page]
    changed = {page: name for page, name in current.items() if name != DEFAULTS[page]}
    row = db.get(AppSetting, _KEY) or AppSetting(key=_KEY)
    row.value = json.dumps(changed, ensure_ascii=False)
    db.add(row)
    db.commit()
    return current


def name(page: str) -> str:
    """One page's current name, for text built outside a request's own session (LINE replies, errors)."""
    with SessionLocal() as db:
        return get_all(db).get(page, page)
