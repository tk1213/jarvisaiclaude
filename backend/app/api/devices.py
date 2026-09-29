from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, get_tuya, require_device_control
from app.schemas import CommandRequest, DeviceOut, DeviceUpdate, PowerRequest, SceneOut
from app.services import devices as svc

router = APIRouter(tags=["home_control"], dependencies=[Depends(get_current_user)])


def _get(db: Session, device_id: int):
    try:
        return svc.get_device(db, device_id)
    except svc.DeviceNotFound as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from None


@router.post("/devices/sync", response_model=list[DeviceOut])
def sync_devices(db: Session = Depends(get_db), tuya=Depends(get_tuya)):
    return svc.sync_devices(db, tuya)


@router.get("/devices", response_model=list[DeviceOut])
def list_devices(name: str | None = None, room: str | None = None, db: Session = Depends(get_db)):
    return svc.find_devices(db, name=name, room=room)


@router.get("/devices/{device_id}", response_model=DeviceOut)
def get_device(device_id: int, refresh: bool = False, db: Session = Depends(get_db), tuya=Depends(get_tuya)):
    device = _get(db, device_id)
    return svc.refresh_status(db, tuya, device) if refresh else device


@router.patch("/devices/{device_id}", response_model=DeviceOut)
def update_device(
    device_id: int, body: DeviceUpdate, db: Session = Depends(get_db), _=Depends(require_device_control)
):
    """Rename a device or set its room; the values survive later syncs from Tuya."""
    device = _get(db, device_id)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("name") is not None:
        name = changes["name"].strip()
        if not name:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Name cannot be blank")
        device.name = name
        device.name_overridden = True
    if "room" in changes:
        device.room = (changes["room"] or "").strip() or None
        device.room_overridden = True
    db.commit()
    return device


@router.post("/devices/{device_id}/commands", response_model=DeviceOut)
def send_commands(
    device_id: int,
    body: CommandRequest,
    db: Session = Depends(get_db),
    tuya=Depends(get_tuya),
    _=Depends(require_device_control),
):
    commands = [c.model_dump() for c in body.commands]
    return svc.control_device(db, tuya, _get(db, device_id), commands)


@router.post("/devices/{device_id}/power", response_model=DeviceOut)
def set_power(
    device_id: int,
    body: PowerRequest,
    db: Session = Depends(get_db),
    tuya=Depends(get_tuya),
    _=Depends(require_device_control),
):
    device = _get(db, device_id)
    try:
        return svc.set_power(db, tuya, device, body.on)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from None


@router.get("/scenes", response_model=list[SceneOut])
def list_scenes(tuya=Depends(get_tuya)):
    return [SceneOut(scene_id=str(s["scene_id"]), name=s["name"]) for s in tuya.list_scenes()]


@router.post("/scenes/{scene_id}/trigger", status_code=204)
def trigger_scene(scene_id: str, tuya=Depends(get_tuya), _=Depends(require_device_control)):
    tuya.trigger_scene(scene_id)
