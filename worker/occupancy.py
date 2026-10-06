"""คำนวณ footprint ของรถ และ score ของแต่ละช่องจอด (FR-6, FR-7) — pure function

หมายเหตุพิกัด: slot_polygon และ footprint ต้องอยู่หน่วยเดียวกัน (เช่น normalized 0-1
เทียบกับขนาดภาพ ตามที่ SPEC ข้อ 4 กำหนดไว้สำหรับ slot polygon) ผู้เรียกต้องแปลง
พิกัดกล่องตรวจจับ (ที่เป็นพิกเซลจริง) เป็น normalized ก่อนเรียกฟังก์ชันนี้
"""
from __future__ import annotations

from datetime import datetime

from shapely.geometry import Polygon, box

BoxXYXY = tuple[float, float, float, float]

MAX_RAW_HISTORY = 3  # เก็บผลดิบ 3 รอบล่าสุด (FR-8)
DEBOUNCE_MAJORITY = 2  # เปลี่ยนสถานะเมื่อผลดิบตรงกัน >= 2 ใน 3 รอบ


def compute_footprint(detection_box: BoxXYXY) -> BoxXYXY:
    """คืนกล่องครึ่งล่าง (ใกล้พื้น) ของรถ 1 คัน ลดปัญหารถคันหน้าบังช่องหลังในมุมเฉียง (FR-6)"""
    x1, y1, x2, y2 = detection_box
    mid_y = (y1 + y2) / 2
    return (x1, mid_y, x2, y2)


def compute_slot_score(slot_polygon: list[list[float]], footprints: list[BoxXYXY]) -> float:
    """คืนค่า score สูงสุดจากรถทุกคัน = สัดส่วนพื้นที่ slot ที่ถูกทับด้วย footprint (FR-6)"""
    if len(slot_polygon) < 3:
        return 0.0

    slot_shape = Polygon(slot_polygon)
    if not slot_shape.is_valid or slot_shape.area == 0:
        return 0.0

    best_score = 0.0
    for footprint in footprints:
        footprint_shape = box(*footprint)
        intersection_area = slot_shape.intersection(footprint_shape).area
        score = intersection_area / slot_shape.area
        best_score = max(best_score, score)
    return best_score


def is_occupied(score: float, threshold: float) -> bool:
    """FR-7: ผลดิบถือว่า occupied ถ้า score >= threshold ของช่องนั้น"""
    return score >= threshold


def normalize_box(detection_box: BoxXYXY, frame_width: int, frame_height: int) -> BoxXYXY:
    """แปลงกล่องพิกเซลจริงจากตัวตรวจจับเป็น normalized 0-1 ให้หน่วยเดียวกับ slot polygon"""
    x1, y1, x2, y2 = detection_box
    return (x1 / frame_width, y1 / frame_height, x2 / frame_width, y2 / frame_height)


def update_raw_history(history: list[str], new_raw: str) -> list[str]:
    """ต่อผลดิบรอบล่าสุดเข้าไป แล้วเก็บไว้แค่ 3 รอบล่าสุด (FR-8)"""
    return (history + [new_raw])[-MAX_RAW_HISTORY:]


def apply_debounce(history: list[str], current_state: str) -> str:
    """เปลี่ยนสถานะเมื่อผลดิบ >= 2 ใน 3 รอบล่าสุดตรงกัน ไม่งั้นคงสถานะเดิมไว้ (FR-8)

    กันตัวเลขกระพริบจากรถวิ่งผ่าน/คนเดินบังชั่วขณะ
    """
    if not history:
        return current_state

    counts: dict[str, int] = {}
    for raw in history:
        counts[raw] = counts.get(raw, 0) + 1
    majority_state, majority_count = max(counts.items(), key=lambda kv: kv[1])

    return majority_state if majority_count >= DEBOUNCE_MAJORITY else current_state


def resolve_override(
    debounced_state: str,
    override_state: str | None,
    override_until: datetime | None,
    now: datetime,
) -> str:
    """Override จาก Operator มีผลเหนือผลตรวจจับ จนหมดอายุหรือถูกยกเลิก (FR-11)"""
    if override_state and (override_until is None or override_until > now):
        return override_state
    return debounced_state
