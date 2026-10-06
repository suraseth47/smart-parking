"""โหมด A: เสนอกรอบช่องจอดจากการสังเกตรถที่จอดจริง (FR-28c, FR-28d) — pure function

รับ footprint (กล่อง normalized 0-1) ที่เก็บได้จากหลายรอบของ calibration job
มาจัดกลุ่มตำแหน่งที่ซ้อนกัน คัดเฉพาะกลุ่มที่ "จอดนิ่ง" บ่อยพอ แล้วสร้าง proposal
"""
from __future__ import annotations

from shapely.geometry import box

BoxXYXY = tuple[float, float, float, float]


def compute_iou(box_a: BoxXYXY, box_b: BoxXYXY) -> float:
    """สัดส่วนพื้นที่ซ้อนกันเทียบกับพื้นที่รวมของกล่องทั้งสอง (Intersection over Union)"""
    shape_a, shape_b = box(*box_a), box(*box_b)
    union_area = shape_a.area + shape_b.area - shape_a.intersection(shape_b).area
    if union_area == 0:
        return 0.0
    return shape_a.intersection(shape_b).area / union_area


def cluster_boxes(samples: list[list[BoxXYXY]], iou_threshold: float = 0.5) -> list[dict]:
    """จัดกลุ่ม footprint ที่ซ้อนกัน (IoU > threshold) ข้ามรอบตัวอย่างทั้งหมด (FR-28c)

    คืน list ของ {"boxes": [...], "sample_indices": {int, ...}} — เทียบกล่องใหม่
    กับกล่องตัวแทน (กล่องแรก) ของกลุ่มที่มีอยู่ แบบ greedy ตามลำดับที่พบ
    """
    clusters: list[dict] = []
    for sample_idx, boxes in enumerate(samples):
        for candidate in boxes:
            matched = None
            for cluster in clusters:
                representative = cluster["boxes"][0]
                if compute_iou(candidate, representative) > iou_threshold:
                    matched = cluster
                    break
            if matched is None:
                clusters.append({"boxes": [candidate], "sample_indices": {sample_idx}})
            else:
                matched["boxes"].append(candidate)
                matched["sample_indices"].add(sample_idx)
    return clusters


def median_box(boxes: list[BoxXYXY]) -> BoxXYXY:
    """ค่ามัธยฐานของกรอบ (แยกคำนวณทีละแกน) ใช้เป็นกรอบตัวแทนของกลุ่ม (FR-28c)"""
    xs1 = sorted(b[0] for b in boxes)
    ys1 = sorted(b[1] for b in boxes)
    xs2 = sorted(b[2] for b in boxes)
    ys2 = sorted(b[3] for b in boxes)
    mid = len(boxes) // 2

    def median(values: list[float]) -> float:
        if len(values) % 2 == 1:
            return values[mid]
        return (values[mid - 1] + values[mid]) / 2

    return (median(xs1), median(ys1), median(xs2), median(ys2))


def box_to_polygon(box_xyxy: BoxXYXY) -> list[list[float]]:
    """แปลงกล่อง xyxy เป็น polygon 4 มุม เรียง TL -> TR -> BR -> BL ให้หน่วยเดียวกับ Slot.polygon"""
    x1, y1, x2, y2 = box_xyxy
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


def non_max_suppression(proposals: list[dict], iou_threshold: float = 0.5) -> list[dict]:
    """ตัด proposal ที่ทับกันเกิน (FR-28c) เก็บไว้เฉพาะตัวที่ confidence สูงกว่าในกลุ่มที่ทับกัน"""
    ordered = sorted(proposals, key=lambda p: p["confidence"], reverse=True)
    kept: list[dict] = []
    for candidate in ordered:
        overlaps_kept = any(
            compute_iou(candidate["box"], kept_item["box"]) > iou_threshold for kept_item in kept
        )
        if not overlaps_kept:
            kept.append(candidate)
    return kept


def build_proposals(
    samples: list[list[BoxXYXY]],
    min_presence_ratio: float = 0.2,
    iou_threshold: float = 0.5,
) -> list[dict]:
    """สร้าง proposals จากผลสังเกตทั้ง job (FR-28c, FR-28d)

    1. จัดกลุ่ม footprint ที่ซ้อนกัน
    2. คัดเฉพาะกลุ่มที่ปรากฏ >= min_presence_ratio ของจำนวนตัวอย่าง (ตัดรถวิ่งผ่าน)
    3. ใช้ค่ามัธยฐานของกรอบในกลุ่มเป็น polygon, confidence = สัดส่วนการปรากฏ
    4. ตัดกรอบที่ทับกันเกิน (NMS)
    5. เรียงซ้าย->ขวา บน->ล่าง

    คืน list ของ {"polygon": [[x,y], ...], "confidence": float}
    """
    total_samples = len(samples)
    if total_samples == 0:
        return []

    clusters = cluster_boxes(samples, iou_threshold=iou_threshold)

    candidates = []
    for cluster in clusters:
        presence_ratio = len(cluster["sample_indices"]) / total_samples
        if presence_ratio < min_presence_ratio:
            continue
        representative_box = median_box(cluster["boxes"])
        candidates.append({"box": representative_box, "confidence": round(presence_ratio, 4)})

    kept = non_max_suppression(candidates, iou_threshold=iou_threshold)

    def sort_key(item: dict) -> tuple[float, float]:
        x1, y1, x2, y2 = item["box"]
        return ((y1 + y2) / 2, (x1 + x2) / 2)  # บน->ล่าง ก่อน แล้วค่อยซ้าย->ขวา

    kept.sort(key=sort_key)

    return [
        {"polygon": box_to_polygon(item["box"]), "confidence": item["confidence"]} for item in kept
    ]
