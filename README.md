# JARVIS AI

ผู้ช่วยส่วนตัวอัจฉริยะ: ควบคุมบ้าน (Tuya Smart Home), ออกเอกสารธุรกิจ (FlowAccount)
และในอนาคตดึงยอดขายจาก Lazada/Shopee ผ่าน 3 ช่องทาง: Dashboard, LINE และ Voice

แผนงานและสถานะดูได้ที่ [docs/roadmap.md](docs/roadmap.md) ตอนนี้อยู่ที่ **เฟส 0**

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
    api/                     REST endpoints (auth, devices, scenes)
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
| WS | `/ws/devices?token=` | สถานะอุปกรณ์แบบสด |

## Dashboard

ต้องมี [Node.js](https://nodejs.org) (LTS) สำหรับ build ครั้งแรกและทุกครั้งที่ frontend เปลี่ยน

```bash
cd frontend
npm install
npm run build        # สร้าง frontend/dist
```

จากนั้นรัน backend (บน Windows ดับเบิลคลิก `start.bat` ที่โฟลเดอร์หลักได้เลย) แล้วเปิด http://localhost:8000 (server จะเปิดหน้า Dashboard จาก `frontend/dist` ให้เอง)

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

ระหว่างแก้หน้าเว็บ ใช้ `npm run dev` (http://localhost:5173) ซึ่งจะส่ง API ต่อไปที่ backend :8000 ให้เอง

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
