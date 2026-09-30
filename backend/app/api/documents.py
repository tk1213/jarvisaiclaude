from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import User
from app.services import documents as docs

router = APIRouter(tags=["documents"])


class DocumentOut(BaseModel):
    id: int
    document: str
    status: str
    serial: str | None
    customer: str | None
    grand_total: str
    channel: str
    created_at: str


@router.get("/documents", response_model=list[DocumentOut])
def list_documents(limit: int = 20, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Documents JARVIS prepared or issued for this user, newest first (spec §6 audit trail)."""
    return [
        DocumentOut(
            id=d.id,
            document=docs.DOC_NAMES.get(d.doc_type, d.doc_type),
            status=d.status,
            serial=d.document_serial,
            customer=(d.payload.get("customer") or {}).get("name"),
            grand_total=d.total_amount,
            channel=d.channel,
            created_at=d.created_at.isoformat(),
        )
        for d in docs.recent(db, user, max(1, min(limit, 100)))
    ]
