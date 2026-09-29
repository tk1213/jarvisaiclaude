"""Device operations shared by the REST API and (from phase 1) the LLM tools."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.tuya import TuyaError
from app.models import Device

# Data-point codes that turn a device on/off, in order of preference.
POWER_CODES = ("switch_led", "switch", "switch_1")


class DeviceNotFound(LookupError):
    pass


def _status_dict(status: list[dict]) -> dict:
    return {s["code"]: s["value"] for s in status}


def sync_devices(db: Session, tuya) -> list[Device]:
    """Pull the device list (and room assignment) from Tuya into the database."""
    room_of: dict[str, str] = {}
    try:
        for room in tuya.list_rooms():
            for d in tuya.list_room_devices(str(room["room_id"])):
                room_of[d["id"]] = room["name"]
    except (TuyaError, ValueError):
        pass  # rooms are optional; they can also be set manually

    existing = {d.tuya_device_id: d for d in db.scalars(select(Device))}
    synced = []
    for raw in tuya.list_devices():
        device = existing.get(raw["id"]) or Device(tuya_device_id=raw["id"])
        device.name = raw.get("name", device.name or raw["id"])
        device.category = raw.get("category", "")
        device.product_name = raw.get("product_name", "")
        device.online = bool(raw.get("online", False))
        device.status = _status_dict(raw.get("status", []))
        if raw["id"] in room_of:
            device.room = room_of[raw["id"]]
        db.add(device)
        synced.append(device)
    db.commit()
    return synced


def get_device(db: Session, device_id: int) -> Device:
    device = db.get(Device, device_id)
    if device is None:
        raise DeviceNotFound(f"device {device_id} not found")
    return device


def find_devices(db: Session, name: str | None = None, room: str | None = None) -> list[Device]:
    """Loose lookup by (partial) name and/or room, for natural-language commands."""
    query = select(Device)
    if name:
        query = query.where(Device.name.ilike(f"%{name}%"))
    if room:
        query = query.where(Device.room.ilike(f"%{room}%"))
    return list(db.scalars(query.order_by(Device.id)))


def refresh_status(db: Session, tuya, device: Device) -> Device:
    device.status = _status_dict(tuya.get_device_status(device.tuya_device_id))
    db.commit()
    return device


def control_device(db: Session, tuya, device: Device, commands: list[dict]) -> Device:
    tuya.send_commands(device.tuya_device_id, commands)
    return refresh_status(db, tuya, device)


def apply_device_event(db: Session, event: dict) -> Device | None:
    """Apply a Tuya Pulsar event (status report or online/offline) to the stored device."""
    device_id = event.get("devId")
    device = db.scalar(select(Device).where(Device.tuya_device_id == device_id)) if device_id else None
    if device is None:
        return None
    if event.get("status"):
        # Reassign rather than mutate: the JSON column only notices a new object.
        device.status = {**device.status, **_status_dict(event["status"])}
    if event.get("bizCode") in ("online", "offline"):
        device.online = event["bizCode"] == "online"
    db.commit()
    return device


def power_code(device: Device) -> str:
    for code in POWER_CODES:
        if code in device.status:
            return code
    raise ValueError(f"device '{device.name}' has no known power switch")


def set_power(db: Session, tuya, device: Device, on: bool) -> Device:
    return control_device(db, tuya, device, [{"code": power_code(device), "value": on}])
