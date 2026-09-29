"""Phase 0 smoke test: talk to Tuya directly, no LLM involved.

    python -m app.scripts.tuya_check                    # list devices + status
    python -m app.scripts.tuya_check scenes             # list scenes
    python -m app.scripts.tuya_check on  <device_id>    # turn a device on
    python -m app.scripts.tuya_check off <device_id>    # turn a device off
    python -m app.scripts.tuya_check cmd <device_id> <code> <json-value>
    python -m app.scripts.tuya_check ir <ir_hub_device_id>   # remotes + keys of an IR hub
    python -m app.scripts.tuya_check info <device_id>        # full device details
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
            status = d.get("status") or []
            if not status:
                try:
                    status = tuya.get_shadow_properties(d["id"])
                    if status:
                        print("    (from shadow properties)")
                except Exception as e:
                    print(f"    shadow properties: n/a {e}")
            for s in status:
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
    elif action == "info" and len(argv) == 2:
        print(json.dumps(tuya.get_device_info(argv[1]), ensure_ascii=False, indent=2))
    elif action == "ir" and len(argv) == 2:
        remotes = tuya.ir_list_remotes(argv[1])
        if not remotes:
            print("No remotes on this IR hub. Add one (e.g. your AC) to it in the Tuya Smart app first.")
        for r in remotes:
            print(json.dumps(r, ensure_ascii=False))
            keys = tuya.ir_remote_keys(argv[1], r["remote_id"])
            print("  category_id:", keys.get("category_id"), "| single_air:", keys.get("single_air"))
            for k in keys.get("key_list", []):
                print(f"    key_id={k.get('key_id')} key={k.get('key')} name={k.get('key_name')} standard={k.get('standard_key')}")
            try:
                print("  ac/status:", json.dumps(tuya.ir_ac_status(argv[1], r["remote_id"]), ensure_ascii=False))
            except Exception as e:  # not an AC remote, or not supported
                print("  ac/status: n/a", e)
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
