from sqlalchemy import inspect, text

from app.db import engine, init_db


def test_adds_new_columns_to_an_old_devices_table():
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE devices"))
        # The phase 0 schema, before name/room overrides and control_denied existed.
        conn.execute(
            text(
                "CREATE TABLE devices (id INTEGER PRIMARY KEY, tuya_device_id VARCHAR(64) UNIQUE, "
                "name VARCHAR(128), room VARCHAR(64), category VARCHAR(32), product_name VARCHAR(128), "
                "online BOOLEAN, status JSON, updated_at DATETIME)"
            )
        )
        conn.execute(text("INSERT INTO devices (tuya_device_id, name, online, status) VALUES ('d1', 'Lamp', 1, '{}')"))

    init_db()
    init_db()  # idempotent

    cols = {c["name"] for c in inspect(engine).get_columns("devices")}
    assert {"name_overridden", "room_overridden", "control_denied"} <= cols
    with engine.connect() as conn:
        row = conn.execute(text("SELECT name, name_overridden, control_denied FROM devices")).one()
    assert row[0] == "Lamp" and not row[1] and not row[2]
