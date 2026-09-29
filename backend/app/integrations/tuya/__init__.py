from datetime import datetime, timezone
from functools import lru_cache

from app.config import get_settings
from app.integrations.tuya.client import TuyaClient, TuyaError, TuyaToken
from app.integrations.tuya.mock import MockTuyaClient

__all__ = ["TuyaClient", "MockTuyaClient", "TuyaError", "get_tuya_client"]


class DbTokenStore:
    """Persists the Tuya token encrypted in the `tokens` table."""

    provider = "tuya"

    def load(self) -> TuyaToken | None:
        from app.db import SessionLocal
        from app.models import ProviderToken
        from app.security import decrypt

        with SessionLocal() as db:
            row = db.get(ProviderToken, self.provider)
            return TuyaToken.from_json(decrypt(row.encrypted_value)) if row else None

    def save(self, token: TuyaToken) -> None:
        from app.db import SessionLocal
        from app.models import ProviderToken
        from app.security import encrypt

        with SessionLocal() as db:
            row = db.get(ProviderToken, self.provider) or ProviderToken(provider=self.provider)
            row.encrypted_value = encrypt(token.to_json())
            row.expires_at = datetime.fromtimestamp(token.expires_at, tz=timezone.utc)
            db.add(row)
            db.commit()


@lru_cache
def get_tuya_client() -> TuyaClient | MockTuyaClient:
    s = get_settings()
    if s.tuya_mode == "mock":
        return MockTuyaClient()
    return TuyaClient(
        endpoint=s.tuya_endpoint,
        access_id=s.tuya_access_id,
        access_secret=s.tuya_access_secret,
        user_uid=s.tuya_user_uid,
        home_id=s.tuya_home_id,
        token_store=DbTokenStore(),
    )
