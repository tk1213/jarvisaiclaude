from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app import permissions

from app.config import get_settings
from app.db import get_db
from app.deps import get_current_user, require_admin
from app.models import ChatMessage, User
from app.ratelimit import limiter
from app.schemas import LoginRequest, PasswordReset, TokenResponse, UserCreate, UserOut, UserUpdate
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(tags=["auth"])


def user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        is_admin=user.is_admin,
        can_control_devices=permissions.allowed(user, "home", "edit"),
        can_issue_documents=permissions.allowed(user, "flowaccount", "edit"),
        permissions=permissions.levels(user),
        line_linked=user.line_user_id is not None,
    )


def _create_user(db: Session, body: UserCreate) -> User:
    if db.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(status.HTTP_409_CONFLICT, "ชื่อผู้ใช้นี้มีอยู่แล้ว")
    user = User(
        username=body.username,
        display_name=body.display_name or body.username,
        password_hash=hash_password(body.password),
        is_admin=body.is_admin,
    )
    permissions.set_levels(user, {page: "edit" for page in permissions.PAGES} if body.is_admin else body.permissions)
    db.add(user)
    db.commit()
    return user


def _member(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ไม่พบสมาชิกนี้")
    return user


@router.post("/auth/bootstrap", response_model=UserOut, status_code=201)
def bootstrap(body: UserCreate, db: Session = Depends(get_db)):
    """Create the first (owner) account. Only works while there are no users."""
    if db.scalar(select(func.count()).select_from(User)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Already bootstrapped")
    return user_out(_create_user(db, body.model_copy(update={"is_admin": True})))


@router.post("/auth/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    client_ip = request.client.host if request.client else "unknown"
    limiter.hit(f"login:{client_ip}:{body.username}", get_settings().rate_limit_login_per_minute)
    user = db.scalar(select(User).where(User.username == body.username, User.deleted_at.is_(None)))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    return TokenResponse(access_token=create_access_token(user.id))


@router.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user_out(user)


# --- Members (the 👥 สมาชิก page, admin only) -------------------------------------------------------------------------


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return user_out(_create_user(db, body))


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return [user_out(u) for u in db.scalars(select(User).where(User.deleted_at.is_(None)).order_by(User.id))]


@router.put("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserUpdate, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    user = _member(db, user_id)
    if body.display_name is not None:
        user.display_name = body.display_name.strip() or user.username
    if body.permissions is not None:
        if user.is_admin:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "admin เข้าได้ทุกหน้าเสมอ ไม่ต้องตั้งสิทธิ์")
        permissions.set_levels(user, body.permissions)
    db.commit()
    return user_out(user)


@router.post("/users/{user_id}/password", status_code=204)
def reset_password(user_id: int, body: PasswordReset, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    user = _member(db, user_id)
    user.password_hash = hash_password(body.password)
    db.commit()


@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Remove a member: they can't sign in or use LINE any more and their chats are deleted. The row stays (renamed,
    so the username can be used again) because the document log still records who issued what."""
    user = _member(db, user_id)
    if user.id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ลบบัญชีตัวเองไม่ได้")
    if user.is_admin:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ลบบัญชี admin ไม่ได้")
    user.deleted_at = datetime.now(timezone.utc)
    user.username = f"{user.username}#deleted-{user.id}"[:64]
    user.line_user_id = None
    user.password_hash = "!"
    permissions.set_levels(user, {})
    db.execute(delete(ChatMessage).where(ChatMessage.user_id == user.id))
    db.commit()
