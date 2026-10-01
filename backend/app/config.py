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
    # Tuya doesn't push changes to IR air conditioners made in its app, so poll them (0 = off).
    ir_ac_poll_seconds: int = 30

    # Claude (JARVIS Core, spec §4.1)
    anthropic_api_key: str = ""
    claude_model: str = "claude-opus-5-5"
    # low keeps replies fast for short home-control commands; raise for harder tasks
    claude_effort: Literal["low", "medium", "high", "xhigh", "max"] = "low"
    claude_max_tool_rounds: int = 8
    timezone: str = "Asia/Bangkok"
    # Anthropic's server-side web search, for outside questions (stocks, gold, weather, films, restaurants).
    web_search_enabled: bool = True
    web_search_max_uses: int = 3  # per reply; each search adds a few seconds
    # 2-letter country to localize results; empty = timezone only (the search provider doesn't support "TH").
    web_search_country: str = ""

    # Spoken replies use Microsoft Edge's online neural voices (free, no key); "browser" = the browser's own voices.
    tts_engine: Literal["edge", "browser"] = "edge"
    tts_voice: str = "th-TH-PremwadeeNeural"  # female; th-TH-NiwatNeural is male
    tts_rate: str = "-8%"  # speed, e.g. "+0%" normal
    tts_pitch: str = "+15Hz"  # higher = brighter
    # The dashboard can switch to a male voice (Edge only; Google has no Thai male neural voice set up here).
    tts_voice_male: str = "th-TH-NiwatNeural"
    tts_pitch_male: str = "+0Hz"
    tts_number_rate: str = "-30%"  # numbers are read at this (slower) speed so they're easy to catch
    # Google Cloud Text-to-Speech, used first when a key is set (Edge stays as the fallback).
    # TTS_RATE and TTS_NUMBER_RATE apply to it too; pitch is in semitones (-20..20).
    google_tts_api_key: str = ""
    google_tts_voice: str = "th-TH-Neural2-C"  # female; th-TH-Standard-A is another
    google_tts_pitch: float = 1.5

    # LINE Official Account (Messaging API). The webhook is POST /line/webhook on a public https URL.
    line_channel_secret: str = ""
    line_channel_access_token: str = ""
    # A LINE chat continues the same conversation until it's been quiet this long.
    line_session_idle_minutes: int = 30

    # FlowAccount Open API (spec §4.3). "mock" issues fake documents so the flow can be tried without an account.
    flowaccount_mode: Literal["mock", "live"] = "mock"
    # Production https://openapi.flowaccount.com/v1, sandbox (sandbox-new.flowaccount.com) https://openapi.flowaccount.com/test
    flowaccount_base_url: str = "https://openapi.flowaccount.com/v1"
    flowaccount_client_id: str = ""
    flowaccount_client_secret: str = ""
    flowaccount_scope: str = "flowaccount-api"

    # Rate limits (spec §6), per user for device control, per username+IP for login.
    rate_limit_control_per_minute: int = 30
    rate_limit_login_per_minute: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()
