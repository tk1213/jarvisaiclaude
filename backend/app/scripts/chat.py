"""Chat with JARVIS from the terminal (same brain as the dashboard).

    python -m app.scripts.chat <username>

Type a message and press Enter; an empty line or Ctrl+C exits. The whole
conversation is one session, so JARVIS remembers earlier turns.
"""

import sys

from sqlalchemy import select

from app.core.messages import Channel, InboundMessage
from app.core.orchestrator import get_orchestrator
from app.db import SessionLocal, init_db
from app.integrations.tuya import get_tuya_client
from app.models import User


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    init_db()
    orchestrator = get_orchestrator()
    tuya = get_tuya_client()
    session_id = None

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == argv[0]))
        if user is None:
            print(f"No user named {argv[0]!r}")
            return 1
        print("JARVIS พร้อมแล้วค่ะ (Enter ว่างเพื่อออก)")
        while True:
            try:
                text = input("คุณ: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not text:
                break
            msg = InboundMessage(user_id=user.id, channel=Channel.dashboard, session_id=session_id, text=text)
            reply = orchestrator.handle(db, tuya, user, msg)
            session_id = reply.session_id
            for call in reply.tool_calls:
                print(f"  [{'ok' if call.ok else 'error'}] {call.name} {call.input}")
            print(f"JARVIS: {reply.text}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
