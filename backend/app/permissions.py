"""Which dashboard pages each member may open, set by an admin on the 👥 สมาชิก page.

Every page has a level: "none" (hidden), "view" (look only) or "edit" (also change things). Chat has no view-only
mode, so it is "none" or "edit". Admins always get "edit" everywhere. The same levels guard the API, JARVIS's tools
(dashboard chat and LINE) and the LINE slip groups, so hiding a tab is never the only protection.
"""

import json
from typing import Literal

from fastapi import Depends, HTTPException, status

from app.deps import get_current_user
from app.models import User

Level = Literal["none", "view", "edit"]
PAGES = ("home", "flowaccount", "account", "personal", "company", "chat")
PAGE_NAMES = {
    "home": "บ้าน",
    "flowaccount": "FlowAccount",
    "account": "Account ภาษี",
    "personal": "การเงินส่วนตัว",
    "company": "การเงินบริษัท",
    "chat": "แชทกับจาร์วิส",
}
_RANK = {"none": 0, "view": 1, "edit": 2}


def clean(levels: dict) -> dict[str, Level]:
    """Every page with a valid level (missing or unknown = "none"); chat can't be view-only."""
    out: dict[str, Level] = {}
    for page in PAGES:
        level = levels.get(page, "none")
        if level not in _RANK:
            level = "none"
        if page == "chat" and level == "view":
            level = "edit"
        out[page] = level
    return out


def levels(user: User) -> dict[str, Level]:
    if user.is_admin:
        return {page: "edit" for page in PAGES}
    if user.permissions is None:
        # Accounts made before page permissions keep what they could do then.
        return clean(
            {
                "home": "edit" if user.can_control_devices else "view",
                "flowaccount": "edit" if user.can_issue_documents else "view",
                "chat": "edit",
            }
        )
    try:
        stored = json.loads(user.permissions)
    except ValueError:
        stored = {}
    return clean(stored if isinstance(stored, dict) else {})


def allowed(user: User, page: str, need: Level = "view") -> bool:
    return _RANK[levels(user).get(page, "none")] >= _RANK[need]


def set_levels(user: User, new: dict) -> None:
    """Store a member's levels; the older yes/no flags follow, so code that still reads them agrees."""
    cleaned = clean(new)
    user.permissions = json.dumps(cleaned)
    user.can_control_devices = cleaned["home"] == "edit"
    user.can_issue_documents = cleaned["flowaccount"] == "edit"


def denied_text(page: str, need: Level = "view") -> str:
    what = "แก้ไข" if need == "edit" else "เข้า"
    return f"บัญชีนี้ไม่มีสิทธิ์{what}หน้า{PAGE_NAMES[page]} ให้ admin เปิดสิทธิ์ในหน้า 👥 สมาชิก"


def require(page: str, need: Level = "view"):
    """FastAPI dependency: the signed-in user, if they have at least `need` on `page` (403 otherwise)."""
    def check(user: User = Depends(get_current_user)) -> User:
        if not allowed(user, page, need):
            raise HTTPException(status.HTTP_403_FORBIDDEN, denied_text(page, need))
        return user

    return check
