"""เทียบโมเดล AI ทุกตัวในโฟลเดอร์ models/ กับภาพล่าสุดของกล้อง (ไม่เปลี่ยนค่าใดๆ ในระบบ)

วิธีใช้ (บน Server):
    cd ~/smart-parking
    docker compose exec -T worker python - < tools/compare_models.py          # กล้อง id 3
    docker compose exec -T worker python - 5 < tools/compare_models.py        # กล้อง id 5

แสดง: เวลาประมวลผลต่อภาพ, กรอบที่นับเป็นรถ และคะแนน/สถานะของทุกช่องที่ Publish แล้ว
ใช้ค่า "นับวัตถุขนาดใหญ่เป็นรถ" ของกล้องนั้นตามที่ตั้งไว้จริง
"""
import sys
import time
from datetime import datetime

import cv2
from sqlalchemy import select

from core.camera_utils import snapshot_path
from core.config import MODELS_DIR, get_settings
from core.db import SessionLocal
from core.models import Camera, LayoutStatus, Slot
from worker.detector import OnnxYoloxDetector
from worker.occupancy import compute_slot_score, is_occupied
from worker.vehicle_boxes import analyze_vehicle_boxes

RUNS = 3

camera_id = int(sys.argv[1]) if len(sys.argv) > 1 else 3
db = SessionLocal()
camera = db.get(Camera, camera_id)
if camera is None:
    sys.exit(f"ไม่พบกล้อง id {camera_id}")
slots = db.scalars(
    select(Slot)
    .where(Slot.camera_id == camera_id, Slot.layout_status == LayoutStatus.PUBLISHED, Slot.is_active.is_(True))
    .order_by(Slot.code)
).all()

path = snapshot_path(camera_id)
frame = cv2.imread(str(path))
if frame is None:
    sys.exit(f"ไม่มีภาพล่าสุดของกล้อง ({path})")
age_s = time.time() - path.stat().st_mtime
large = camera.large_object_min_area

print(f"กล้อง: {camera.name} | ภาพ {frame.shape[1]}x{frame.shape[0]} ถ่ายเมื่อ {age_s:.0f} วินาทีก่อน")
print(f"นับวัตถุขนาดใหญ่เป็นรถ: {'ปิด' if large is None else f'เปิด ≥ {large:.1%}'}")
print(f"โมเดลที่ระบบใช้อยู่ตอนนี้: {get_settings().detector_model}")

model_files = sorted(MODELS_DIR.glob("*.onnx"))
if not model_files:
    sys.exit("ไม่พบไฟล์ .onnx ในโฟลเดอร์ models/")

summary = []
for model_path in model_files:
    detector = OnnxYoloxDetector(model_path)
    analyze_vehicle_boxes(detector, frame, large)  # รอบแรกช้ากว่าปกติ ไม่นับเวลา
    start = time.perf_counter()
    for _ in range(RUNS):
        boxes = analyze_vehicle_boxes(detector, frame, large)
    ms = (time.perf_counter() - start) / RUNS * 1000

    print(f"\n=== {model_path.name}  ({ms:.0f} ms ต่อภาพ) ===")
    for b in sorted(boxes, key=lambda v: v.box[0]):
        kind = "รถ" if b.kind == "vehicle" else "วัตถุใหญ่→รถ"
        print(f"  {kind:<12} {b.class_name:<12} {b.score:.2f}  x {b.box[0]:.2f}-{b.box[2]:.2f}  y {b.box[1]:.2f}-{b.box[3]:.2f}")
    footprints = [b.footprint for b in boxes]
    states = []
    for slot in slots:
        score = compute_slot_score(slot.polygon, footprints)
        state = "occupied" if is_occupied(score, slot.threshold) else "free"
        states.append(f"{slot.code} {score:.2f}/{slot.threshold} {state}")
    print("  ช่องจอด: " + (" | ".join(states) if states else "(ยังไม่มีช่องที่ Publish)"))
    summary.append((model_path.name, ms, len(boxes), sum(s.endswith("occupied") for s in states)))

print("\n=== สรุป ===")
print(f"{'โมเดล':<16}{'ms/ภาพ':>8}{'กรอบรถ':>8}{'ช่องมีรถ':>10}")
for name, ms, n_boxes, n_occ in summary:
    print(f"{name:<16}{ms:>8.0f}{n_boxes:>8}{n_occ:>10}")
print(f"(เวลาวัดเมื่อ {datetime.now():%H:%M:%S} บน CPU ของเครื่องนี้)")
db.close()
