"""ดึงภาพ 1 เฟรมจากแหล่งต่างๆ: ไฟล์ภาพ, ไฟล์วิดีโอ, หรือ RTSP URL (ตาม FR-1)"""
import os

import cv2
import numpy as np

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp"}


def grab_frame(source: str) -> np.ndarray:
    """คืนภาพ 1 เฟรมแบบ BGR จาก source; โยน RuntimeError ถ้าดึงไม่ได้"""
    if _is_image_file(source):
        # ใช้ imdecode แทน imread ตรงๆ เพราะ cv2.imread พังกับ path ที่มีอักษรไทย/unicode บน Windows
        file_bytes = np.fromfile(source, dtype=np.uint8)
        frame = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
        if frame is None:
            raise RuntimeError(f"อ่านไฟล์ภาพไม่ได้: {source}")
        return frame

    if source.startswith("rtsp://"):
        # บังคับใช้ TCP กันภาพแตก/เฟรมหลุดตาม FR-1
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise RuntimeError(f"เปิดแหล่งภาพไม่ได้: {source}")
    try:
        ok, frame = cap.read()
    finally:
        cap.release()
    if not ok or frame is None:
        raise RuntimeError(f"ดึงเฟรมไม่ได้: {source}")
    return frame


def _is_image_file(source: str) -> bool:
    return any(source.lower().endswith(suffix) for suffix in IMAGE_SUFFIXES)
