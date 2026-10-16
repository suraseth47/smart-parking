# Smart Parking 🅿️

ระบบตรวจนับที่จอดรถว่างจากกล้องวงจรปิด IP (Hikvision / Dahua) แล้วแสดงจำนวนที่ว่างบนเว็บไซต์ให้คนทั่วไปดูได้แบบออนไลน์ — ติดตั้งบน Server เครื่องเดียวที่หน้างาน

> พัฒนาครบทุกเฟสตาม SPEC ข้อ 12 แล้ว (P0–P4) คำสั่ง/โครงสร้างด้านล่างตรงกับโค้ดจริง
> รายละเอียดการออกแบบทั้งหมดอยู่ใน [SPEC.md](SPEC.md)

---

## ความสามารถหลัก

- 🚗 ตรวจสถานะ **ทุกช่องจอด** (ว่าง/มีรถ) ด้วย AI จากกล้องเดิม หลายกล้อง อัปเดตทุก ~30 วินาที
- 🌐 **หน้าเว็บสาธารณะ** (ไทย/อังกฤษ) แสดงที่ว่างรวมทั้งลาน + แยกโซน/ชั้น + ช่องคนพิการ/EV
- 🛠️ **หลังบ้าน** สำหรับ Admin และ Operator
  - เพิ่ม/ทดสอบกล้อง
  - กำหนดช่องจอดได้ 3 วิธี: **วาดเอง**, **ระบบสังเกตรถที่จอดจริงแล้วเสนอกรอบ**, **ระบบหาเส้นช่องจอดแล้วเสนอกรอบ** → Admin อนุมัติ
  - Live view, บังคับสถานะช่อง/ปิดโซนชั่วคราว
  - สถานะกล้อง (หลุด / ถูกขยับ), รายงานกราฟอัตราการใช้งาน
- 🔒 HTTPS อัตโนมัติ (Let's Encrypt), ไม่เผยแพร่ภาพกล้องสู่สาธารณะ

---

## สถาปัตยกรรมโดยย่อ

```
คนทั่วไป/Admin ──HTTPS──▶ Router (port forward 80,443)
                               │
                ┌──────────────▼───────────────────────────┐
                │ Server (Docker Compose)                    │
                │  caddy ─▶ web (FastAPI)    worker (AI)    │
                │                 └── SQLite ──┘            │
                └──────────────────────────────┬───────────┘
                                               │ RTSP
                                   กล้อง IP 1..N (LAN/VLAN)
```

| Service | หน้าที่ |
|---|---|
| `caddy` | HTTPS / reverse proxy |
| `web` | หน้าเว็บสาธารณะ + หลังบ้าน + API |
| `worker` | ดึงภาพ → ตรวจจับรถ → คำนวณช่องว่าง → บันทึก DB |

---

## สิ่งที่ต้องเตรียม

### ฮาร์ดแวร์ (สำหรับ 3–8 กล้อง)
- Mini PC / SFF: Intel Core i5 gen 12+ , RAM 16 GB, NVMe 512 GB, LAN 1 Gbps
- UPS
- (ถ้ามากกว่า 8 กล้อง) การ์ดจอ NVIDIA RTX 3060 12GB หรือเทียบเท่า

### ซอฟต์แวร์
- Ubuntu Server 24.04 LTS
- Docker Engine + Docker Compose plugin
- git

### เครือข่าย
- [ ] Server เข้าถึงกล้องทุกตัวได้ (แนะนำกล้องอยู่ VLAN แยก)
- [ ] Public IP แบบคงที่ที่เราเตอร์
- [ ] Domain ที่มี DNS A record ชี้มาที่ Public IP (เช่น `parking.example.com`)
- [ ] Port forward TCP **80** และ **443** → IP ของ Server (ห้ามเปิด port อื่น)
- [ ] user/password ของกล้องที่ดึง RTSP ได้ (แนะนำสร้าง user แบบ view-only)

### RTSP URL ของกล้อง

| ยี่ห้อ | ตัวอย่าง (main stream, channel 1) |
|---|---|
| Hikvision | `rtsp://user:pass@192.168.10.11:554/Streaming/Channels/101` |
| Dahua | `rtsp://user:pass@192.168.10.12:554/cam/realmonitor?channel=1&subtype=0` |

ทดสอบก่อนติดตั้งด้วย VLC (Media → Open Network Stream) หรือ:
```bash
ffmpeg -rtsp_transport tcp -i "rtsp://user:pass@IP:554/Streaming/Channels/101" -frames:v 1 test.jpg
```

---

## ถ้าเครื่อง Server เป็น Proxmox

ขั้นตอนด้านล่างทั้งหมด (Docker, การติดตั้ง) ต้องรันบน **Ubuntu Server 24.04 LTS** —
ถ้า Server หน้างานลงไว้เป็น Proxmox (hypervisor) ต้องสร้าง **VM** (ไม่ใช่ LXC container
เพราะ Docker-in-LXC ต้องเปิด nesting เสี่ยงมีปัญหา) ก่อน แล้วค่อยทำตามขั้นตอนข้างล่างนี้
*ในตัว VM*:

1. Proxmox UI → **Create VM** → เลือก ISO ของ Ubuntu Server 24.04 LTS
2. สเปก VM: อย่างน้อย 4 vCPU, RAM 16 GB, Disk 512 GB (ปรับตามจำนวนกล้อง ดูหัวข้อฮาร์ดแวร์ด้านบน)
3. Network: ใช้ **Bridge** (เช่น `vmbr0`) ไม่ใช่ NAT ให้ VM ได้ IP ของตัวเองในเครือข่ายเดียวกับกล้อง
4. ติดตั้ง Ubuntu ตามปกติ ตั้ง static IP ให้ VM (จะได้ตั้ง port forward จากเราเตอร์มาที่ IP นี้ได้แน่นอน)
5. จากนั้น SSH เข้า VM แล้วทำตาม "การติดตั้ง" ด้านล่างนี้ต่อได้เลย เหมือนเป็น Ubuntu Server ปกติ

---

## การติดตั้ง

```bash
# 1. ติดตั้ง Docker (ครั้งแรกของเครื่อง)
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER   # logout/login ใหม่

# 2. ตั้ง timezone และ firewall
sudo timedatectl set-timezone Asia/Bangkok
sudo ufw allow 80,443/tcp
sudo ufw allow from 192.168.0.0/16 to any port 22 proto tcp   # SSH เฉพาะ LAN
sudo ufw enable

# 3. ดึงโปรเจกต์
git clone https://github.com/suraseth47/smart-parking.git
cd smart-parking

# 4. ตั้งค่า
cp .env.example .env
nano .env          # แก้ DOMAIN, SITE_NAME, สร้าง SECRET_KEY / FERNET_KEY

# 5. ดาวน์โหลดโมเดล AI ไปไว้ที่ models/ (ดูวิธีใน models/README.md)

# 6. รันระบบ
docker compose up -d

# 7. สร้างบัญชี Admin คนแรก
docker compose exec web python scripts/create_admin.py
```

### ตัวแปรใน `.env`

| ตัวแปร | ตัวอย่าง | คำอธิบาย |
|---|---|---|
| `DOMAIN` | `parking.example.com` | ใช้ออกใบรับรอง HTTPS |
| `ACME_EMAIL` | `admin@example.com` | อีเมลสำหรับ Let's Encrypt |
| `SITE_NAME_TH` / `SITE_NAME_EN` | `ลานจอดรถ ...` | ชื่อที่แสดงบนเว็บ |
| `SECRET_KEY` | (สุ่มยาว) | เซ็น session |
| `FERNET_KEY` | (สุ่ม) | เข้ารหัสรหัสผ่านกล้องใน DB |
| `TZ` | `Asia/Bangkok` | |

> จำกัด IP ที่เข้าหลังบ้านได้ (ไม่บังคับ) ตั้งที่หน้า **หลังบ้าน → ตั้งค่า** หลัง login
> (ไม่ได้ตั้งผ่าน `.env`)

สร้าง key แบบสุ่ม:
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

---

## ตั้งค่าครั้งแรก (หลังบ้าน)

เข้า `https://<domain>/admin` แล้วทำตามลำดับ:

1. **Settings** — ชื่อสถานที่, โลโก้, ข้อความประกาศ
2. **Zones** — สร้างโซน/ชั้น และใส่ "จำนวนช่องจริง" ของแต่ละโซน
3. **Cameras** — เพิ่มกล้อง → กด **Test connection** ให้เห็นภาพ
4. **กำหนดช่องจอด** เลือกวิธีใดวิธีหนึ่งต่อกล้อง
   - **วาดเอง:** คลิก 4 มุมต่อช่อง ใช้ปุ่ม Repeat ทำซ้ำช่องที่เรียงกัน
   - **สังเกตรถจริง (แนะนำสำหรับกล้องมุมเฉียง):** สร้าง job 1–3 วัน → รอ → เข้าหน้า Review กด Accept/แก้กรอบ
   - **หาเส้นช่องจอด (ทดลอง):** เลือกภาพตอนลานว่าง ปรับค่าจนกรอบตรง → Accept
5. ตั้ง **โซน** และ **ประเภทช่อง** (ปกติ / คนพิการ / EV / สงวน-VIP)
6. กด **Preview** ดูว่ากรอบเขียว/แดงตรงกับความจริง → **Publish**
7. ดู **Coverage** ว่ากล้องครอบคลุมกี่ % ของแต่ละโซน
8. รัน **Validation** (สุ่มภาพให้คนยืนยัน) เพื่อวัดความแม่นยำก่อนส่งมอบ
9. **Users** — สร้างบัญชี Operator ให้เจ้าหน้าที่

---

## การใช้งานประจำวัน

| งาน | ใคร | ที่ไหน |
|---|---|---|
| ดูภาพรวม / สถานะกล้อง | Admin, Operator | Dashboard |
| ดูภาพพร้อมกรอบสถานะ | Admin, Operator | Live |
| ปิดช่อง/โซนชั่วคราว (ซ่อม, งานอีเวนต์) | Admin, Operator | Live → Override / Zones → Close |
| ดูกราฟการใช้งาน | Admin, Operator | Reports |
| กล้องถูกขยับ → แก้กรอบใหม่ | Admin | แจ้งเตือนบน Dashboard → Layout editor |

---

## การดูแลระบบ

```bash
docker compose ps                      # สถานะ service
docker compose logs -f worker          # ดู log การตรวจจับ
docker compose restart worker          # รีสตาร์ต worker
docker compose exec web python scripts/benchmark.py   # วัดเวลาประมวลผลต่อกล้อง
```

### Backup / Restore
- ตั้ง cron บนเครื่อง host ให้รัน `scripts/backup.sh` วันละครั้ง (สคริปต์เก็บให้อัตโนมัติแค่ 14 ชุดล่าสุด):
  ```bash
  sudo apt install sqlite3   # ถ้ายังไม่มี
  chmod +x scripts/backup.sh
  crontab -e
  # เพิ่มบรรทัดนี้ (รันตี 3 ทุกวัน แก้ path ให้ตรงเครื่องจริง):
  0 3 * * * /path/to/smart-parking/scripts/backup.sh >> /var/log/smart-parking-backup.log 2>&1
  ```
- ไฟล์ backup จะอยู่ที่ `data/backups/app_<วันที่เวลา>.db`
- แนะนำคัดลอกโฟลเดอร์ `data/backups/` ออกนอกเครื่องเป็นระยะ
- Restore: หยุดระบบ (`docker compose down`) → คัดลอกไฟล์ backup ทับ `data/app.db` → `docker compose up -d`

### อัปเดตเวอร์ชัน
```bash
git pull
docker compose build
docker compose up -d     # migration ฐานข้อมูลรันอัตโนมัติตอน start
```

---

## แก้ปัญหาเบื้องต้น

| อาการ | สาเหตุที่พบบ่อย | วิธีแก้ |
|---|---|---|
| Test connection: `401 Unauthorized` | user/password ผิด หรือ user ไม่มีสิทธิ์ดูสด | ตรวจที่หน้าเว็บกล้อง |
| Test connection: timeout | IP/VLAN/firewall, RTSP port ไม่ใช่ 554 | `ping` และ `ffmpeg` จาก server |
| โซนแสดง "ไม่มีข้อมูล" | กล้องหลุด หรือถูกขยับ | ดู Dashboard → สถานะกล้อง |
| ตัวเลขกระพริบไปมา | threshold ต่ำไป / คนเดินบัง | เพิ่ม threshold ของช่อง หรือ debounce |
| ช่องไกล ๆ ไม่เคยเป็นสีแดง | รถเล็กเกินในภาพ | เปิด Tiling ของกล้อง หรือตัดช่องนั้นออก |
| เว็บไม่ขึ้น HTTPS | DNS ยังไม่ชี้ / port 80 ไม่ได้ forward | ตรวจ DNS และ `docker compose logs caddy` |
| Dashboard เตือนประมวลผลช้า | กล้องเยอะ/เปิด tiling หลายตัว | เพิ่ม interval หรือเพิ่ม GPU |

---

## เช็คลิสต์ก่อนประกาศใช้งานจริง (Go-live)

หลัง deploy เสร็จ ให้ถือเป็น **staging** ก่อน — ยังไม่เปิดให้ลูกค้า/สาธารณะใช้จนกว่าจะผ่านครบ
(อ้างอิง SPEC ข้อ 13 Acceptance Criteria):

### ความปลอดภัยก่อนเปิดสู่สาธารณะ (ทำก่อนอย่างแรก)
- [ ] เปลี่ยนรหัสผ่าน Admin ตัวทดสอบ (หรือลบทิ้งแล้วสร้างใหม่ด้วย `scripts/create_admin.py`)
- [ ] ลบกล้องทดสอบ (`ValidationTestCam` หรือกล้องตัวอย่างอื่นที่ชี้ไฟล์ในเครื่อง dev) ออก ใส่กล้องจริงแทน

### ทดสอบด้วยกล้องจริง
- [ ] เพิ่มกล้องจริงที่หน้า "กล้อง" แล้วกด **Test connection** เห็นภาพจริงจากกล้อง
- [ ] วาด/อนุมัติช่องจอดจริง แล้ว Publish
- [ ] รถเข้า/ออกจริง → ตัวเลขบนเว็บเปลี่ยนภายใน 2 นาที
- [ ] ถอดสาย LAN กล้อง 1 ตัวทดสอบจริง → โซนนั้นแสดง "ไม่มีข้อมูล" ภายใน 2 นาที + มีแจ้งเตือนในหลังบ้าน
- [ ] รัน Validation tool วัด % ความแม่นยำ เทียบ NFR-4

### เครือข่าย/ความปลอดภัยระบบ
- [ ] เปิด `https://<domain>/` จากมือถือที่ไม่ได้ต่อ LAN เดียวกัน เห็นเว็บจริงผ่าน HTTPS (ใบรับรองออกจาก Let's Encrypt สำเร็จ)
- [ ] สแกนพอร์ตจากนอกเครือข่าย (เช่น `nmap <public-ip>`) ต้องเห็นแค่ 80/443 เปิด
- [ ] ลองเข้า URL ภาพกล้องตรงๆ โดยไม่ login ต้องเข้าไม่ได้

### ความทนทาน
- [ ] `docker compose restart` หรือ reboot ทั้งเครื่อง → ระบบกลับมาทำงานเองครบ (web, worker, caddy) โดยไม่ต้องสั่งอะไรเพิ่ม
- [ ] ตั้ง cron backup (`scripts/backup.sh`) แล้วทดลอง restore ดูสักครั้งว่าใช้ได้จริง

ผ่านครบทุกข้อค่อยประกาศ URL ให้สาธารณะ/ลูกค้าใช้งานจริง

---

## โครงสร้างโปรเจกต์

```
smart-parking/
├── docker-compose.yml   ├── Caddyfile   ├── .env.example   ├── Dockerfile
├── core/        # config, DB, models, security, กติกาการนับ
├── web/         # FastAPI: หน้าเว็บสาธารณะ + หลังบ้าน + API
├── worker/      # ดึงภาพ, ตรวจจับ, คำนวณช่อง, health, สถิติ, calibration
├── migrations/  # Alembic
├── models/      # ไฟล์โมเดล AI (.onnx)
├── scripts/     # create_admin, backup, benchmark
├── data/        # ฐานข้อมูลและภาพ (volume, ไม่ commit)
├── tests/
├── SPEC.md
└── README.md
```

---

## Roadmap

- [x] P0 Prototype — ดึงภาพ + ตรวจจับรถ + benchmark
- [ ] P1 MVP — กล้อง, วาดช่อง, นับ, หน้าเว็บสาธารณะ, login, HTTPS (โค้ดครบแล้ว รอทดสอบ deploy จริงบน Ubuntu+Docker)
- [ ] P2 Operation — health, override, รายงาน, backup, validation
- [ ] P3 Semi-auto — สังเกตรถจริง + อนุมัติ, ตรวจกล้องถูกขยับ
- [ ] P4 Extra — หาเส้นช่องจอด, re-align อัตโนมัติ

## License

(ระบุภายหลัง — ดูหมายเหตุ License ของโมเดล AI ใน SPEC.md ข้อ 3.2)
