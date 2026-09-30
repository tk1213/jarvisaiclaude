# JARVIS AI

ผู้ช่วยส่วนตัวอัจฉริยะ: ควบคุมบ้าน (Tuya Smart Home), ออกเอกสารธุรกิจ (FlowAccount)
และในอนาคตดึงยอดขายจาก Lazada/Shopee ผ่าน 3 ช่องทาง: Dashboard, LINE และ Voice

แผนงานและสถานะดูได้ที่ [docs/roadmap.md](docs/roadmap.md) ตอนนี้อยู่ที่ **เฟส 1** (LINE OA พร้อมใช้แล้ว ถัดไปคือเฟส 2 FlowAccount)

## โครงสร้าง

```
frontend/                    Dashboard (React + Tailwind + Vite)
  src/App.tsx                หน้าหลัก: การ์ดอุปกรณ์, scene, กล่องแชท
  src/useDevices.ts          รับสถานะอุปกรณ์สดผ่าน WebSocket
backend/
  app/
    main.py                  FastAPI app
    config.py                ตั้งค่าจาก environment / .env
    models.py                Data model (users, devices, contacts, documents_log, chat_sessions, tokens)
    security.py              รหัสผ่าน, JWT, เข้ารหัส token
    api/                     REST endpoints (auth, devices, scenes, voice, line)
    api/line.py              LINE webhook + เชื่อมบัญชี LINE ด้วยรหัส 6 หลัก
    integrations/line.py     LINE Messaging API (ตรวจลายเซ็น, reply/push, Flex Message)
    services/devices.py      logic ควบคุมอุปกรณ์ (ใช้ร่วมกับ LLM tools ในเฟส 1)
    integrations/tuya/       Tuya OpenAPI client, Pulsar (event เรียลไทม์) + mock
    ratelimit.py             จำกัดจำนวนคำสั่ง/การ login ต่อนาที
    realtime.py              ส่งการเปลี่ยนแปลงของอุปกรณ์ไปที่ Dashboard ทันที
    core/messages.py         รูปแบบข้อความกลางของทุกช่องทาง
    core/orchestrator.py     สมองของ JARVIS: คุยกับ Claude + เรียก tools + จำบทสนทนา
    core/tools.py            เครื่องมือ home_control ที่ Claude เรียกใช้ได้
    core/prompts.py          บุคลิก/System prompt ของ JARVIS
    scripts/chat.py          คุยกับ JARVIS จาก command line
    scripts/tuya_check.py    ทดสอบคุม Tuya ตรงๆ จาก command line
  tests/
```

## เริ่มใช้งาน

```bash
cp .env.example .env        # แล้วแก้ JWT_SECRET และ ENCRYPTION_KEY
docker compose up --build   # Postgres + JARVIS Core ที่ http://localhost:8000
```

เปิด http://localhost:8000/docs เพื่อลอง API ผ่าน Swagger UI

รันโดยไม่ใช้ Docker (ต้องมี Postgres หรือตั้ง `DATABASE_URL=sqlite:///./jarvis.db`):

```bash
cd backend
pip install -e '.[dev]'
uvicorn app.main:app --reload
pytest
```

### ขั้นตอนแรก

```bash
# 1. สร้างบัญชีเจ้าของ (ทำได้ครั้งเดียว)
curl -X POST localhost:8000/auth/bootstrap -H 'Content-Type: application/json' \
  -d '{"username":"owner","password":"your-password"}'

# 2. Login รับ token
TOKEN=$(curl -s -X POST localhost:8000/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"owner","password":"your-password"}' | python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

# 3. ดึงรายการอุปกรณ์จาก Tuya เข้าฐานข้อมูล แล้วลองเปิดเครื่องแรก
curl -X POST localhost:8000/devices/sync -H "Authorization: Bearer $TOKEN"
curl -X POST localhost:8000/devices/1/power -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"on":true}'
```

## API (เฟส 0)

| Method | Path | ใช้ทำอะไร |
|---|---|---|
| POST | `/auth/bootstrap` | สร้างบัญชีเจ้าของคนแรก |
| POST | `/auth/login` | รับ JWT |
| GET | `/auth/me` | ข้อมูลผู้ใช้ปัจจุบัน |
| GET/POST | `/users` | ดู/เพิ่มผู้ใช้ (admin) |
| POST | `/devices/sync` | ดึงอุปกรณ์และห้องจาก Tuya |
| GET | `/devices?name=&room=` | ค้นหาอุปกรณ์ |
| GET | `/devices/{id}?refresh=true` | สถานะอุปกรณ์ (ดึงสดจาก Tuya ได้) |
| PATCH | `/devices/{id}` | แก้ชื่อ/ห้อง |
| POST | `/devices/{id}/power` | เปิด/ปิด (เลือก code ให้อัตโนมัติ) |
| POST | `/devices/{id}/commands` | ส่งคำสั่ง Tuya แบบ raw |
| GET | `/scenes` | รายการ scene |
| POST | `/scenes/{scene_id}/trigger` | สั่ง scene |
| POST | `/core/chat` | คุยกับ JARVIS |
| POST | `/line/webhook` | รับข้อความจาก LINE OA (ตรวจลายเซ็น) |
| GET/POST/DELETE | `/line/status`, `/line/link-code`, `/line/link` | เชื่อม/ยกเลิกบัญชี LINE |
| WS | `/ws/devices?token=` | สถานะอุปกรณ์แบบสด |

## Dashboard

ต้องมี [Node.js](https://nodejs.org) (LTS) สำหรับ build ครั้งแรกและทุกครั้งที่ frontend เปลี่ยน

```bash
cd frontend
npm install
npm run build        # สร้าง frontend/dist
```

จากนั้นรัน backend (บน Windows ดับเบิลคลิก `start.bat` ที่โฟลเดอร์หลักได้เลย) แล้วเปิด http://localhost:8765 (`start.bat` รันที่พอร์ต 8765; server จะเปิดหน้า Dashboard จาก `frontend/dist` ให้เอง)

- การ์ดอุปกรณ์พร้อมปุ่มเปิด/ปิด ค่ากำลังไฟ/แรงดัน/อุณหภูมิ และสถานะออนไลน์ จัดกลุ่มตามห้อง
- ปุ่มดินสอบนการ์ด: แก้ชื่อและห้อง (ค่าที่แก้จะไม่ถูกทับตอนอัปเดตจาก Tuya และ JARVIS ใช้ห้องในการเข้าใจคำสั่ง)
- ปุ่ม "อัปเดตอุปกรณ์": ดึงรายการจาก Tuya แล้วสรุปว่าเพิ่ม/นำออกอะไร (อุปกรณ์ใหม่ต้องจับคู่ในแอป Tuya Smart ก่อน)
- ป้ายเตือนเมื่อ Tuya ปฏิเสธคำสั่งเพราะสิทธิ์เป็น Read พร้อมวิธีแก้
- แอร์ที่สั่งผ่านรีโมท IR: เปิด/ปิด, ปรับอุณหภูมิ 16-30 °C, โหมด และความแรงลม

### รีโมท IR (เช่น Smart IR ที่มีเทอร์โมมิเตอร์)

1. ในแอป Tuya Smart เข้าอุปกรณ์รีโมท IR แล้วเพิ่มรีโมท (เช่น แอร์ยี่ห้อที่ใช้) ทดสอบให้เครื่องตอบสนอง
2. iot.tuya.com > Cloud > Cloud Services สมัคร **IR Control Hub Open Service** (Free Trial)
   แล้วแท็บ Authorized Projects เพิ่มโปรเจกต์ของเรา
3. ตั้ง Device Permission ของตัวรีโมท IR และแอร์เป็น Controllable
4. กด "อัปเดตอุปกรณ์" บน Dashboard ระบบจะผูกแอร์เข้ากับตัวส่ง IR ให้เอง
5. ตรวจได้ด้วย `python -m app.scripts.tuya_check ir <device_id ของตัวรีโมท IR>`

Tuya ไม่ส่ง event เมื่อสั่งแอร์ IR จากแอป Tuya Smart ระบบจึงถามสถานะแอร์จาก Tuya ทุก 30 วินาที
(ปรับได้ที่ `IR_AC_POLL_SECONDS`, `0` = ปิด) การ์ดบน Dashboard จะเปลี่ยนตามภายในเวลานั้น
ส่วนการกดรีโมทตัวจริงที่ตัวแอร์ ระบบจะไม่รู้ เพราะ IR เป็นสัญญาณทางเดียว
- อัปเดตสดผ่าน WebSocket `/ws/devices` ไม่ว่าจะกดจากแอป, ตัวอุปกรณ์ หรือสั่งผ่าน JARVIS
- ปุ่ม scene และกล่องแชทคุยกับ JARVIS

### สั่งด้วยเสียง

กดปุ่มไมค์ข้างช่องพิมพ์ แล้วพูดได้เลย (เช่น "เปิดแอร์ 25 องศา") พูดจบระบบจะส่งให้ JARVIS เองและอ่านคำตอบออกเสียง

- ใช้ Chrome หรือ Edge (การฟังเสียงพูดยังไม่รองรับใน Firefox)
- ครั้งแรกเบราว์เซอร์จะถามสิทธิ์ไมโครโฟน ให้กด Allow
- การแปลงเสียงเป็นข้อความใช้บริการของเบราว์เซอร์ จึงต้องต่ออินเทอร์เน็ต
- ใช้ได้ที่ `http://localhost` เท่านั้น ถ้าจะเปิดจากเครื่องอื่นต้องเป็น `https`
- กดไมค์ระหว่าง JARVIS พูดเพื่อพูดแทรก หรือกด "หยุดพูด" ที่หัวกล่องแชท

#### โหมดปลุก ("Hey Jarvis")

ที่หัวกล่องแชทมี 2 ปุ่ม

- **🎙 ปุ่มไมค์รอเรียก:** เปิดไว้แล้วไมค์จะฟังเฉพาะคำว่า **"Hey Jarvis"** / **"เฮ้ จาร์วิส"** (พูดชื่อเฉยๆ ไม่ปลุก) จำสถานะไว้หลังรีเฟรช
- **สวิตช์โหมดปลุก:** เปิดเองเมื่อได้ยิน "Hey Jarvis" (หรือกดเอง) ระหว่างเปิดอยู่พูดคำสั่งต่อเนื่องได้เลยโดยไม่ต้องเรียกชื่อ
  - พูด "Hey Jarvis เปิดแอร์ 25 องศา" ได้ในประโยคเดียว
  - ปิดด้วย **"Stop Jarvis"** / "จาร์วิส หยุดการทำงาน" หรือกดสวิตช์ แล้วกลับไปรอ "Hey Jarvis" (ไมค์ยังเปิดอยู่)
  - ไม่มีใครพูดกับ JARVIS 1 นาที จะพักเอง (กันเสียงทีวีถูกนับเป็นคำสั่ง)
- ในแชทจะมีบรรทัดบอกทุกครั้งที่ตื่น/พัก และคำที่กำลังพูดขึ้นเป็นกล่องขอบประ
- ระหว่าง JARVIS คิดหรือพูด ระบบหยุดฟังชั่วคราว (ไม่ให้ได้ยินเสียงตัวเอง)
- เปิด Dashboard หลายแท็บได้ แต่ไมค์จะฟังทีละแท็บ (แท็บที่เปิดล่าสุด หรือกดปุ่ม 🎙 เพื่อย้ายมาแท็บนี้) ทุกแท็บหยุดฟังระหว่างที่ JARVIS พูด และไม่รับคำตอบของ JARVIS เองเป็นคำสั่ง
- ถ้าเสียงผู้หญิงจาก server ใช้ไม่ได้ จะแสดงคำตอบเป็นข้อความอย่างเดียว ไม่ใช้เสียงผู้ชายของเบราว์เซอร์
- ต้องเปิดหน้า Dashboard ค้างไว้ ระหว่างไมค์เปิด เสียงถูกส่งไปแปลงเป็นข้อความที่บริการของเบราว์เซอร์ (Google สำหรับ Chrome) ตลอดเวลา ปิดปุ่ม 🎙 เมื่อไม่ใช้

#### เสียงตอบ

**แนะนำ: เสียงของ Google (ทางการ เสถียร)** ใส่ `GOOGLE_TTS_API_KEY` แล้วระบบจะใช้ Google ก่อน ถ้าใช้ไม่ได้ค่อยใช้เสียง Edge ด้านล่าง

1. https://console.cloud.google.com เลือกโปรเจกต์ (ต้องเปิด billing แต่ใช้ฟรีเดือนละ 1 ล้านตัวอักษรสำหรับเสียง Neural2)
2. APIs & Services > Library ค้นหา **Cloud Text-to-Speech API** กด Enable
3. APIs & Services > Credentials > Create credentials > API key ตั้ง API restrictions ให้ใช้ได้แค่ Cloud Text-to-Speech API
4. ใส่ `GOOGLE_TTS_API_KEY=...` ใน `backend/.env` แล้วเปิด server ใหม่ (log จะขึ้น `speaking with Google ...`)
- ปรับเสียง: `GOOGLE_TTS_VOICE` (ค่าเริ่มต้น `th-TH-Neural2-C` เสียงผู้หญิง), `GOOGLE_TTS_PITCH` (semitone), ความเร็วใช้ `TTS_RATE`/`TTS_NUMBER_RATE` ร่วมกัน

**สำรอง: เสียง Edge (ฟรี ไม่ต้องมี key แต่บางช่วงไม่ตอบ)**

ค่าเริ่มต้นใช้เสียงผู้หญิง **Premwadee** (neural) ของ Microsoft Edge ผ่าน server (แพ็กเกจ `edge-tts`)
ฟรี ไม่ต้องมี key และได้เสียงเดียวกันไม่ว่าจะเปิดด้วยเบราว์เซอร์ไหน ปรับให้แหลมขึ้นเล็กน้อยให้ฟังสดใส และพูดช้าลงเล็กน้อยให้ฟังชัด

- ตัวเลขอ่านช้าลงให้ฟังทัน (`TTS_NUMBER_RATE=-30%`) และเสียงเริ่มเล่นระหว่างที่ server ยังสร้างเสียงส่วนที่เหลืออยู่
- ปรับได้ใน `.env`: `TTS_RATE=-8%` (ความเร็ว: +0% = ปกติ, ลบ = ช้าลง, ช้าสุด -50%), `TTS_PITCH=+15Hz` (ระดับเสียง: +0Hz ถึงบวก, เสียงไทยของ Edge ไม่รองรับค่าติดลบ) แล้วเปิด server ใหม่
- เป็นบริการ "อ่านออกเสียง" ของ Edge ที่ไม่ได้เปิดเป็น API ทางการ ถ้าวันหนึ่งใช้ไม่ได้ ระบบจะกลับไปใช้เสียงของเบราว์เซอร์ให้เอง
  (หรือตั้ง `TTS_ENGINE=browser`)

ระหว่างแก้หน้าเว็บ ใช้ `npm run dev` (http://localhost:5173) ซึ่งจะส่ง API ต่อไปที่ backend :8765 ให้เอง

## คุยกับ JARVIS (เฟส 1)

ใส่ `ANTHROPIC_API_KEY` ใน `.env` แล้วลองได้ 2 ทาง:

```bash
cd backend
python -m app.scripts.chat <username>      # คุยใน terminal
```

หรือ `POST /core/chat` ใน `/docs` ด้วย body `{"text": "เปิดปลั๊ก 2 หน่อย"}` (ครั้งต่อไปส่ง `session_id` จากคำตอบกลับไปด้วยเพื่อคุยต่อเนื่อง)

- ใช้โมเดล `claude-opus-5-5` (เปลี่ยนได้ที่ `CLAUDE_MODEL`) effort `low` เพื่อให้ตอบเร็ว
- เปิด server-side fallback ไว้: ถ้าโมเดลหลักปฏิเสธคำขอ ระบบจะลองโมเดลสำรองให้อัตโนมัติ
- ประวัติการคุยเก็บแบบเพิ่มต่อท้ายอย่างเดียว (append-only) ในตาราง `chat_sessions` ห้ามแก้แถวเก่า
  เพราะ Claude ผูก thinking กับบทสนทนาที่ส่งไปแบบตรงทุกไบต์

### ถามเรื่องนอกบ้าน

JARVIS ค้นเว็บเองได้ (web search ของ Anthropic) เช่น "ราคาทองวันนี้", "หุ้น PTT เท่าไหร่", "พรุ่งนี้ฝนตกไหม", "หนังอะไรเข้าโรง", "ร้านอาหารแถวสีลม"
คำตอบบอกแหล่งที่มาและเวลาของข้อมูล และในแชทจะมีป้าย "ค้นเว็บ"

- ถ้าผู้ดูแลองค์กรปิด web search ไว้ใน Claude Console ต้องเปิดก่อน ไม่อย่างนั้น JARVIS จะตอบว่าค้นไม่ได้
- คิดเงินเพิ่มตามจำนวนครั้งที่ค้น ตั้งได้ด้วย `WEB_SEARCH_MAX_USES` (ค่าเริ่มต้น 3 ต่อคำตอบ) หรือปิดด้วย `WEB_SEARCH_ENABLED=false`
- การค้นทำให้ตอบช้าลงอีกไม่กี่วินาที

## LINE OA (เฟส 1)

คุยกับจาร์วิสผ่านแชท LINE ได้เหมือนบน Dashboard (สั่งอุปกรณ์, ถามสถานะ, ค้นเว็บ) พอสั่งอุปกรณ์แล้วจะตอบเป็นการ์ด (Flex Message)
บอกสถานะเปิด/ปิดของอุปกรณ์ที่เพิ่งสั่ง และมีปุ่มลัด "สถานะบ้าน", "ปิดทุกอย่าง", "อุณหภูมิตอนนี้" ใต้คำตอบ

**ความปลอดภัย:** จาร์วิสตอบเฉพาะบัญชี LINE ที่เชื่อมกับผู้ใช้ JARVIS แล้วเท่านั้น คนอื่นที่แอด OA สั่งบ้านไม่ได้
และทุกคำขอจาก LINE ต้องมีลายเซ็นที่ถูกต้องจาก Channel secret

### ตั้งค่าครั้งแรก

1. สร้าง LINE Official Account ที่ [LINE Official Account Manager](https://manager.line.biz)
   แล้วไปที่ **ตั้งค่า > Messaging API > เปิดใช้ Messaging API** (เลือกหรือสร้าง Provider)
2. เปิด [LINE Developers Console](https://developers.line.biz/console/) เลือก channel ของ OA
   - แท็บ **Basic settings**: คัดลอก **Channel secret**
   - แท็บ **Messaging API**: กด **Issue** ที่ **Channel access token (long-lived)** แล้วคัดลอก
3. ใส่ใน `backend\.env` แล้วปิด-เปิด `start.bat` ใหม่
   ```
   LINE_CHANNEL_SECRET=...
   LINE_CHANNEL_ACCESS_TOKEN=...
   ```
4. เปิด URL สาธารณะ (https) ให้ LINE ส่งข้อความเข้ามาได้ ด้วย Cloudflare Tunnel
   - ติดตั้งครั้งเดียว: `winget install --id Cloudflare.cloudflared`
   - ดับเบิลคลิก `tunnel.bat` (เปิดไว้คู่กับ `start.bat`) แล้วคัดลอกที่อยู่ `https://....trycloudflare.com` ที่ขึ้นมา
5. LINE Developers Console แท็บ **Messaging API > Webhook settings**
   - Webhook URL: `https://....trycloudflare.com/line/webhook` แล้วกด **Verify** ต้องขึ้น Success
   - เปิด **Use webhook**
6. LINE Official Account Manager **ตั้งค่า > การตอบกลับ**: ปิด **ข้อความตอบกลับอัตโนมัติ** และ **ข้อความทักทาย**
   (ไม่อย่างนั้น LINE จะตอบซ้ำกับจาร์วิส) และเปิด **Webhook**
7. แอดเพื่อน OA (QR ในแท็บ Messaging API) แล้วบน Dashboard กดปุ่ม **LINE** ที่มุมบน > **ขอรหัสเชื่อม LINE**
   ส่งรหัส 6 หลักในแชท OA ภายใน 10 นาที จาร์วิสจะตอบว่าเชื่อมแล้ว

### การใช้งาน

- พิมพ์คำสั่งได้เลย เช่น "เปิดปลั๊ก 2", "อุณหภูมิห้องทำงาน", "ราคาทองวันนี้"
- คุยต่อเนื่องได้ จาร์วิสจำบทสนทนาจนกว่าจะเงียบ 30 นาที (`LINE_SESSION_IDLE_MINUTES`) พิมพ์ **"เริ่มใหม่"** เพื่อเริ่มบทสนทนาใหม่ทันที
- ระหว่างคิดจะขึ้นจุด "..." ในแชท ถ้าตอบช้าจน reply token หมดอายุ ระบบจะส่งแบบ push แทน (นับโควตาข้อความของ OA)
- รับเฉพาะแชทส่วนตัว ในกลุ่มจาร์วิสจะไม่ตอบ และตอนนี้อ่านได้แค่ข้อความตัวอักษร (ยังไม่รับรูปหรือเสียง)
- ยกเลิกการเชื่อมได้ที่ปุ่ม **LINE** บน Dashboard

**หมายเหตุ Cloudflare Tunnel:** ที่อยู่ `trycloudflare.com` เปลี่ยนทุกครั้งที่เปิด `tunnel.bat` ใหม่ ต้องไปแก้ Webhook URL ทุกครั้ง
เมื่อเปิด tunnel แล้ว Dashboard จะเข้าจากอินเทอร์เน็ตได้ด้วย (ต้อง login ทุกครั้ง) จึงควรตั้งรหัสผ่านที่เดายาก

### ใช้โดเมนของตัวเองแบบถาวร (แนะนำ)

ถ้าโดเมนอยู่ใน Cloudflare แล้ว ทำ tunnel ถาวรที่รันเป็น Windows service (เปิดเองทุกครั้งที่เปิดเครื่อง ไม่ต้องใช้ `tunnel.bat`)

1. [dash.cloudflare.com](https://dash.cloudflare.com) > **Zero Trust** > **Networks** > **Tunnels** > **Create a tunnel** > **Cloudflared** ตั้งชื่อ `jarvis`
2. เลือก **Windows** แล้วคัดลอกคำสั่ง `cloudflared.exe service install <token>` ไปรันใน PowerShell แบบ **Run as Administrator**
   (token เป็นความลับ ห้ามส่งให้ใคร) รอจนหน้าเว็บขึ้นว่า Connector **Connected**
3. **Public Hostname**: Subdomain `jarvis`, Domain โดเมนของเรา, Service Type `HTTP`, URL `localhost:8765`
   (ใส่ Path `^/line/webhook$` ได้ เพื่อให้อินเทอร์เน็ตเข้าได้แค่ webhook ไม่ใช่ Dashboard)
   (ถ้าขึ้นว่ามี DNS record ชื่อนี้อยู่แล้ว ให้ลบ record เดิมในหน้า DNS ก่อน)
4. ถ้าไม่ได้ใส่ Path เปิด `https://jarvis.<โดเมน>/health` ต้องได้ `{"status":"ok",...}` (ต้องเปิด `start.bat` อยู่)
5. แก้ Webhook URL ใน LINE Developers เป็น `https://jarvis.<โดเมน>/line/webhook` แล้วกด **Verify**

## ต่อ Tuya จริง

1. สมัคร [Tuya IoT Platform](https://iot.tuya.com) แล้วสร้าง **Cloud Project** (Smart Home, เลือก data center ให้ตรงกับ Region ของบัญชีแอป)
2. เปิด API services: IoT Core, Authorization, Smart Home Scene Linkage
3. ที่ **Devices > Link App Account** สแกน QR ด้วยแอป Tuya Smart / Smart Life
   แล้วตรวจคอลัมน์ **Device Permission** ของอุปกรณ์ที่จะสั่งงานให้เป็น **Controllable** (ถ้าเป็น Read ให้กด Change)
4. ใส่ `TUYA_ACCESS_ID`, `TUYA_ACCESS_SECRET`, `TUYA_ENDPOINT`, `TUYA_USER_UID` ใน `.env` แล้วตั้ง `TUYA_MODE=live`
   (UID อยู่ในแท็บ Link App Account; Singapore ใช้ `TUYA_ENDPOINT=https://openapi-sg.iotbing.com`)
5. ทดสอบโดยยังไม่ต้องใช้ LLM:

```bash
cd backend
python -m app.scripts.tuya_check              # รายการอุปกรณ์ + สถานะ
python -m app.scripts.tuya_check on <device_id>
python -m app.scripts.tuya_check scenes
```

### สถานะแบบเรียลไทม์ (Message Service / Pulsar)

เมื่อรัน server ในโหมด `live` ระบบจะต่อ Tuya Pulsar ให้อัตโนมัติ เวลามีคนกดสวิตช์ที่ตัวอุปกรณ์หรือในแอป
สถานะในตาราง `devices` จะอัปเดตเอง ต้องตั้งค่าในโปรเจกต์ก่อน 3 อย่าง:

1. แท็บ **Message Service** กดสวิตช์ **Enable** (ถ้ายังปิดอยู่ log จะขึ้น `HTTP 401`)
2. **Messaging Rules → Production Environment → Create Messaging Rules** เลือก BizCode
   `deviceOnline`, `deviceOffline`, `devicePropertyMessage` แล้วกด **Release Rule**
3. **เปิดสวิตช์** หน้า rule ของ Production ให้ขึ้นว่า *rules ... are in effect* (ถ้าปิดอยู่จะไม่มีข้อความส่งมา)

ตรวจผล:
- log ต้องขึ้น `connected to Tuya Pulsar` และแท็บ Subscription Management (Production) ต้องเห็น Consumers = 1
- กดอุปกรณ์จากแอปแล้ว log ต้องขึ้น `Tuya event received: {...}`
- ถ้าหลุด ระบบจะต่อใหม่เองโดยรอนานขึ้นเรื่อยๆ สูงสุด 60 วินาที

## ความปลอดภัย

- endpoint ที่สั่งอุปกรณ์จำกัด 30 ครั้ง/นาที/ผู้ใช้ และ login จำกัด 5 ครั้ง/นาที ต่อ IP+username (ปรับได้ใน `.env`) เกินแล้วได้ `429`
- ตัวนับเก็บในหน่วยความจำของ process เดียว ถ้าจะรันหลาย instance ต้องย้ายไป Redis
- ในโหมด `live` server จะไม่ยอมเริ่มถ้ายังไม่ได้เปลี่ยน `JWT_SECRET`
