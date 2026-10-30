# SPEC — Smart Parking (ระบบตรวจนับที่จอดรถว่างด้วยกล้อง IP)

> สถานะเอกสาร: Draft v0.1 (ออกแบบก่อนเขียนโค้ด) — 2026-10-06
> ภาษาเอกสาร: ไทย (ศัพท์เทคนิคใช้ภาษาอังกฤษ)

---

## 1. เป้าหมาย (Goals)

1. ตรวจสถานะ **ทุกช่องจอดรถยนต์** (ว่าง / มีรถ) จากกล้อง IP เดิมของลูกค้า แล้วสรุปเป็นจำนวนที่จอดว่าง
2. แสดงผลให้ **คนทั่วไปดูผ่านเว็บไซต์** (มือถือเป็นหลัก) ทั้งจำนวนรวมทั้งลาน และแยกตามโซน/ชั้น อัปเดตทุก ~30 วินาที
3. มี **ระบบหลังบ้าน** ให้ Admin กำหนดตำแหน่งช่องจอดได้ 3 วิธี: วาดเอง / ระบบเสนอจากการสังเกตรถจริง / ระบบเสนอจากเส้นช่องจอด แล้ว Admin อนุมัติ
4. ทุกอย่างรันบน **Server เครื่องเดียวที่ site ลูกค้า** ติดตั้งซ้ำได้ง่ายด้วย Docker (แต่ละ site แยกอิสระ)
5. โค้ดเป็น **Python** อ่านง่าย ผู้พัฒนาระดับเริ่มต้นดูแลต่อได้

### Non-goals (ไม่อยู่ในขอบเขต)

- อุปกรณ์อื่น: ไม้กั้น, ป้าย/จอแสดงจำนวน, เซนเซอร์ช่องจอด
- การนับรถจักรยานยนต์
- อ่านป้ายทะเบียน (LPR), คิดค่าจอด, จองที่จอด
- การแจ้งเตือนนอกระบบ (LINE/Email) — แสดงในหลังบ้านเท่านั้น
- หน้ารวมหลาย site (ไว้เฟสอนาคต)
- เผยแพร่ภาพจากกล้องสู่สาธารณะ

---

## 2. ข้อมูลตั้งต้นและสมมติฐาน (จากการสอบถาม)

| หัวข้อ | ค่า |
|---|---|
| ขนาดลาน | กลาง: 50–200 ช่อง, กล้อง 3–8 ตัว (ออกแบบให้ขยายถึง ~12 ตัวได้) |
| กล้อง | กล้องเดิมที่ติดตั้งแล้ว Hikvision / Dahua, ดึง RTSP ตรงจากกล้อง, ยังไม่ทราบมุม |
| วิธีนับ | ตรวจทีละช่อง (per-slot occupancy) |
| ความถี่อัปเดต | 30 วินาที |
| แสง | กลางวันเป็นหลัก กลางคืนมีไฟส่องสว่าง |
| ประเภทช่อง | ปกติ, คนพิการ/ผู้สูงอายุ, EV ชาร์จ, สงวน/VIP |
| หน้าเว็บสาธารณะ | ตัวเลขว่างรวมทั้งลาน + แยกโซน/ชั้น, ภาษาไทย + อังกฤษ, ไม่แสดงภาพ |
| กล้องหลุด | โซนนั้นแสดง "ไม่มีข้อมูล" และไม่นับรวม |
| ผู้ใช้หลังบ้าน | 2 ระดับ: Admin, Operator |
| รายงาน | กราฟอัตราการใช้งานรายชั่วโมง/วัน ในหลังบ้าน (เก็บเฉพาะตัวเลข) |
| การเข้าถึงจากภายนอก | Public IP + Port forward ที่เราเตอร์, มี domain, HTTPS ด้วย Let's Encrypt |
| ภาษาโปรแกรม | Python |
| การติดตั้งหลาย site | ใช่ แต่ละ site แยกอิสระ |

**สมมติฐานเพิ่มเติม** (ต้องยืนยันตอนสำรวจหน้างาน)

- A1: กล้องความละเอียดอย่างน้อย 2MP (1920×1080) และเปิด RTSP ได้
- A2: Server เข้าถึงวงกล้องได้ผ่าน LAN/VLAN
- A3: กล้องเดิม **อาจมองไม่เห็นทุกช่อง** — ช่องที่มองไม่เห็นจะไม่ถูกนับ ระบบต้องรายงาน "ความครอบคลุม" ให้เห็นชัด (ดูข้อ 11 Site Survey)
- A4: รถที่อยู่ไกลจากกล้องมากจนสูงน้อยกว่า ~40 px ในภาพ ถือว่าเชื่อถือไม่ได้

---

## 3. ภาพรวมสถาปัตยกรรม

```
                       Internet (คนทั่วไป / Admin)
                                │  HTTPS 443 (+80 สำหรับ Let's Encrypt)
                         ┌──────┴──────┐
                         │   Router    │  port forward 80,443 → Server
                         └──────┬──────┘
 ┌──────────────────────────────┼─────────────────────────────────┐
 │ Server @ Site (Ubuntu 24.04 + Docker Compose)                  │
 │                                                                 │
 │  ┌─────────┐   ┌──────────────────────┐   ┌──────────────────┐ │
 │  │  caddy  │──▶│ web (FastAPI)        │   │ worker (Python)  │ │
 │  │ HTTPS   │   │ - หน้าเว็บสาธารณะ      │   │ - ดึงภาพจากกล้อง     │ │
 │  └─────────┘   │ - Public API         │   │ - ตรวจจับรถ (AI)     │ │
 │                │ - หลังบ้าน Admin/Op   │   │ - คำนวณสถานะช่อง    │ │
 │                └──────────┬───────────┘   │ - งานกึ่งออโต้        │ │
 │                           │               │ - health / สถิติ    │ │
 │                           ▼               └────────┬─────────┘ │
 │                 ┌───────────────────────────────────┴───┐      │
 │                 │ data volume: SQLite DB + snapshots     │      │
 │                 └───────────────────────────────────────┘      │
 └───────────────────────────────┬────────────────────────────────┘
                                 │ RTSP (LAN / Camera VLAN)
              ┌──────────┬───────┴───┬──────────┐
            Cam 1      Cam 2       Cam 3  ...  Cam N  (Hikvision/Dahua)
```

### 3.1 Services (Docker Compose)

| Service | หน้าที่ | หมายเหตุ |
|---|---|---|
| `caddy` | Reverse proxy, ออก/ต่ออายุใบรับรอง Let's Encrypt อัตโนมัติ | ตั้งค่าง่ายกว่า nginx+certbot |
| `web` | FastAPI: หน้าเว็บสาธารณะ, Public API, หน้าหลังบ้าน, Admin API | ไม่ทำงานหนัก ตอบเร็ว |
| `worker` | วนลูกทุก 30 วิ: ดึงภาพ → ตรวจจับ → คำนวณสถานะ → เขียน DB; รันงาน calibration, health check, สรุปสถิติ | แยกจาก web เพื่อไม่ให้งาน AI ทำเว็บช้า |

`web` กับ `worker` สื่อสารกันผ่าน **ฐานข้อมูลอย่างเดียว** (ไม่มี message queue) เพื่อความเรียบง่าย — worker อ่านค่า config/layout จาก DB ทุกรอบ และเขียนผลลง DB, web อ่านผลไปแสดง

### 3.2 Tech stack

| ส่วน | เลือกใช้ | เหตุผล |
|---|---|---|
| ภาษา | Python 3.12 | ตามความถนัดผู้พัฒนา |
| Web framework | FastAPI + Uvicorn + Jinja2 templates | เขียนง่าย มี docs API อัตโนมัติ |
| Frontend | HTML + Jinja2 + Alpine.js (เล็ก), Konva.js (วาดกรอบ), Chart.js (กราฟ) | ไม่ต้อง build/Node.js |
| Database | SQLite (WAL mode) + SQLAlchemy + Alembic | ไม่มี server DB ให้ดูแล, ข้อมูลไม่ใหญ่ |
| ดึงภาพ | ffmpeg (ดึง 1 เฟรมจาก RTSP) / OpenCV | เสถียรกับ Hikvision/Dahua |
| AI ตรวจจับรถ | ONNX Runtime (+ OpenVINO EP บน Intel CPU) | รันบน CPU ได้ดี, เปลี่ยนโมเดลได้ |
| โมเดล | YOLOX-s / YOLOX-m (Apache-2.0) ที่ export เป็น ONNX | ดูหมายเหตุ License ด้านล่าง |
| เรขาคณิต | Shapely (polygon intersection), NumPy | |
| กึ่งออโต้ (เส้นช่อง) | OpenCV (CLAHE, Canny, HoughLinesP) | |
| Reverse proxy | Caddy 2 | HTTPS อัตโนมัติ |
| Deploy | Docker Compose | ติดตั้งซ้ำหลาย site ง่าย |
| ส่งออกรายงาน Excel | openpyxl (MIT) | สร้างไฟล์ .xlsx ตาม TOR 4.5 (เพิ่ม 2026-10-28) |
| Test | pytest | |

> ⚠️ **License โมเดล:** Ultralytics YOLO (v8/11) ใช้ง่ายที่สุดแต่เป็น **AGPL-3.0** — ถ้านำระบบไปขาย/ติดตั้งให้ลูกค้าโดยไม่เปิดซอร์สทั้งระบบ ต้องซื้อ Enterprise License จึงออกแบบให้ใช้โมเดล License แบบ Apache-2.0 (เช่น YOLOX) ผ่าน ONNX และแยก `Detector` เป็น interface เพื่อสลับโมเดลได้ภายหลัง (**ต้องตัดสินใจ D-1**)

---

## 4. แนวคิดหลักและข้อมูล (Domain)

- **Site** — ลานจอด 1 แห่ง = การติดตั้ง 1 ชุด (ไม่มี multi-tenant ในโค้ด)
- **Zone** — โซน/ชั้น เช่น "ชั้น 1", "โซน A" ใช้แสดงผลสาธารณะ
- **Camera** — กล้อง 1 ตัว มองเห็นได้หลายโซน
- **Slot** — ช่องจอด 1 ช่อง = polygon บนภาพของกล้อง 1 ตัว, สังกัด 1 โซน, มีประเภท (type)
- **Slot types:** `normal`, `disabled` (คนพิการ/ผู้สูงอายุ), `ev`, `reserved` (สงวน/VIP — **ไม่นับเป็นที่ว่างสาธารณะ**, แสดงเฉพาะหลังบ้าน)
- **Slot state:** `free`, `occupied`, `unknown`
- **Layout** — ชุดของ slot ของกล้อง 1 ตัว มีสถานะ `draft` (กำลังแก้) และ `published` (ใช้งานจริง); แก้ draft ไม่กระทบตัวเลขหน้าเว็บจนกว่าจะกด Publish
- **Proposal** — กรอบช่องที่ระบบเสนอ (จากโหมดกึ่งออโต้) รอ Admin อนุมัติ
- **Override** — Operator บังคับสถานะช่องชั่วคราว (เช่น ปิดซ่อม, วางกรวย) มีเวลาหมดอายุ

**ข้อกำหนดพิกัด:** polygon เก็บเป็นพิกัด **normalized 0–1** เทียบกับขนาดภาพ เพื่อไม่พังเมื่อเปลี่ยนความละเอียด/สตรีม

**ช่องที่กล้องเห็นซ้ำกัน:** 1 ช่องผูกกับกล้องหลัก 1 ตัวเท่านั้น (เวอร์ชันแรก) — ห้ามวาดช่องเดียวกันบน 2 กล้อง ระบบตรวจรหัสช่องซ้ำให้

---

## 5. Functional Requirements

### 5.1 การดึงภาพและตรวจจับ (worker)

- **FR-1** ทุก `detect_interval` (ค่าเริ่ม 30 วิ) ดึงภาพ 1 เฟรมจากกล้องที่เปิดใช้งานทุกตัว (ใช้ main stream เพื่อความละเอียด; timeout 10 วิ; RTSP over TCP)
- **FR-2** ตรวจจับวัตถุคลาส `car`, `truck`, `bus` (ไม่นับ motorcycle) ค่า confidence ขั้นต่ำปรับได้ (ค่าเริ่ม 0.35)
- **FR-3** รองรับ **tiling** (ตัดภาพเป็นส่วน ๆ ก่อนตรวจ) แบบเลือกเปิดต่อกล้อง สำหรับกล้องมุมกว้างที่รถไกล ๆ ตัวเล็ก
- **FR-4** รองรับ **ROI mask** ต่อกล้อง (ตัดส่วนภาพที่ไม่เกี่ยว เช่น ถนนนอกลาน) เพื่อลดงานและลด false positive
- **FR-5** เก็บภาพล่าสุดของแต่ละกล้อง 1 ภาพ (เขียนทับ) สำหรับหน้า Live/Editor ในหลังบ้านเท่านั้น

### 5.2 การคำนวณสถานะช่อง

- **FR-6** สำหรับแต่ละ slot คำนวณ `score` = สัดส่วนพื้นที่ polygon ที่ทับกับ "footprint" ของรถ
  - footprint = ครึ่งล่างของ bounding box (ใกล้พื้น) เพื่อลดปัญหารถคันหน้าบังช่องหลังในมุมเฉียง
  - ใช้ค่า score สูงสุดจากรถทุกคัน
- **FR-7** `raw = occupied` ถ้า `score ≥ slot.threshold` (ค่าเริ่ม 0.30 ปรับได้ต่อช่อง)
- **FR-8** **Debounce:** เปลี่ยนสถานะเมื่อผลดิบ ≥ 2 ใน 3 รอบล่าสุดตรงกัน (ปรับได้) — ป้องกันตัวเลขกระพริบจากรถวิ่งผ่าน/คนเดินบัง
- **FR-9** สถานะเป็น `unknown` เมื่อ: ดึงภาพไม่ได้, ภาพเก่ากว่า 2 รอบ, กล้องถูกขยับ (FR-30), หรือช่องยังไม่ publish
- **FR-10** บันทึก event เมื่อสถานะช่องเปลี่ยน (เก็บ 30 วัน ใช้ debug)
- **FR-11** Override จาก Operator มีผลเหนือผลตรวจจับ จนหมดอายุหรือถูกยกเลิก

### 5.3 กติกาการนับสำหรับสาธารณะ

- **FR-12** นับเฉพาะช่องที่ `published`, `is_active`, type ∈ {`normal`, `disabled`, `ev`} — `reserved` ไม่นับ
- **FR-13** แยกตัวเลขว่างเป็น: ปกติ / คนพิการ-ผู้สูงอายุ / EV ต่อโซน และรวมทั้งลาน
- **FR-14** กติกาโซนเมื่อข้อมูลไม่ครบ:
  - ช่อง `unknown` ในโซน ≥ 50% (ปรับได้) → โซนแสดง **"ไม่มีข้อมูล / No data"** และ **ไม่นับรวม** ในยอดทั้งลาน
  - 0% < unknown < 50% → แสดงจำนวนว่างที่ทราบ + ป้าย "ข้อมูลบางส่วน"
- **FR-15** ยอดรวมทั้งลานแสดงหมายเหตุถ้ามีโซนที่ถูกตัดออก
- **FR-16** แสดงเวลาที่อัปเดตล่าสุด; ถ้าทั้งระบบไม่อัปเดตเกิน 3 นาที แสดงแบนเนอร์ "ระบบขัดข้องชั่วคราว"

### 5.4 หน้าเว็บสาธารณะ

- **FR-17** หน้าเดียว รองรับมือถือ แสดง: ชื่อสถานที่/โลโก้, จำนวนว่างรวม (ตัวใหญ่), การ์ดแต่ละโซน (ว่าง/ทั้งหมด, สีเขียว-เหลือง-แดงตาม %), ตัวเลขช่องคนพิการ/EV, เวลาอัปเดต
- **FR-18** สลับภาษา ไทย/อังกฤษ (จำค่าใน URL `?lang=en` หรือ cookie)
- **FR-19** หน้าเว็บดึง `/api/public/summary` ทุก 30 วิ โดยไม่ reload หน้า
- **FR-20** ไม่มีภาพกล้อง ไม่มีข้อมูลระดับช่องรายช่อง (ลดความเสี่ยง PDPA/ความปลอดภัย)

### 5.5 หลังบ้าน — การจัดการกล้อง

- **FR-21** เพิ่ม/แก้/ปิดกล้อง: ชื่อ, ยี่ห้อ (preset URL), IP, port, user/password, channel, stream, interval, tiling, ROI
- **FR-22** ปุ่ม **Test connection** แสดงภาพ snapshot ทันทีหรือข้อความ error ที่อ่านเข้าใจ (auth fail / timeout / stream ไม่มี)
- **FR-23** รหัสผ่านกล้องเก็บแบบเข้ารหัส (Fernet, key อยู่ใน `.env`) และไม่แสดงกลับบนหน้าจอ

**Preset RTSP URL**

| ยี่ห้อ | Main stream | Sub stream |
|---|---|---|
| Hikvision | `rtsp://{user}:{pass}@{ip}:554/Streaming/Channels/{ch}01` | `.../Streaming/Channels/{ch}02` |
| Dahua | `rtsp://{user}:{pass}@{ip}:554/cam/realmonitor?channel={ch}&subtype=0` | `...&subtype=1` |
| TVT (กล้องต่อตรง) | `rtsp://{user}:{pass}@{ip}:554/profile1` | `.../profile2` |
| Custom | กรอก URL เอง | |

### 5.6 หลังบ้าน — กำหนดช่องจอด (Layout Editor)

- **FR-24 วาดเอง (Manual):** บนภาพ snapshot คลิก 4 จุดสร้างช่อง, ลากมุมปรับ, ลบ, คัดลอก, กำหนดโซน/ประเภท/รหัสช่อง
  - **Repeat tool:** วาด 1 ช่องแล้วสั่ง "ทำซ้ำ N ช่องตามแนว" (ช่วยลานที่ช่องเรียงกันยาว)
  - **Auto-numbering:** ใส่รหัสช่องอัตโนมัติ เช่น A-01, A-02 …
- **FR-25 Preview/Dry-run:** ระหว่างแก้ draft แสดงผลการตรวจจับปัจจุบันซ้อนบนกรอบ (เขียว=ว่าง, แดง=มีรถ) เพื่อตรวจก่อน publish
- **FR-26 Publish:** ยืนยันแล้ว layout draft → published, บันทึก reference image ของกล้อง (ใช้ใน FR-30), บันทึก audit log
- **FR-27 Coverage report:** แสดงจำนวนช่องที่วาดต่อโซน เทียบกับ "จำนวนช่องจริง" ที่ Admin กรอก เพื่อเห็นว่ากล้องครอบคลุมกี่ %

### 5.7 หลังบ้าน — โหมดกึ่งออโต้ (ระบบเสนอ → Admin อนุมัติ)

Admin เลือกวิธีได้ต่อกล้อง

**โหมด A: สังเกตจากรถที่จอดจริง (Observation)** — แนะนำสำหรับกล้องเดิมมุมเฉียง
- **FR-28a** Admin สร้าง job: เลือกกล้อง, ระยะเวลา (1–3 วัน), ความถี่สุ่มตัวอย่าง (ค่าเริ่ม 5 นาที), ช่วงเวลาที่สนใจ (เช่น 08:00–18:00)
- **FR-28b** ระหว่าง job เก็บเฉพาะ **พิกัด footprint ของรถ** (ไม่เก็บภาพ ยกเว้นภาพพื้นหลัง 1 ภาพช่วงรถเยอะ)
- **FR-28c** เมื่อจบ: จัดกลุ่ม footprint ที่ซ้อนกัน (IoU > 0.5), เก็บเฉพาะกลุ่มที่ "จอดนิ่ง" ปรากฏ ≥ 20% ของตัวอย่าง (ตัดรถวิ่งผ่าน/ทางวิ่ง), ใช้ค่ามัธยฐานของกรอบเป็น polygon, ตัดกรอบที่ทับกันเกิน (NMS)
- **FR-28d** สร้าง proposals พร้อม `confidence` = สัดส่วนการปรากฏ, เรียงรหัสซ้าย→ขวา บน→ล่าง

**โหมด B: ตรวจจับเส้นช่องจอด (Line detection)** — สำหรับลานที่เส้นชัด/มุมค่อนข้างตรง (สถานะ: ทดลอง)
- **FR-29a** Admin เลือกภาพ snapshot ตอนลานค่อนข้างว่าง
- **FR-29b** ประมวลผล: grayscale + CLAHE → mask สีขาว/เหลือง → Canny → HoughLinesP → จัดกลุ่มตามมุม → จับคู่เส้นขนานที่ระยะห่างอยู่ในช่วงความกว้างช่องที่กำหนด → สร้าง polygon
- **FR-29c** มีแถบปรับพารามิเตอร์ (ความกว้างช่อง, ความยาวเส้นขั้นต่ำ, threshold) พร้อม preview ทันที

**การอนุมัติ (ใช้ร่วมทั้ง 2 โหมด)**
- **FR-29d** หน้า Review แสดง proposals ซ้อนบนภาพ: Accept / Reject / แก้มุม / Accept ทั้งหมดที่ confidence ≥ X
- **FR-29e** Proposal ที่ Accept จะเข้า **layout draft** (ไม่ใช่ใช้งานทันที) → ต้อง Preview + Publish ตาม FR-25/26
- **FR-29f** ลบข้อมูลดิบของ job อัตโนมัติหลังปิด job 7 วัน

### 5.8 หลังบ้าน — สุขภาพระบบ

- **FR-30 ตรวจกล้องถูกขยับ:** ทุก 10 นาที เทียบภาพปัจจุบันกับ reference image (ORB feature matching / homography หรือ SSIM ของขอบภาพ) ถ้าเลื่อนเกินเกณฑ์ → สถานะกล้อง `moved`, ช่องของกล้องนั้น `unknown`, แสดงแจ้งเตือนในหลังบ้าน
  - เฟส 3: ปุ่ม "Re-align" ใช้ homography ที่คำนวณได้ขยับกรอบให้อัตโนมัติ แล้วให้ Admin ยืนยัน
- **FR-31** Dashboard แสดงต่อกล้อง: online/offline/moved, เวลาภาพล่าสุด, เวลาประมวลผล, error ล่าสุด; ของ server: CPU, RAM, disk, อุณหภูมิ (ถ้าอ่านได้)
- **FR-32** แจ้งเตือนเป็นแบนเนอร์ + กระดิ่งในหลังบ้าน (ไม่ส่งออกนอกระบบ)

### 5.9 หลังบ้าน — Live view และ Override

- **FR-33** หน้า Live: เลือกกล้อง เห็นภาพล่าสุด + กรอบสีตามสถานะ + score (รีเฟรช 30 วิ)
- **FR-34** Override: เลือกช่อง/หลายช่อง/ทั้งโซน → บังคับ `occupied` (ปิดใช้) หรือ `free` พร้อมหมายเหตุและเวลาหมดอายุ
- **FR-35** ตั้ง "ปิดโซนชั่วคราว" → หน้าสาธารณะแสดง "ปิดให้บริการ"

### 5.10 รายงาน

- **FR-36** worker บันทึกสรุปทุก 1 นาทีต่อโซน: total, occupied, free, unknown
- **FR-37** สรุปรายชั่วโมงอัตโนมัติ (avg/max occupancy %)
- **FR-38** หน้า Reports: กราฟรายชั่วโมง (เลือกวัน), รายวัน (เลือกช่วง), ช่วงเวลาที่คนมากสุดเฉลี่ยตามวันในสัปดาห์ (heatmap)
- **FR-39** เก็บข้อมูลรายนาที 30 วัน, รายชั่วโมง 2 ปี (ปรับได้)

### 5.11 ผู้ใช้และสิทธิ์

- **FR-40** Login ด้วย username/password (Argon2), session cookie (HttpOnly, Secure, SameSite=Lax), CSRF token บนทุกฟอร์ม
- **FR-41** ล็อกบัญชี 15 นาทีหลังใส่รหัสผิด 5 ครั้ง
- **FR-42** สร้าง Admin คนแรกด้วยคำสั่ง CLI ตอนติดตั้ง (ไม่มีรหัสผ่านค่าเริ่มต้น)
- **FR-43** Audit log: login, แก้กล้อง, publish layout, อนุมัติ proposal, override, จัดการผู้ใช้

| ความสามารถ | Admin | Operator |
|---|:-:|:-:|
| Dashboard / Live view | ✅ | ✅ |
| Override ช่อง / ปิดโซน | ✅ | ✅ |
| ดูรายงาน | ✅ | ✅ |
| จัดการกล้อง | ✅ | ❌ |
| Layout editor / Publish | ✅ | ❌ |
| กึ่งออโต้ (สร้าง job / อนุมัติ) | ✅ | ❌ |
| จัดการโซน | ✅ | ❌ |
| จัดการผู้ใช้ | ✅ | ❌ |
| ตั้งค่าระบบ / ดู audit log | ✅ | ❌ |

### 5.12 ตั้งค่าระบบ (Settings)

ชื่อสถานที่ (TH/EN), โลโก้, ข้อความประกาศหน้าเว็บ, เกณฑ์สี (เช่น ว่าง < 10% = แดง), detect interval, debounce, unknown threshold ของโซน, retention

---

## 6. Data Model (SQLite)

```
users            (id, username UNIQUE, password_hash, role[admin|operator],
                  is_active, failed_logins, locked_until, created_at, last_login_at)

zones            (id, code UNIQUE, name_th, name_en, floor, sort_order,
                  expected_slots,           -- จำนวนช่องจริง ใช้คำนวณ coverage
                  is_public, is_closed, closed_note)

cameras          (id, name, brand[hikvision|dahua|tvt|custom], host, port, channel,
                  stream[main|sub], rtsp_url_custom, username, password_enc,
                  enabled, detect_interval_s, conf_threshold, tiling_enabled,
                  roi_polygon JSON, reference_image_path,
                  status[online|offline|moved|disabled], last_frame_at,
                  last_infer_ms, last_error, frame_w, frame_h)

slots            (id, code UNIQUE, camera_id FK, zone_id FK,
                  type[normal|disabled|ev|reserved],
                  polygon JSON,             -- normalized [[x,y],...]
                  threshold, is_active,
                  layout_status[draft|published], updated_at)

slot_state       (slot_id PK FK, state[free|occupied|unknown], score,
                  raw_history JSON,         -- ผล 3 รอบล่าสุด
                  since, updated_at,
                  override_state, override_until, override_by FK, override_note)

slot_events      (id, slot_id, from_state, to_state, ts)          -- เก็บ 30 วัน

calib_jobs       (id, camera_id, method[observation|lines], params JSON,
                  status[running|done|failed|cancelled], progress,
                  started_at, ends_at, created_by, background_image_path)

calib_samples    (id, job_id, ts, boxes JSON)                       -- ลบหลังปิด job 7 วัน

slot_proposals   (id, job_id, camera_id, polygon JSON, confidence,
                  status[pending|accepted|rejected], decided_by, decided_at)

zone_stats_minute(ts, zone_id, total, occupied, free, unknown)     -- 30 วัน
zone_stats_hour  (hour_ts, zone_id, avg_occ_pct, max_occ_pct, samples) -- 2 ปี

alerts           (id, level, source, message, created_at, resolved_at)
audit_log        (id, user_id, action, target, detail JSON, ts)
settings         (key PK, value JSON)
```

---

## 7. API

### 7.1 Public (ไม่ต้อง login)

| Method | Path | คำอธิบาย |
|---|---|---|
| GET | `/` | หน้าเว็บสาธารณะ |
| GET | `/api/public/summary` | ตัวเลขสรุป (cache 10 วิ, rate limit 60 req/นาที/IP) |
| GET | `/healthz` | สถานะระบบแบบย่อ (สำหรับ monitoring) |

ตัวอย่าง `/api/public/summary`
```json
{
  "site": {"name_th": "ลานจอดรถ ตัวอย่าง", "name_en": "Sample Parking"},
  "updated_at": "2026-10-06T08:30:00+07:00",
  "stale": false,
  "total": {"free": 37, "capacity": 120, "free_disabled": 2, "free_ev": 1,
            "excluded_zones": ["B2"]},
  "zones": [
    {"code": "A", "name_th": "โซน A", "name_en": "Zone A", "status": "ok",
     "free": 20, "capacity": 60, "free_disabled": 1, "free_ev": 1},
    {"code": "B1", "status": "partial", "free": 17, "capacity": 40},
    {"code": "B2", "status": "no_data"},
    {"code": "C",  "status": "closed"}
  ]
}
```

### 7.2 Admin (ต้อง login, prefix `/api/admin`)

| กลุ่ม | Endpoints (สรุป) | สิทธิ์ |
|---|---|---|
| Auth | `POST /admin/login`, `POST /admin/logout` | – |
| Cameras | `GET/POST /cameras`, `GET/PUT/DELETE /cameras/{id}`, `POST /cameras/{id}/test`, `GET /cameras/{id}/snapshot` | Admin (snapshot: ทั้งคู่) |
| Zones | `GET/POST /zones`, `PUT/DELETE /zones/{id}`, `POST /zones/{id}/close` | Admin (close: ทั้งคู่) |
| Layout | `GET /cameras/{id}/slots?status=draft`, `PUT /cameras/{id}/slots` (บันทึก draft), `POST /cameras/{id}/slots/preview`, `POST /cameras/{id}/slots/publish` | Admin |
| Calibration | `POST /calib/jobs`, `GET /calib/jobs`, `POST /calib/jobs/{id}/cancel`, `GET /calib/jobs/{id}/proposals`, `POST /calib/proposals/{id}/accept\|reject`, `PATCH /calib/proposals/{id}`, `POST /calib/lines/preview` | Admin |
| Live | `GET /live/{camera_id}` (state + score ทุกช่อง) | ทั้งคู่ |
| Override | `POST /slots/{id}/override`, `DELETE /slots/{id}/override` | ทั้งคู่ |
| Reports | `GET /reports/hourly?zone=&date=`, `GET /reports/daily?zone=&from=&to=`, `GET /reports/heatmap?zone=&weeks=` | ทั้งคู่ |
| Health | `GET /health`, `GET /alerts`, `POST /alerts/{id}/resolve` | ทั้งคู่ |
| Users | `GET/POST /users`, `PUT/DELETE /users/{id}` | Admin |
| Settings | `GET/PUT /settings` | Admin |
| Audit | `GET /audit` | Admin |

---

## 8. Non-Functional Requirements

### 8.1 Performance
- **NFR-1** 8 กล้อง ที่ interval 30 วิ ประมวลผลครบ 1 รอบ < 20 วิ บน CPU (Intel i5 gen 12+) — ถ้าเกินให้ระบบเตือนใน Dashboard
- **NFR-2** `/api/public/summary` ตอบ < 100 ms, รองรับ ~100 ผู้ชมพร้อมกัน (มี cache)
- **NFR-3** ตัวเลขบนเว็บสะท้อนการเปลี่ยนแปลงภายใน ≤ 2 นาที (30 วิ × debounce + polling)

### 8.2 Accuracy (เกณฑ์รับงาน)
- **NFR-4** ความถูกต้องสถานะช่อง ≥ 95% กลางวัน และ ≥ 90% กลางคืน (มีไฟ) สำหรับช่องที่ผ่านเกณฑ์ A4
- วัดด้วยเครื่องมือ **Validation** ในหลังบ้าน: สุ่มภาพ 20 ภาพ/กล้อง ให้คนกดยืนยันสถานะจริง แล้วคำนวณ % ถูกต้อง

### 8.3 Reliability
- **NFR-5** ทุก container `restart: unless-stopped`; worker มี watchdog ถ้ารอบค้างเกิน 2 นาที ให้ exit เพื่อให้ Docker restart
- **NFR-6** กล้องตัวหนึ่งพัง/ช้า ต้องไม่ทำให้กล้องอื่นค้าง (timeout ต่อกล้อง, ประมวลผลแยก)
- **NFR-7** Backup SQLite อัตโนมัติทุกวัน (ใช้ `sqlite3 .backup`) เก็บ 14 ชุด
- **NFR-8** เวลาเครื่อง sync NTP, timezone Asia/Bangkok

### 8.4 Security
- **NFR-9** เปิดสู่ WAN เฉพาะ 80/443 (80 ใช้ redirect + ACME); SSH/อื่น ๆ ไม่เปิดสู่ WAN
- **NFR-10** ufw บน server: อนุญาต 80/443 ทุกที่, 22 เฉพาะ LAN
- **NFR-11** แนะนำกล้องอยู่ VLAN แยก server เป็นตัวเดียวที่เข้าถึงได้; กล้องไม่ออกอินเทอร์เน็ต
- **NFR-12** ตัวเลือก: จำกัด `/admin` ให้เข้าได้เฉพาะ IP ที่กำหนด (Caddy `remote_ip` matcher) หรือผ่าน VPN — **แนะนำให้เปิดใช้**
- **NFR-13** Security headers (HSTS, CSP, X-Frame-Options), rate limit หน้า login และ public API
- **NFR-14** secrets (SECRET_KEY, FERNET_KEY) อยู่ใน `.env` ห้าม commit

### 8.5 Privacy (PDPA)
- **NFR-15** ไม่เผยแพร่ภาพสู่สาธารณะ; หลังบ้านเก็บแค่ภาพล่าสุดต่อกล้อง (เขียนทับ) + reference image + ภาพพื้นหลังของ calibration job
- **NFR-16** ไม่เก็บป้ายทะเบียนหรือข้อมูลระบุตัวบุคคล; เก็บเฉพาะพิกัดกรอบและตัวเลข

---

## 9. สเปก Server ที่แนะนำ

| ระดับ | ใช้เมื่อ | สเปก |
|---|---|---|
| **มาตรฐาน (แนะนำ)** | 3–8 กล้อง, interval 30 วิ | Mini PC / SFF Intel Core i5 gen 12–14 หรือ Core Ultra 5, RAM 16 GB, NVMe SSD 512 GB, LAN 1 Gbps (2 port ถ้าแยกวงกล้อง หรือใช้ VLAN trunk), Ubuntu Server 24.04 LTS |
| เพิ่ม GPU | > 8 กล้อง, เปิด tiling หลายกล้อง, หรือใช้โมเดลใหญ่ | + NVIDIA RTX 3060 12GB / RTX 4060 (เปลี่ยนไปใช้ ONNX Runtime CUDA EP) |
| ควรมีเสมอ | | UPS (≥ 15 นาที + สั่ง shutdown ได้), ระบายอากาศดี/ไม่วางในตู้ร้อน |

เหตุผล: ตรวจจับ 8 ภาพทุก 30 วิ = ภาระเบามากสำหรับ CPU สมัยใหม่ (ประมาณ 0.3–1.5 วิ/ภาพ ด้วย OpenVINO) GPU จำเป็นเฉพาะงานที่ใหญ่กว่านี้ — ยืนยันตัวเลขจริงด้วย benchmark ในเฟส 1

---

## 10. โครงสร้างโปรเจกต์ (เสนอ)

```
smart-parking/
├── docker-compose.yml
├── .env.example
├── Caddyfile
├── Dockerfile                 # image เดียว ใช้ทั้ง web และ worker (คนละ command)
├── pyproject.toml
├── core/                      # โค้ดใช้ร่วม
│   ├── config.py              # อ่าน .env + settings
│   ├── db.py                  # SQLAlchemy session, WAL
│   ├── models.py              # ตารางตามข้อ 6
│   ├── security.py            # hash รหัสผ่าน, เข้ารหัสรหัสกล้อง
│   └── counting.py            # กติกานับสาธารณะ (FR-12..15) — ใช้ร่วม web/worker
├── web/
│   ├── main.py
│   ├── routers/               # public.py, auth.py, admin_pages.py, api_admin/*.py
│   ├── templates/             # public/, admin/
│   └── static/                # css, js (konva, chart, alpine), i18n th/en
├── worker/
│   ├── main.py                # scheduler loop + watchdog
│   ├── capture.py             # ffmpeg/RTSP grab
│   ├── detector.py            # Detector interface + OnnxYoloxDetector
│   ├── occupancy.py           # footprint, score, debounce (FR-6..9)
│   ├── health.py              # online/offline, camera moved (FR-30)
│   ├── stats.py               # สรุปรายนาที/ชั่วโมง, retention
│   └── calibration/
│       ├── observation.py     # โหมด A
│       └── lines.py           # โหมด B
├── migrations/                # Alembic
├── models/                    # ไฟล์ .onnx (ไม่ commit ไฟล์ใหญ่)
├── scripts/
│   ├── create_admin.py
│   ├── backup.sh
│   └── benchmark.py           # วัดเวลาประมวลผลต่อกล้อง
├── data/                      # volume: app.db, snapshots/, backups/
├── tests/                     # pytest: occupancy, counting, lines
├── SPEC.md
└── README.md
```

หลักการเขียนโค้ด (สำหรับผู้พัฒนาระดับเริ่มต้น): ฟังก์ชันสั้น, ไฟล์ละหน้าที่เดียว, ตรรกะคำนวณ (occupancy, counting) เป็น pure function ไม่ยุ่งกับ DB เพื่อเขียน test ง่าย

---

## 11. Site Survey (ทำก่อนเสนอราคา/ติดตั้ง)

เนื่องจากใช้กล้องเดิมที่ยังไม่ทราบมุม ต้องสำรวจก่อนทุก site:

1. ขอ RTSP/user ของกล้องทุกตัว, ทดสอบดึงภาพด้วย VLC หรือ `ffmpeg`
2. เก็บ snapshot ของทุกกล้อง **ช่วงรถเยอะ** และ **ช่วงกลางคืน**
3. วาดคร่าว ๆ ว่าแต่ละกล้องเห็นช่องไหนบ้าง → สรุป **% ความครอบคลุม** ต่อโซน
4. ทำเครื่องหมายช่องที่ "เสี่ยง": รถไกลเกินไป, ถูกเสา/ต้นไม้บัง, ถูกรถคันหน้าบังมิด, ย้อนแสง
5. เช็ค bandwidth/VLAN ระหว่างกล้องกับจุดวาง server, ไฟฟ้า/UPS, ตำแหน่งตู้
6. ยืนยัน Public IP, domain, การ port forward กับผู้ดูแลเครือข่ายลูกค้า
7. สรุปให้ลูกค้าเซ็นรับทราบ: ช่องที่ระบบนับได้ / นับไม่ได้ และข้อเสนอเพิ่มกล้อง (นอกขอบเขตงานนี้)

---

## 12. แผนการพัฒนา (Milestones)

| เฟส | ขอบเขต | เกณฑ์เสร็จ |
|---|---|---|
| **P0 — Prototype** | สคริปต์ดึงภาพจาก 1 กล้อง + ตรวจจับรถ + วาด bbox; benchmark | เห็นรถถูกตรวจในภาพจริงของ site, รู้เวลาประมวลผลต่อภาพ |
| **P1 — MVP** | Docker Compose, DB, จัดการกล้อง, Layout editor (manual + repeat), occupancy + debounce, หน้าเว็บสาธารณะ TH/EN, login Admin/Operator, Caddy HTTPS | ลานจริงแสดงตัวเลขบนเว็บผ่าน domain; ผ่าน NFR-4 บนกล้องอย่างน้อย 1 ตัว |
| **P2 — Operation** | Dashboard health, กล้องหลุด → no_data, Live view, Override/ปิดโซน, รายงานกราฟ, backup, audit log, Validation tool | ใช้งานจริง 2 สัปดาห์โดยไม่ต้องแก้มือ |
| **P3 — Semi-auto** | โหมด A Observation + หน้า Review/Approve, ตรวจกล้องถูกขยับ | สร้าง layout กล้องใหม่ได้ด้วยการอนุมัติ ≥ 70% ของช่องจาก proposals |
| **P4 — Extra** | โหมด B Line detection, Re-align อัตโนมัติ, จำกัด IP หลังบ้านผ่าน UI | ตามความต้องการ |

---

## 13. Acceptance Criteria (สรุป)

- [ ] เปิด `https://<domain>/` จากมือถือนอกเครือข่าย เห็นจำนวนว่างรวมและแยกโซน ทั้งไทย/อังกฤษ
- [ ] รถเข้าจอด/ออก ตัวเลขเปลี่ยนภายใน 2 นาที
- [ ] ถอดสาย LAN กล้อง 1 ตัว → โซนที่เกี่ยวข้องแสดง "ไม่มีข้อมูล" ภายใน 2 นาที และไม่นับรวม; หลังบ้านมีแจ้งเตือน
- [ ] ช่อง `reserved` ไม่ถูกนับในตัวเลขสาธารณะ; ช่องคนพิการ/EV แสดงแยก
- [ ] Admin วาด/แก้/publish ช่องได้ และ Operator ทำไม่ได้
- [ ] Admin สร้าง job สังเกต 24 ชม. แล้วได้ proposals และอนุมัติเข้า layout ได้
- [ ] ความถูกต้องตาม NFR-4 จาก Validation tool
- [ ] ไม่มี port อื่นนอกจาก 80/443 เปิดสู่ WAN; ไม่มีภาพกล้องเข้าถึงได้โดยไม่ login
- [ ] รีบูต server แล้วทุกอย่างกลับมาทำงานเองโดยไม่ต้องแตะ

---

## 14. เรื่องที่ต้องตัดสินใจ (Open Decisions)

| ID | เรื่อง | ตัวเลือก | ข้อเสนอ |
|---|---|---|---|
| D-1 | โมเดลตรวจจับ | YOLOX (Apache-2.0) / Ultralytics YOLO (AGPL หรือซื้อ license) / RF-DETR | เริ่ม YOLOX-s ONNX; benchmark เทียบใน P0 |
| D-2 | จำกัดการเข้าหลังบ้าน | เปิดทั่วไป + รหัสผ่าน / IP allowlist / VPN (เช่น WireGuard บน MikroTik) | IP allowlist หรือ VPN |
| D-3 | ช่องที่ 2 กล้องเห็นซ้ำ | กล้องหลักตัวเดียว / รวมผลหลายกล้อง | กล้องหลักตัวเดียว (v1) |
| D-4 | ค่าเกณฑ์ debounce/threshold | ค่าเริ่มตามสเปก | ปรับจริงหลังทดสอบที่ site แรก |
| D-5 | Retention ข้อมูล | 30 วัน / 2 ปี | ตามสเปก จนกว่าลูกค้าขออื่น |

---

## 15. อภิธานศัพท์

- **RTSP** — โปรโตคอลสตรีมวิดีโอจากกล้อง IP
- **Polygon / กรอบช่อง** — รูปหลายเหลี่ยม (ปกติ 4 จุด) แทนพื้นที่ช่องจอดบนภาพ
- **Footprint** — ส่วนล่างของกรอบรถที่ใกล้พื้น ใช้ตัดสินว่ารถอยู่ช่องไหน
- **Debounce** — รอผลซ้ำหลายรอบก่อนเปลี่ยนสถานะ กันตัวเลขกระพริบ
- **Proposal** — กรอบที่ระบบเสนอ รอคนอนุมัติ
- **Tiling** — ตัดภาพเป็นส่วนย่อยก่อนตรวจจับ ช่วยหาวัตถุขนาดเล็ก
