"""โหมด B: เสนอกรอบช่องจอดจากการตรวจจับเส้นช่องจอด (FR-29a/b/c) — สถานะทดลองตาม SPEC

ไปป์ไลน์ตาม FR-29b: grayscale + CLAHE -> mask สีขาว/เหลือง -> Canny -> HoughLinesP
-> จัดกลุ่มตามมุม -> จับคู่เส้นขนานที่ระยะห่างอยู่ในช่วงความกว้างช่องที่กำหนด -> สร้าง polygon

ฟังก์ชันเกี่ยวกับเส้น (angle, pairing, polygon ordering) เป็น pure function ล้วน
มีแค่ detect_line_segments ที่ต้องรับภาพจริง (numpy array) แต่ยัง deterministic
ไม่มี side effect และไม่ยุ่งกับ DB จึง pytest ได้เหมือนฟังก์ชันอื่นในโปรเจกต์นี้
(เทียบ worker/health.py: detect_camera_moved)
"""
from __future__ import annotations

import math

import cv2
import numpy as np

LineXYXY = tuple[float, float, float, float]

DEFAULT_MIN_LINE_LENGTH = 40.0
DEFAULT_CANNY_LOW = 50
DEFAULT_CANNY_HIGH = 150
DEFAULT_HOUGH_THRESHOLD = 40
ANGLE_GROUP_TOLERANCE_DEG = 10.0


def _enhance_gray(frame_bgr: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(gray)


def _white_yellow_mask(frame_bgr: np.ndarray) -> np.ndarray:
    """มาสก์สีขาว/เหลือง (สีเส้นช่องจอดทั่วไป) จากภาพ HSV"""
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    white = cv2.inRange(hsv, (0, 0, 180), (180, 60, 255))
    yellow = cv2.inRange(hsv, (15, 60, 120), (40, 255, 255))
    return cv2.bitwise_or(white, yellow)


def detect_line_segments(
    frame_bgr: np.ndarray,
    min_line_length: float = DEFAULT_MIN_LINE_LENGTH,
    canny_low: int = DEFAULT_CANNY_LOW,
    canny_high: int = DEFAULT_CANNY_HIGH,
    hough_threshold: int = DEFAULT_HOUGH_THRESHOLD,
) -> list[LineXYXY]:
    """grayscale+CLAHE -> mask ขาว/เหลือง -> Canny -> HoughLinesP (FR-29b ขั้นแรก)

    คืน list ของเส้น (x1,y1,x2,y2) เป็นพิกเซลจริง
    """
    gray = _enhance_gray(frame_bgr)
    mask = _white_yellow_mask(frame_bgr)
    masked_gray = cv2.bitwise_and(gray, gray, mask=mask)
    edges = cv2.Canny(masked_gray, canny_low, canny_high)
    raw_lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180,
        threshold=hough_threshold,
        minLineLength=min_line_length,
        maxLineGap=10,
    )
    if raw_lines is None:
        return []
    return [tuple(float(v) for v in np.asarray(line).flatten()) for line in raw_lines]


def line_angle_deg(line: LineXYXY) -> float:
    """มุมของเส้น หน่วยองศา อยู่ในช่วง [0, 180)"""
    x1, y1, x2, y2 = line
    return math.degrees(math.atan2(y2 - y1, x2 - x1)) % 180


def line_length(line: LineXYXY) -> float:
    x1, y1, x2, y2 = line
    return math.hypot(x2 - x1, y2 - y1)


def line_midpoint(line: LineXYXY) -> tuple[float, float]:
    x1, y1, x2, y2 = line
    return ((x1 + x2) / 2, (y1 + y2) / 2)


def group_lines_by_angle(
    lines: list[LineXYXY], tolerance_deg: float = ANGLE_GROUP_TOLERANCE_DEG
) -> list[list[LineXYXY]]:
    """จัดกลุ่มเส้นที่มุมใกล้เคียงกัน (FR-29b) — มุมวนรอบ 180 องศา (เช่น 179 กับ 1 ถือว่าใกล้กัน)"""
    groups: list[list[LineXYXY]] = []
    for line in lines:
        angle = line_angle_deg(line)
        matched = None
        for group in groups:
            group_angle = line_angle_deg(group[0])
            diff = min(abs(angle - group_angle), 180 - abs(angle - group_angle))
            if diff <= tolerance_deg:
                matched = group
                break
        if matched is None:
            groups.append([line])
        else:
            matched.append(line)
    return groups


def perpendicular_distance(line_a: LineXYXY, line_b: LineXYXY) -> float:
    """ระยะห่างตั้งฉากจากจุดกึ่งกลางของ line_b ไปยังแนวเส้น line_a"""
    ax1, ay1, ax2, ay2 = line_a
    length = line_length(line_a)
    if length == 0:
        return 0.0
    nx, ny = -(ay2 - ay1) / length, (ax2 - ax1) / length  # หน่วยเวกเตอร์ตั้งฉาก
    mx, my = line_midpoint(line_b)
    return abs((mx - ax1) * nx + (my - ay1) * ny)


def pair_parallel_lines(
    lines_in_group: list[LineXYXY], slot_width_min: float, slot_width_max: float
) -> list[tuple[LineXYXY, LineXYXY]]:
    """จับคู่เส้นขนาน (มุมใกล้กันแล้ว) ที่ระยะห่างอยู่ในช่วงความกว้างช่องที่กำหนด (FR-29b/c)

    จับคู่แบบ greedy: เส้นหนึ่งจับคู่ได้ครั้งเดียว เรียงตามลำดับที่พบในลิสต์
    """
    used: set[int] = set()
    pairs: list[tuple[LineXYXY, LineXYXY]] = []
    for i, line_a in enumerate(lines_in_group):
        if i in used:
            continue
        for j in range(i + 1, len(lines_in_group)):
            if j in used:
                continue
            dist = perpendicular_distance(line_a, lines_in_group[j])
            if slot_width_min <= dist <= slot_width_max:
                pairs.append((line_a, lines_in_group[j]))
                used.add(i)
                used.add(j)
                break
    return pairs


def _order_quad_points(points: list[tuple[float, float]]) -> list[list[float]]:
    """เรียง 4 จุดของ polygon ตามลำดับรอบจุดศูนย์กลาง (กันรูปบิดเป็นเลขแปด)"""
    cx = sum(p[0] for p in points) / len(points)
    cy = sum(p[1] for p in points) / len(points)
    ordered = sorted(points, key=lambda p: math.atan2(p[1] - cy, p[0] - cx))
    return [[p[0], p[1]] for p in ordered]


def pair_to_polygon(pair: tuple[LineXYXY, LineXYXY], frame_width: int, frame_height: int) -> list[list[float]]:
    """แปลงคู่เส้นขนาน (พิกเซลจริง) เป็น polygon normalized 0-1"""
    line_a, line_b = pair
    points = [
        (line_a[0], line_a[1]),
        (line_a[2], line_a[3]),
        (line_b[0], line_b[1]),
        (line_b[2], line_b[3]),
    ]
    ordered = _order_quad_points(points)
    return [[x / frame_width, y / frame_height] for x, y in ordered]


def propose_polygons_from_lines(
    frame_bgr: np.ndarray,
    slot_width_min: float,
    slot_width_max: float,
    min_line_length: float = DEFAULT_MIN_LINE_LENGTH,
    hough_threshold: int = DEFAULT_HOUGH_THRESHOLD,
) -> list[list[list[float]]]:
    """ไปป์ไลน์เต็มของโหมด B (FR-29a/b/c): คืน list ของ polygon normalized 0-1 ที่เสนอ

    ใช้ได้ทั้งตอน preview (ไม่บันทึก) และตอนสร้าง proposals จริง
    """
    frame_h, frame_w = frame_bgr.shape[:2]
    lines = detect_line_segments(frame_bgr, min_line_length=min_line_length, hough_threshold=hough_threshold)
    groups = group_lines_by_angle(lines)

    polygons = []
    for group in groups:
        pairs = pair_parallel_lines(group, slot_width_min, slot_width_max)
        for pair in pairs:
            polygons.append(pair_to_polygon(pair, frame_w, frame_h))
    return polygons
