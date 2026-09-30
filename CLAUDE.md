# JARVIS AI: notes for Claude sessions

## Working with the owner

- **Reply in Thai.** The owner reads Thai; keep code, commits and identifiers in English.
- The owner runs everything on **Windows** (PowerShell, Python 3.14, Chrome) from `D:\Claude\jarvisclaude`
  (a clone of this repo). Give Windows commands, and after each change say exactly what to run there:
  - server-only changes: `git pull`, then close and reopen `start.bat`
  - frontend changes: also `cd frontend && npm run build`, then Ctrl+F5 in the dashboard
  - new Python dependencies: `cd backend && .venv\Scripts\activate && pip install -e ".[dev]"`
- **Secrets live only in `backend\.env` on the owner's machine** (gitignored): `ANTHROPIC_API_KEY`,
  `TUYA_ACCESS_SECRET`, `GOOGLE_TTS_API_KEY`, `JWT_SECRET`, `ENCRYPTION_KEY`. Never ask for them in chat;
  if one shows up in a screenshot or log, tell the owner to rotate it.
- Work phase by phase following `docs/roadmap.md` (spec: the owner's Thai JARVIS PDF). Update the roadmap
  checkboxes and the Thai `README.md` when a feature lands.

## Layout

- `backend/` FastAPI + SQLAlchemy 2 (SQLite locally, Postgres in docker-compose), settings from `.env`
  via pydantic-settings (`app/config.py`)
  - `app/core/orchestrator.py` Claude tool loop (manual loop, append-only history in `chat_sessions`)
  - `app/core/tools.py` home-control tools; `app/core/prompts.py` persona + voice hint
  - `app/integrations/tuya/` OpenAPI client, Pulsar realtime events, mock home
  - `app/services/devices.py` device logic (sync, power, IR air conditioner)
  - `app/api/voice.py` + `app/integrations/google_tts.py` / `edge_voice.py` spoken replies
- `frontend/` React 19 + TypeScript + Vite + Tailwind v4; built `frontend/dist` is served by the backend at `/`
  - `src/components/ChatPanel.tsx` chat, mic, wake-word UI; `src/voice.ts` speech in/out; `src/wake.ts` "Hey Jarvis"

## Checks before pushing

```bash
cd backend && pytest                      # all tests use the Tuya mock; no network needed
cd frontend && npm run build && npm run lint
```
Frontend style: no semicolons, single quotes, long lines are fine (there is no Prettier config; if you
run Prettier use `--no-semi --single-quote --print-width 180`). `TUYA_MODE=mock` runs the app without devices.

## Claude API usage (keep these when editing the orchestrator)

- Model `claude-opus-5-5`, `client.beta.messages.create` with betas `server-side-fallback-2026-07-01`
  and `thinking-binding-controls-2026-08-01`, `fallbacks="default"`, adaptive thinking with
  `block_binding.prefix_mismatch_behavior="drop_block"`, effort `low`.
- The system prompt and tool list must stay byte-identical across a conversation; per-turn data (time,
  device snapshot, voice hint) goes in the user turn. History is append-only (preserved thinking).
- Server-side web search `web_search_20260209` (no `country` in `user_location`: "TH" is rejected);
  the loop resumes `pause_turn`.

## Decisions already made with the owner

- JARVIS is female, bright and cheerful, ends sentences with ค่ะ/คะ. Her name is said **"จาร์วิส"**
  (never spelled J-A-R-V-I-S); speech also rewrites "JARVIS" to จาร์วิส.
- Replies write numbers as digits (24.6 °C, 72%); the voice reads numbers slower (`TTS_NUMBER_RATE`).
- Voice: Google Cloud TTS (`th-TH-Neural2-C`) first when `GOOGLE_TTS_API_KEY` is set, then Edge
  Premwadee, then text only. **Never fall back to a male voice** (Windows Pattara and Edge Niwat are male).
- Hands-free: the 🎙 button keeps the mic waiting for "Hey Jarvis"/"เฮ้ จาร์วิส" only (the bare name doesn't
  wake it; sound-alikes "Hey David", "เฮ้ เดวิด/เดวิก/จาวิก" also wake it); JARVIS greets "ค่ะ TK มีอะไรให้ช่วยไหมคะ";
  waking turns on the "โหมดปลุก" switch for a continuous conversation; "Stop Jarvis" /
  "จาร์วิส หยุดการทำงาน" goes back to waiting (mic stays on); 60 s of silence also sleeps. One dashboard tab
  listens at a time and JARVIS's own replies are ignored as commands.
- New devices are added only by the "อัปเดตอุปกรณ์" button, never automatically.
- The IR air conditioner (Air PANASONIC via the Temp Smart Jarvis hub) can't report changes made in the
  Tuya app or with its physical remote; the dashboard/JARVIS side is the source of truth.

## Next up

Phase 1: LINE OA (Messaging API webhook + Flex Message; needs a LINE Official Account and a public URL,
e.g. Cloudflare Tunnel). Then phase 2: FlowAccount. Remind the owner to renew the Anthropic API key
before it expires on 29 Dec 2026.
