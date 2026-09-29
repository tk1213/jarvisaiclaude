from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db import get_db
from app.integrations.tuya import get_tuya_client
from app.models import User
from app.security import decode_access_token

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated", {"WWW-Authenticate": "Bearer"})
    if creds is None:
        raise unauthorized
    try:
        user_id = decode_access_token(creds.credentials)
    except Exception:
        raise unauthorized from None
    user = db.get(User, user_id)
    if user is None:
        raise unauthorized
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin only")
    return user


def require_device_control(user: User = Depends(get_current_user)) -> User:
    if not user.can_control_devices:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No permission to control devices")
    return user


def get_tuya():
    return get_tuya_client()
