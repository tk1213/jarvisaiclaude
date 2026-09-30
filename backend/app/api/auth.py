from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.deps import get_current_user, require_admin
from app.models import User
from app.ratelimit import limiter
from app.schemas import LoginRequest, TokenResponse, UserCreate, UserOut
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(tags=["auth"])


def _create_user(db: Session, body: UserCreate) -> User:
    if db.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already exists")
    user = User(
        username=body.username,
        display_name=body.display_name or body.username,
        password_hash=hash_password(body.password),
        is_admin=body.is_admin,
        can_control_devices=body.can_control_devices,
        can_issue_documents=body.can_issue_documents,
    )
    db.add(user)
    db.commit()
    return user


@router.post("/auth/bootstrap", response_model=UserOut, status_code=201)
def bootstrap(body: UserCreate, db: Session = Depends(get_db)):
    """Create the first (owner) account. Only works while there are no users."""
    if db.scalar(select(func.count()).select_from(User)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Already bootstrapped")
    body = body.model_copy(update={"is_admin": True, "can_control_devices": True, "can_issue_documents": True})
    return _create_user(db, body)


@router.post("/auth/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    client_ip = request.client.host if request.client else "unknown"
    limiter.hit(f"login:{client_ip}:{body.username}", get_settings().rate_limit_login_per_minute)
    user = db.scalar(select(User).where(User.username == body.username))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    return TokenResponse(access_token=create_access_token(user.id))


@router.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return _create_user(db, body)


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return list(db.scalars(select(User).order_by(User.id)))
