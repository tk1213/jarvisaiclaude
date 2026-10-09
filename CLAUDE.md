# JARVIS AI: notes for Claude sessions

## Working with the owner

- **Reply in Thai.** The owner reads Thai; keep code, commits and identifiers in English.
- **Ask before changing anything.** When the owner asks whether something can be done ("ทำได้ไหม"), first answer
  yes or no and why. Before making any change (code, files, PRs, settings), summarize what will change and wait
  for the owner to confirm; don't start until they do.
- The owner runs everything on **Windows** (PowerShell, Python 3.14, Chrome) from `D:\Claude\jarvisclaude`
  (a clone of this repo). Give Windows commands, and after each change say exactly what to run there:
  - server-only changes: `git pull`, then close and reopen `start.bat`
  - frontend changes: also `cd frontend && npm run build`, then Ctrl+F5 in the dashboard
  - new Python dependencies: `cd backend && .venv\Scripts\activate && pip install -e ".[dev]"`
- **Secrets live only in `backend\.env` on the owner's machine** (gitignored): `ANTHROPIC_API_KEY`,
  `TUYA_ACCESS_SECRET`, `GOOGLE_TTS_API_KEY`, `LINE_CHANNEL_SECRET`, `LINE_CHANNEL_ACCESS_TOKEN`,
  `FLOWACCOUNT_CLIENT_SECRET`, `JWT_SECRET`,
  `ENCRYPTION_KEY`. Never ask for them in chat;
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
  - `app/api/line.py` + `app/integrations/line.py` LINE OA webhook, account linking, Flex replies
  - `app/services/documents.py` + `app/integrations/flowaccount.py` FlowAccount documents (v1 API, mock mode)
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
- Automatic prompt caching: top-level `cache_control={"type": "ephemeral"}` on every orchestrator call, so tool rounds and
  turns within 5 minutes read the repeated prefix at the cache rate. Each round logs `cache_read=` / `cache_write=` tokens
  (`journalctl -u jarvis | grep cache_read` on the mini PC) to check it's hitting.
- Server-side web search `web_search_20260209` (no `country` in `user_location`: "TH" is rejected);
  the loop resumes `pause_turn`.

## Decisions already made with the owner

- JARVIS is female, bright and cheerful, ends sentences with ค่ะ/คะ. Her name is said **"จาร์วิส"**
  (never spelled J-A-R-V-I-S); speech also rewrites "JARVIS" to จาร์วิส. She calls the owner "TK" and
  ends every reply with "ค่ะ TK" ("เปิดปลั๊ก 2 แล้วค่ะ TK"). After a device command she only says it's on/off
  (no temperature/mode details unless asked); a question about one room answers for that room only.
- Replies write numbers as digits (24.6 °C, 72%); the voice reads numbers a little slower (`TTS_NUMBER_RATE`, -20%; the owner uses -10%).
  Edge only splits numbers into separate pieces (which adds a gap before/after each) when that rate is ≥10 points
  away from the voice rate; Google uses SSML in one request, so it never has gaps. Money is spoken like a cheque:
  "5,000.00 บาท" -> ห้าพันบาทถ้วน, "5,000.30 บาท" -> ห้าพันบาทสามสิบสตางค์ (`for_speech` in `app/api/voice.py`).
- Voice: Google Cloud TTS (`th-TH-Neural2-C`) first when `GOOGLE_TTS_API_KEY` is set, then Edge
  Premwadee, then text only. **Never fall back to a male voice** (Windows Pattara and Edge Niwat are male).
  The owner can pick "🔊 เสียงผู้ชาย" in the chat header (remembered per browser): Edge Niwat only, no fallback
  to the other gender, a notch slower (`TTS_RATE_MALE`). With the male voice the dashboard sends `voice: "male"`
  and the user turn asks for ครับ instead of ค่ะ (greeting "ครับ TK มีอะไรให้ช่วยไหมครับ"); switching back to female adds a
  reminder to use ค่ะ, and `match_voice()` fixes the particle in dashboard replies either way. LINE stays ค่ะ.
- Hands-free: the 🎙 button keeps the mic waiting for "Hey Jarvis"/"เฮ้ จาร์วิส" only (the bare name doesn't
  wake it; sound-alikes "Hey David", "เฮ้ เดวิด/เดวิก/จาวิก", "เฮ้ยจาร์วิส", "hang/hen javis", "hen heavy", "เพลงจาร์วิส" also wake it); JARVIS greets "ค่ะ TK มีอะไรให้ช่วยไหมคะ";
  waking turns on the "โหมดปลุก" switch for a continuous conversation; "Stop Jarvis" /
  "จาร์วิส หยุดการทำงาน" / "จบการทำงาน" goes back to waiting (mic stays on); 60 s of silence also sleeps. The wake phrase wakes it at once
  (first transcript that has it); a command is sent after 3.5 s without speech (`SETTLE_MS`), so pausing mid-sentence doesn't cut it short. One dashboard tab
  listens at a time and JARVIS's own replies are ignored as commands. The listener also checks the recognizer's
  alternative transcripts for the wake word, recycles an idle session every 45 s and restarts itself if it stops.
- Document replies are one sentence on every channel: draft "ร่าง<ประเภท>ของ<ลูกค้า> ยืนยันไหมคะ TK", issued
  "ออก<ประเภท>ของ<ลูกค้า>เรียบร้อยแล้วค่ะ TK"; no address, items, amounts or document number unless the owner asks.
- VAT: quotations have 7% VAT on top by default (FlowAccount product prices exclude VAT; vat_inclusive only when the owner
  says a price includes it). Billing notes, tax invoices and receipts follow the customer's latest document (`last_order`,
  which skips cancelled drafts); a new customer gets VAT. A quotation draft with VAT adds a third button "ไม่เอาแวท"
  (`confirm_choices`), which re-drafts with vat=false; a new draft cancels open drafts of the same type for that customer.
- LINE quick replies: none on ordinary answers; only "OK" / "Cancel" under a reply whose turn made a document draft
  (`prepare_document`). OK = confirm (`issue_document`), Cancel = `cancel_document` (status "cancelled", can't be issued).
  The dashboard chat shows the same buttons under its latest reply when that reply made a draft (`confirmChoices` in ChatPanel).
- Locations JARVIS sends to LINE are always a Google Maps link (not a LINE location pin).
- Pictures (customer name cards/addresses for documents): LINE keeps an image message silently for the user's next
  text (max 4, 10 min, `_pending_images` in `app/api/line.py`); the dashboard's 📎 button sends up to 4 with the message.
  `app/core/images.py` (Pillow) re-encodes them as JPEG ≤1024 px. Images go to Claude in that turn only: `_persist` stores
  a text placeholder instead, so they're never re-sent with later turns.
- Backups: `backup.bat` / the daily "JARVIS Backup" task (`backup-schedule.bat` → `backup-schedule.ps1`, 12:00 + at logon,
  StartWhenAvailable) run `app.scripts.backup` (`--auto` skips once today's is done) into `D:\JarvisClaudeBackup\<date>`:
  git bundle (after `git fetch`), `.env`, both SQLite files via the backup API, Thai restore notes; keeps 15 days.
- Ubuntu: `install-ubuntu.sh <backup folder>` sets up a Ubuntu Desktop 24.04 mini PC from a backup (bundle + .env + DBs,
  never overwriting existing data): apt packages, Node 22, Chrome, cloudflared, `jarvis.service` (systemd, port 8765),
  cron backups, no sleep, Chrome autostart. Idempotent. `.gitattributes` keeps `*.sh` LF.
- Account page (💰, admin only until the user-permission page lands): `app/services/accounting.py`, `app/api/account.py`,
  `account_models.py` in a separate SQLite file `backend/data/account/account.db` (`ACCOUNT_DATABASE_URL`, `AccountSession`),
  amounts in satang. Income = FlowAccount `/tax-invoices` + `/cash-invoices`, expenses = `/expenses` (not purchase orders),
  read daily in live mode or by the button; imported rows keep FlowAccount's amounts (only category/payee type/excluded/claimable
  change). Monthly summary: ภ.พ.30 with excess input VAT carried forward, ภ.ง.ด.3 (person) / ภ.ง.ด.53 (company), Excel tax reports
  (openpyxl, `COMPANY_NAME`/`COMPANY_TAX_ID`/`COMPANY_BRANCH`). Claimable input VAT needs the seller's 13-digit tax ID.
  Next: per-user permissions (admin sets each user's pages; Account access view-only or add-only), then receipt photos and voice.
- Personal money (💳 `#personal`, admin only): `app/services/personal.py`, `app/api/personal.py`, `personal_models.py` in
  `backend/data/personal/personal.db` (`PERSONAL_DATABASE_URL`, `PersonalSession`), slip pictures in `PERSONAL_SLIP_DIR`; both are
  in the backup. Balance = opening balance + entries on/after its date. Recording is the main OA's LINE **group "tk รับจ่าย"**
  (any group whose name has "รับจ่าย", `group_kind` "both"; a plain group, not a separate OA), answering linked admins only and
  staying quiet on ordinary chat. Slips (`app/services/slip_reader.py`, Claude JSON-schema output) work out
  the kind themselves (`guess_kind`: owner's receiver side = income, sender side = expense, both = transfer, else ask "1) รายรับ
  2) รายจ่าย"); typed lines start with รับ / จ่าย / โอน ("จ่าย ค่าข้าว 120 กสิกร", no bank = default account, "โอน 5000 กสิกร ไป
  K-SET50"), without one JARVIS asks. "ยอด" = every balance; "ยอด กรุงศรี เหลือเท่าไร" / "ยอดคงเหลือ K-SET50" = that bank or fund only. Duplicate reference = refused; unclear account = numbered question. The older groups named
  "รายรับ"/"รายจ่าย" still record with a fixed kind. Funds are accounts with bank
  `FUND_A`..`FUND_F` (real name in the nickname, matched in slips and typed lines; balance = money put in, no NAV). A transfer is
  one row but shows as รับโอน/โอนออก per account and in each account's month in/out, never in the month totals. No expense
  categories yet.
- New devices are added only by the "อัปเดตอุปกรณ์" button, never automatically.
- The IR air conditioner (Air PANASONIC via the Temp Smart Jarvis hub) can't report changes made in the
  Tuya app or with its physical remote; the dashboard/JARVIS side is the source of truth.

## Next up

Phase 2: FlowAccount is built and runs in `FLOWACCOUNT_MODE=mock`; next is testing with the owner's real
account (sandbox `https://openapi.flowaccount.com/test` first). Documents are two-step: `prepare_document`
saves a draft, `issue_document` is refused unless the draft came from an earlier message (user confirmed).
Products are copied from FlowAccount (`app/services/catalog.py`, "อัปเดตสินค้า" button) into a separate SQLite
file, `backend/data/flowaccount/catalog.db` (`CATALOG_DATABASE_URL`, `app/catalog_models.py`, `CatalogSession`), which
the owner opens with DB Browser for SQLite; named sets ("ชุด A", tables
`product_sets`/`product_set_items`, items by product name, list price unless a special price is fixed, optional
per-set `remarks` that become the document's หมายเหตุ; a short dashboard-only `description`; the dashboard shows sets
as cards with a hover/tap pop-up and edits them in `SetEditor.tsx` via `PUT /product-sets/{id}`) and
`last_order` ("เหมือนครั้งก่อน") feed `prepare_document`. The sandbox connection and test quotation work.
Phase 1 is done. LINE OA's webhook is `https://jarvis.jarvisthai.com/line/webhook`
through a named Cloudflare tunnel (Windows service, path `^/line/webhook$` → `127.0.0.1:8765`;
`start.bat` runs uvicorn on port 8765, so the dashboard is http://localhost:8765); `tunnel.bat` (quick tunnel) is the fallback. A LINE account is answered only after linking with the dashboard's 6-digit code. Remind the owner to renew the Anthropic API key
before it expires on 29 Dec 2026.
