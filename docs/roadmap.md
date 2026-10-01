# JARVIS AI Roadmap

สรุปจากเอกสารสเปคระบบ JARVIS AI (ข้อ 8) พร้อมสถานะปัจจุบัน

## เฟส 0: เตรียมโครงสร้างพื้นฐาน (2-3 สัปดาห์), ✅ เสร็จแล้ว

- [x] JARVIS Core backend (FastAPI) + โครง normalize input ของ 3 ช่องทาง (`app/core/messages.py`)
- [x] Database ตาม Data Model ข้อ 5: `users`, `devices`, `contacts`, `documents_log`, `chat_sessions`, `tokens`
- [x] Auth: JWT, สร้างบัญชีเจ้าของครั้งแรก, แยกสิทธิ์ "ควบคุมอุปกรณ์" กับ "ออกเอกสารการเงิน"
- [x] Tuya OpenAPI client (signing HMAC-SHA256, token + refresh, เก็บ token แบบเข้ารหัส)
- [x] REST API ควบคุมอุปกรณ์: sync, สถานะ, เปิด/ปิด, คำสั่ง raw, scene
- [x] โหมด mock (บ้านจำลอง) สำหรับพัฒนาโดยยังไม่มีอุปกรณ์จริง
- [x] สร้าง Cloud Project บน Tuya IoT Platform + link แอป Tuya Smart (Singapore data center)
- [x] ทดสอบกับอุปกรณ์จริงด้วย `python -m app.scripts.tuya_check` และสั่งปลั๊กผ่าน API
- [x] Tuya Pulsar รับสถานะอุปกรณ์แบบเรียลไทม์ (อัปเดต `devices` อัตโนมัติ, reconnect เอง) ทดสอบกับปลั๊กจริงแล้ว
- [x] Rate limit: สั่งอุปกรณ์ต่อผู้ใช้ และ login ต่อ IP+username

## เฟส 1: 3 ช่องทาง + ควบคุมบ้านด้วย LLM (3-4 สัปดาห์), ✅ เสร็จแล้ว

- [x] ต่อ Claude API + tool calling กลุ่ม `home_control.*` (`get_devices`, `get_device_status`, `control_device`, `list_scenes`, `set_scene`)
  - `POST /core/chat` และ `python -m app.scripts.chat <username>` ความจำระยะสั้นต่อ session (เก็บใน `chat_sessions`)
- [x] ทดสอบคุยกับอุปกรณ์จริง (เปิด/ปิดปลั๊ก, ถามกำลังไฟ, สั่งหลายตัวพร้อมกัน)
- [x] Dashboard (React + Tailwind) เวอร์ชันแรก + WebSocket (หน้าประวัติเอกสารรอเฟส 2 FlowAccount)
  - แก้ชื่อ/ห้องบนการ์ด, ปุ่มอัปเดตอุปกรณ์พร้อมสรุป, ป้ายเตือนสิทธิ์ Read
  - คุมแอร์ผ่านรีโมท IR (Dashboard + tool `control_air_conditioner`), อ่านอุณหภูมิ/ความชื้นจากตัวรีโมท IR
- [x] LINE OA (Messaging API webhook + Flex Message)
  - `POST /line/webhook` ตรวจลายเซ็น, ตอบผ่าน reply API (push เมื่อ token หมดอายุ), การ์ด Flex บอกสถานะอุปกรณ์ที่สั่ง + ปุ่มลัด
  - ตอบเฉพาะบัญชี LINE ที่เชื่อมด้วยรหัส 6 หลักจาก Dashboard, คุยต่อเนื่องจนเงียบ 30 นาที
  - URL สาธารณะผ่าน Cloudflare Tunnel (`tunnel.bat`)
  - tool `send_to_line`: สั่งด้วยเสียง/แชทให้ส่งข่าว ราคาทอง แผนที่ (ลิงก์ Google Maps) หรือรูปเข้า LINE ของตัวเอง
- [x] Voice โหมดพื้นฐาน (STT → Core → TTS) ปุ่มไมค์ในกล่องแชทบน Dashboard ใช้ Web Speech API ของเบราว์เซอร์
  - ส่ง `channel: "voice"` ให้ JARVIS ตอบสั้นแบบอ่านออกเสียงได้, พูดแทรกเพื่อหยุดเสียงตอบได้
  - เสียงตอบผู้หญิง (Google Cloud TTS, สำรองด้วย Edge Premwadee), โหมดปลุก "เฮ้ จาร์วิส / Hey Jarvis" ฟังต่อเนื่อง + ถามต่อได้โดยไม่ต้องเรียกชื่อซ้ำ

## เฟส 2: FlowAccount + Persona เลขา (3-4 สัปดาห์), กำลังทำ (รอทดสอบกับบัญชีจริง)

- [x] FlowAccount Open API (OAuth2 client-credentials) พร้อมโหมด mock, token เก็บเข้ารหัสในตาราง `tokens`
  - [ ] ทดสอบกับบัญชี FlowAccount จริง (sandbox ก่อน แล้ว production)
- [x] Tools `flowaccount.*` (ใบเสนอราคา/ใบวางบิล/ใบกำกับภาษี/ใบเสร็จ) + confirmation flow
  - `prepare_document` สร้างร่าง + สรุป, `issue_document` ออกจริงได้เฉพาะเมื่อผู้ใช้ยืนยันในข้อความถัดไป (ระบบบังคับ ไม่ใช่แค่ prompt)
  - บันทึกทุกเอกสารใน `documents_log` (ใคร/ช่องทางไหน) และแสดง "เอกสารล่าสุด" บน Dashboard
- [x] Persona / System Prompt แบบเลขา (ขั้นตอนสรุป-ยืนยัน, ห้ามเดาข้อมูลลูกค้า/ราคา)
- [x] Long-term memory เบื้องต้น (จำลูกค้าประจำใน `contacts`, ค้นด้วย `find_customers`)

## เฟส 3: ยกระดับความเป็นธรรมชาติ (2-3 สัปดาห์)

- [ ] TTS ที่เป็นธรรมชาติขึ้น + barge-in
- [ ] พฤติกรรม proactive (แจ้งบิลค้าง, สรุปยอดประจำวัน)
- [x] ข้อมูลภายนอก (หุ้น, ทอง, อากาศ, หนัง, ร้านอาหาร, ข่าว) ผ่าน web search ฝั่ง Anthropic (`web_search_20260209`) ทำล่วงหน้าตามที่ขอ

## เฟส 4: Lazada/Shopee (อนาคต)

- [ ] ดึงยอดขายผ่าน FlowAccount ก่อน (`market_get_sales_summary`, `market_get_order_detail`)
- [ ] พิจารณา Open Platform API โดยตรง

## สิ่งที่ต้องตัดสินใจ (ข้อ 9)

- แพ็กเกจ FlowAccount ที่ใช้รองรับ Open API หรือไม่
- ยื่นขอ Partner access กับ Lazada/Shopee ล่วงหน้าถ้าจะทำเฟส 4
- นโยบายว่าใครสั่งออกเอกสารได้บ้าง
