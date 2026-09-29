"""Phase 0 smoke test: talk to Tuya directly, no LLM involved.

    python -m app.scripts.tuya_check                    # list devices + status
    python -m app.scripts.tuya_check scenes             # list scenes
    python -m app.scripts.tuya_check on  <device_id>    # turn a device on
    python -m app.scripts.tuya_check off <device_id>    # turn a device off
    python -m app.scripts.tuya_check cmd <device_id> <code> <json-value>
"""

import json
import sys

from app.config import get_settings
from app.db import init_db
from app.integrations.tuya import get_tuya_client
from app.services.devices import POWER_CODES


def main(argv: list[str]) -> int:
    init_db()  # the live client persists its token in the database
    tuya = get_tuya_client()
    print(f"Tuya mode: {get_settings().tuya_mode}")
    action = argv[0] if argv else "list"

    if action == "list":
        for d in tuya.list_devices():
            state = "online" if d.get("online") else "offline"
            print(f"- {d['id']}  {d.get('name')}  [{d.get('category')}, {state}]")
            for s in d.get("status", []):
                print(f"    {s['code']} = {s['value']}")
    elif action == "scenes":
        for s in tuya.list_scenes():
            print(f"- {s['scene_id']}  {s['name']}")
    elif action in ("on", "off") and len(argv) == 2:
        codes = {s["code"] for s in tuya.get_device_status(argv[1])}
        code = next((c for c in POWER_CODES if c in codes), None)
        if code is None:
            print(f"No power switch among {sorted(codes)}")
            return 1
        tuya.send_commands(argv[1], [{"code": code, "value": action == "on"}])
        print(json.dumps(tuya.get_device_status(argv[1]), ensure_ascii=False))
    elif action == "cmd" and len(argv) == 4:
        tuya.send_commands(argv[1], [{"code": argv[2], "value": json.loads(argv[3])}])
        print(json.dumps(tuya.get_device_status(argv[1]), ensure_ascii=False))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
