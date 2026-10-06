"""วัดเวลาประมวลผลต่อภาพของ Detector (เทียบ NFR-1: 8 กล้อง/30วิ ต้องรวม < 20 วิ)"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2

from worker.detector import OnnxYoloxDetector

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = PROJECT_ROOT / "models" / "yolox_s.onnx"
VIDEO_PATH = PROJECT_ROOT / "data" / "samples" / "carPark.mp4"
NUM_FRAMES = 20


def main() -> None:
    detector = OnnxYoloxDetector(MODEL_PATH)
    cap = cv2.VideoCapture(str(VIDEO_PATH))
    if not cap.isOpened():
        raise RuntimeError(f"เปิดวิดีโอไม่ได้: {VIDEO_PATH}")

    durations_ms = []
    last_detections = []
    try:
        for _ in range(NUM_FRAMES):
            ok, frame = cap.read()
            if not ok:
                break
            start = time.perf_counter()
            last_detections = detector.detect(frame)
            durations_ms.append((time.perf_counter() - start) * 1000)
    finally:
        cap.release()

    if not durations_ms:
        print("ไม่มีเฟรมให้ทดสอบ")
        return

    print(f"จำนวนเฟรมที่ทดสอบ: {len(durations_ms)}")
    print(f"เวลาเฉลี่ย: {sum(durations_ms) / len(durations_ms):.1f} ms/เฟรม")
    print(f"เวลาสูงสุด: {max(durations_ms):.1f} ms")
    print(f"เวลาต่ำสุด: {min(durations_ms):.1f} ms")
    print(f"จำนวนรถที่พบในเฟรมสุดท้าย: {len(last_detections)}")


if __name__ == "__main__":
    main()
