from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


PageLevel = Literal["none", "view", "edit"]


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8)
    display_name: str = Field(default="", max_length=128)
    is_admin: bool = False
    # Pages this member may open ({"home": "edit", "account": "view"}); a new member starts with none.
    permissions: dict[str, PageLevel] = Field(default_factory=dict)


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=128)
    permissions: dict[str, PageLevel] | None = None


class PasswordReset(BaseModel):
    password: str = Field(min_length=8)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str
    is_admin: bool
    can_control_devices: bool
    can_issue_documents: bool
    permissions: dict[str, PageLevel]
    line_linked: bool = False


class DeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tuya_device_id: str
    name: str
    room: str | None
    category: str
    product_name: str
    online: bool
    status: dict[str, Any]
    control_denied: bool = False
    ir_hub_id: str | None = None
    updated_at: datetime


class DeviceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    # An empty string clears the room.
    room: str | None = Field(default=None, max_length=64)


class Command(BaseModel):
    code: str
    value: Any


class CommandRequest(BaseModel):
    commands: list[Command] = Field(min_length=1)


class PowerRequest(BaseModel):
    on: bool


class AcRequest(BaseModel):
    """Any subset of an IR air conditioner's settings; omitted ones keep their current value."""

    power: bool | None = None
    mode: Literal["cool", "heat", "auto", "fan", "dry"] | None = None
    temp: int | None = Field(default=None, ge=16, le=30)
    fan: Literal["auto", "low", "mid", "high"] | None = None


class SceneOut(BaseModel):
    scene_id: str
    name: str
