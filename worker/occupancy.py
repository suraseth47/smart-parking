"""คำนวณ footprint ของรถ และ score ของแต่ละช่องจอด (FR-6, FR-7) — pure function

หมายเหตุพิกัด: slot_polygon และ footprint ต้องอยู่หน่วยเดียวกัน (เช่น normalized 0-1
เทียบกับขนาดภาพ ตามที่ SPEC ข้อ 4 กำหนดไว้สำหรับ slot polygon) ผู้เรียกต้องแปลง
พิกัดกล่องตรวจจับ (ที่เป็นพิกเซลจริง) เป็น normalized ก่อนเรียกฟังก์ชันนี้
"""
from __future__ import annotations

from shapely.geometry import Polygon, box

BoxXYXY = tuple[float, float, float, float]


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
