"""Device operations shared by the REST API and (from phase 1) the LLM tools."""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.tuya import TuyaError
from app.models import Device

log = logging.getLogger(__name__)

# Data-point codes that turn a device on/off, in order of preference.
POWER_CODES = ("switch_led", "switch", "switch_1")


class DeviceNotFound(LookupError):
    pass


def _status_dict(status: list[dict]) -> dict:
    return {s["code"]: s["value"] for s in status}


def _fresh_status(tuya, device_id: str, listed: list[dict]) -> dict:
    """Status from the device list, falling back to shadow properties when the list has none.

    Some devices (IR hubs with a thermometer) report nothing in the device list; their
    readings only arrive via Pulsar or the shadow endpoint.
    """
    if listed:
        return _status_dict(listed)
    try:
        return _status_dict(tuya.get_shadow_properties(device_id))
    except TuyaError:
        return {}


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
        if not device.name_overridden:
            device.name = raw.get("name", device.name or raw["id"])
        device.category = raw.get("category", "")
        device.product_name = raw.get("product_name", "")
        device.online = bool(raw.get("online", False))
        # Merge so values only reported via Pulsar aren't wiped by an empty listing.
        device.status = {**(device.status or {}), **_fresh_status(tuya, raw["id"], raw.get("status", []))}
        if raw["id"] in room_of and not device.room_overridden:
            device.room = room_of[raw["id"]]
        db.add(device)
        synced.append(device)
    # Drop devices that are no longer in the Tuya account.
    seen = {d.tuya_device_id for d in synced}
    for tuya_id, device in existing.items():
        if tuya_id not in seen:
            db.delete(device)
    db.commit()
    return synced


def refresh_all_status(db: Session, tuya) -> None:
    """Update status/online of every known device with one Tuya call.

    Pulsar keeps the table current while the server runs; this covers the
    times it isn't (CLI use, a dropped connection) before answering questions.
    """
    fresh = {raw["id"]: raw for raw in tuya.list_devices()}
    for device in db.scalars(select(Device)):
        raw = fresh.get(device.tuya_device_id)
        if raw is not None:
            device.status = {**(device.status or {}), **_fresh_status(tuya, device.tuya_device_id, raw.get("status", []))}
            device.online = bool(raw.get("online", False))
    db.commit()


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
    fresh = _fresh_status(tuya, device.tuya_device_id, tuya.get_device_status(device.tuya_device_id))
    device.status = {**(device.status or {}), **fresh}
    db.commit()
    return device


def is_permission_error(e: TuyaError) -> bool:
    return str(e.code) == "1106" or "permission" in str(e.msg).lower()


def control_device(db: Session, tuya, device: Device, commands: list[dict]) -> Device:
    try:
        tuya.send_commands(device.tuya_device_id, commands)
    except TuyaError as e:
        if is_permission_error(e) and not device.control_denied:
            device.control_denied = True
            db.commit()
        raise
    device.control_denied = False
    # Tuya accepted the commands, but the device may not have reported its new
    # state to the cloud yet, so overlay what we sent on top of the fetched
    # status. Pulsar corrects it if the device ends up in a different state.
    fetched = _status_dict(tuya.get_device_status(device.tuya_device_id))
    device.status = {**fetched, **_status_dict(commands)}
    db.commit()
    return device


_ONLINE_CODES = {"online": True, "deviceOnline": True, "offline": False, "deviceOffline": False}


def apply_device_event(db: Session, event: dict) -> Device | None:
    """Apply a Tuya Pulsar event (status report or online/offline) to the stored device.

    Handles both the legacy shape ({"devId", "status": [...]}) and the Message
    Queue shape ({"bizCode", "bizData": {"devId", "properties": [...]}}).
    """
    biz_data = event.get("bizData") or {}
    device_id = event.get("devId") or biz_data.get("devId")
    device = db.scalar(select(Device).where(Device.tuya_device_id == device_id)) if device_id else None
    if device is None:
        log.info("ignoring Tuya event for unknown device: %s", event)
        return None
    status = event.get("status") or biz_data.get("properties") or biz_data.get("status")
    if status:
        # Reassign rather than mutate: the JSON column only notices a new object.
        device.status = {**device.status, **_status_dict(status)}
    biz_code = event.get("bizCode")
    if biz_code in _ONLINE_CODES:
        device.online = _ONLINE_CODES[biz_code]
    elif not status:
        log.info("unhandled Tuya event: %s", event)
    db.commit()
    return device


def power_code(device: Device) -> str:
    for code in POWER_CODES:
        if code in device.status:
            return code
    raise ValueError(f"device '{device.name}' has no known power switch")


def set_power(db: Session, tuya, device: Device, on: bool) -> Device:
    return control_device(db, tuya, device, [{"code": power_code(device), "value": on}])
