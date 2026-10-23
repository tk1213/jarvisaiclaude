"""App-wide settings edited from the dashboard: the page names (tab labels)."""

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app import page_names
from app.db import get_db
from app.deps import get_current_user, require_admin
from app.models import User

router = APIRouter(tags=["settings"])


@router.get("/page-names")
def get_page_names(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict[str, str]:
    return page_names.get_all(db)


@router.put("/page-names")
def set_page_names(
    names: dict[str, str] = Body(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> dict[str, str]:
    """Rename pages ({"company": "🏢 บัญชีบริษัท TK"}); a blank name goes back to the default."""
    return page_names.save(db, names)
