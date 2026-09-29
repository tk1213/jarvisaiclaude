from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "JARVIS Core"
    database_url: str = "postgresql+psycopg://jarvis:jarvis@localhost:5432/jarvis"

    # Auth
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24

    # Fernet key used to encrypt third-party tokens at rest (spec §6).
    # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    encryption_key: str = ""

    # Tuya Cloud (spec §4.2). "mock" runs an in-memory fake home so the
    # rest of the system can be developed without real devices.
    tuya_mode: Literal["mock", "live"] = "mock"
    tuya_endpoint: str = "https://openapi.tuyaus.com"
    tuya_access_id: str = ""
    tuya_access_secret: str = ""
    tuya_user_uid: str = ""  # UID of the linked Tuya Smart app account
    tuya_home_id: str = ""  # Home used for scenes; auto-detected if empty
    # Pulsar message service for real-time device events (live mode only).
    tuya_pulsar_enabled: bool = True
    tuya_pulsar_endpoint: str = ""  # derived from tuya_endpoint if empty
    tuya_pulsar_env: Literal["event", "event-test"] = "event"

    # Rate limits (spec §6), per user for device control, per username+IP for login.
    rate_limit_control_per_minute: int = 30
    rate_limit_login_per_minute: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()
