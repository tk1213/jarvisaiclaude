# JARVIS AI Roadmap

สรุปจากเอกสารสเปคระบบ JARVIS AI (ข้อ 8) พร้อมสถานะปัจจุบัน

## เฟส 0: เตรียมโครงสร้างพื้นฐาน (2-3 สัปดาห์), โค้ดครบแล้ว รอทดสอบกับอุปกรณ์จริง

- [x] JARVIS Core backend (FastAPI) + โครง normalize input ของ 3 ช่องทาง (`app/core/messages.py`)
- [x] Database ตาม Data Model ข้อ 5: `users`, `devices`, `contacts`, `documents_log`, `chat_sessions`, `tokens`
- [x] Auth: JWT, สร้างบัญชีเจ้าของครั้งแรก, แยกสิทธิ์ "ควบคุมอุปกรณ์" กับ "ออกเอกสารการเงิน"
- [x] Tuya OpenAPI client (signing HMAC-SHA256, token + refresh, เก็บ token แบบเข้ารหัส)
- [x] REST API ควบคุมอุปกรณ์: sync, สถานะ, เปิด/ปิด, คำสั่ง raw, scene
- [x] โหมด mock (บ้านจำลอง) สำหรับพัฒนาโดยยังไม่มีอุปกรณ์จริง
- [ ] สร้าง Cloud Project บน Tuya IoT Platform + link แอป Tuya Smart (ผู้ใช้ทำ)
- [ ] ทดสอบกับอุปกรณ์จริงด้วย `python -m app.scripts.tuya_check`
- [x] Tuya Pulsar รับสถานะอุปกรณ์แบบเรียลไทม์ (อัปเดต `devices` อัตโนมัติ, reconnect เอง)
- [x] Rate limit: สั่งอุปกรณ์ต่อผู้ใช้ และ login ต่อ IP+username

## เฟส 1: 3 ช่องทาง + ควบคุมบ้านด้วย LLM (3-4 สัปดาห์)

- [ ] ต่อ Claude API + tool calling กลุ่ม `home_control.*` (`get_devices`, `get_device_status`, `control_device`, `set_scene`)
- [ ] Dashboard (React + Tailwind) เวอร์ชันแรก + WebSocket
- [ ] LINE OA (Messaging API webhook + Flex Message)
- [ ] Voice โหมดพื้นฐาน (STT → Core → TTS)

## เฟส 2: FlowAccount + Persona เลขา (3-4 สัปดาห์)

- [ ] FlowAccount Open API (OAuth2 client-credentials)
- [ ] Tools `flowaccount.*` (ใบเสนอราคา/ใบวางบิล/ใบเสร็จ) + confirmation flow
- [ ] Persona / System Prompt แบบเลขา
- [ ] Long-term memory เบื้องต้น (จำลูกค้าประจำ)

## เฟส 3: ยกระดับความเป็นธรรมชาติ (2-3 สัปดาห์)

- [ ] TTS ที่เป็นธรรมชาติขึ้น + barge-in
- [ ] พฤติกรรม proactive (แจ้งบิลค้าง, สรุปยอดประจำวัน)
- [ ] Tools `general_info.*` (วันเวลา, หุ้น, ทอง, หนัง, ร้านอาหาร) + web search fallback

## เฟส 4: Lazada/Shopee (อนาคต)

- [ ] ดึงยอดขายผ่าน FlowAccount ก่อน (`market_get_sales_summary`, `market_get_order_detail`)
- [ ] พิจารณา Open Platform API โดยตรง

## สิ่งที่ต้องตัดสินใจ (ข้อ 9)

- แพ็กเกจ FlowAccount ที่ใช้รองรับ Open API หรือไม่
- ยื่นขอ Partner access กับ Lazada/Shopee ล่วงหน้าถ้าจะทำเฟส 4
- นโยบายว่าใครสั่งออกเอกสารได้บ้าง
