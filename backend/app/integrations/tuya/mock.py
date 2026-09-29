"""In-memory fake of TuyaClient, used when TUYA_MODE=mock (dev and tests)."""

import copy
import threading

from app.integrations.tuya.client import TuyaError

_SEED_DEVICES = [
    {
        "id": "mock-light-living",
        "name": "ไฟห้องนั่งเล่น",
        "category": "dj",
        "product_name": "Smart Bulb",
        "online": True,
        "room_id": "r1",
        "status": [{"code": "switch_led", "value": False}, {"code": "bright_value_v2", "value": 800}],
    },
    {
        "id": "mock-ac-bedroom",
        "name": "แอร์ห้องนอน",
        "category": "kt",
        "product_name": "Smart AC",
        "online": True,
        "room_id": "r2",
        "status": [
            {"code": "switch", "value": False},
            {"code": "temp_set", "value": 25},
            {"code": "mode", "value": "cold"},
        ],
    },
    {
        "id": "mock-plug-kitchen",
        "name": "ปลั๊กกาต้มน้ำ",
        "category": "cz",
        "product_name": "Smart Plug",
        "online": True,
        "room_id": "r3",
        "status": [{"code": "switch_1", "value": False}],
    },
]

_ROOMS = [{"room_id": "r1", "name": "ห้องนั่งเล่น"}, {"room_id": "r2", "name": "ห้องนอน"}, {"room_id": "r3", "name": "ห้องครัว"}]

_SCENES = [
    {"scene_id": "scene-good-night", "name": "ราตรีสวัสดิ์", "actions": [("mock-light-living", "switch_led", False)]},
    {"scene_id": "scene-home", "name": "กลับถึงบ้าน", "actions": [("mock-light-living", "switch_led", True)]},
]


class MockTuyaClient:
    def __init__(self):
        self._devices = {d["id"]: copy.deepcopy(d) for d in _SEED_DEVICES}
        self._lock = threading.Lock()

    def _device(self, device_id: str) -> dict:
        try:
            return self._devices[device_id]
        except KeyError:
            raise TuyaError(2009, f"device {device_id} not found") from None

    def list_devices(self) -> list[dict]:
        return [{k: v for k, v in d.items() if k != "room_id"} for d in copy.deepcopy(list(self._devices.values()))]

    def get_device_status(self, device_id: str) -> list[dict]:
        return copy.deepcopy(self._device(device_id)["status"])

    def send_commands(self, device_id: str, commands: list[dict]) -> bool:
        with self._lock:
            device = self._device(device_id)
            by_code = {s["code"]: s for s in device["status"]}
            for cmd in commands:
                if cmd["code"] not in by_code:
                    raise TuyaError(2008, f"command {cmd['code']} not supported by {device_id}")
            for cmd in commands:
                by_code[cmd["code"]]["value"] = cmd["value"]
        return True

    def list_homes(self) -> list[dict]:
        return [{"home_id": "mock-home", "name": "บ้าน"}]

    def list_rooms(self) -> list[dict]:
        return copy.deepcopy(_ROOMS)

    def list_room_devices(self, room_id: str) -> list[dict]:
        return [{"id": d["id"]} for d in self._devices.values() if d["room_id"] == room_id]

    def list_scenes(self) -> list[dict]:
        return [{"scene_id": s["scene_id"], "name": s["name"]} for s in _SCENES]

    def trigger_scene(self, scene_id: str) -> bool:
        scene = next((s for s in _SCENES if s["scene_id"] == scene_id), None)
        if scene is None:
            raise TuyaError(1106, f"scene {scene_id} not found")
        for device_id, code, value in scene["actions"]:
            self.send_commands(device_id, [{"code": code, "value": value}])
        return True
