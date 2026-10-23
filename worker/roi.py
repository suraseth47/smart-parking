"""ROI อัตโนมัติจากช่องจอด (FR-4) — pure function ไม่ยุ่งกับ DB

ตัดภาพเฉพาะบริเวณที่มีช่องจอด (+ ขอบเผื่อ) ก่อนส่งให้ AI เพราะโมเดลย่อภาพทั้งภาพลงเหลือ
กว้าง 640 พิกเซลเสมอ ถ้าตัดส่วนที่ไม่เกี่ยว (ท้องฟ้า ถนน ตึก) ทิ้งก่อน รถจะใหญ่ขึ้นในสายตา AI
โดยใช้ CPU เท่าเดิม — ได้ผลมากกับกล้องความละเอียดสูง (เช่น 6MP) ที่ช่องจอดกินพื้นที่ส่วนเดียวของภาพ
และลดการจับรถที่วิ่งบนถนนนอกลาน

พิกัด ROI เป็น normalized 0-1 เทียบกับภาพเต็ม (x1, y1, x2, y2)
"""
from __future__ import annotations

BoxXYXY = tuple[float, float, float, float]

# ROI ที่เล็กกว่านี้ (พิกเซล) ไม่ตัด ใช้ภาพเต็มแทน — กันภาพเล็กจนโมเดลดูอะไรไม่ออก
MIN_CROP_PIXELS = 64


def compute_roi(polygons: list[list[list[float]]], margin: float) -> BoxXYXY | None:
    """กรอบสี่เหลี่ยมที่ครอบทุกช่อง แล้วขยายออกทุกด้านเท่ากับ margin (สัดส่วนของภาพเต็ม)

    คืน None ถ้ายังไม่มีช่อง (ใช้ภาพเต็มตามเดิม)
    """
    points = [p for polygon in polygons for p in polygon]
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x1 = max(0.0, min(xs) - margin)
    y1 = max(0.0, min(ys) - margin)
    x2 = min(1.0, max(xs) + margin)
    y2 = min(1.0, max(ys) + margin)
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2, y2)


def roi_to_pixels(roi: BoxXYXY, frame_width: int, frame_height: int) -> tuple[int, int, int, int] | None:
    """แปลง ROI เป็นพิกัดพิกเซลสำหรับตัดภาพ คืน None ถ้าเล็กเกินไปหรือเกือบเต็มภาพอยู่แล้ว"""
    x1 = int(roi[0] * frame_width)
    y1 = int(roi[1] * frame_height)
    x2 = int(round(roi[2] * frame_width))
    y2 = int(round(roi[3] * frame_height))
    if x2 - x1 < MIN_CROP_PIXELS or y2 - y1 < MIN_CROP_PIXELS:
        return None
    if x1 == 0 and y1 == 0 and x2 >= frame_width and y2 >= frame_height:
        return None  # ครอบทั้งภาพ ไม่ต้องตัด
    return (x1, y1, x2, y2)


def shift_box(box: BoxXYXY, offset_x: float, offset_y: float) -> BoxXYXY:
    """เลื่อนกรอบที่ตรวจเจอในภาพที่ตัดแล้ว กลับไปเป็นพิกัดของภาพเต็ม (หน่วยพิกเซล)"""
    x1, y1, x2, y2 = box
    return (x1 + offset_x, y1 + offset_y, x2 + offset_x, y2 + offset_y)
