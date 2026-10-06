"""สคริปต์ P0: ดึงภาพ 1 เฟรม -> ตรวจจับรถ -> วาดกรอบ -> เซฟไฟล์ผลลัพธ์

ใช้ยืนยันเกณฑ์เสร็จ P0: "เห็นรถถูกตรวจในภาพจริงของ site"
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2

from worker.capture import grab_frame
from worker.detector import OnnxYoloxDetector

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = PROJECT_ROOT / "models" / "yolox_s.onnx"
SOURCE = PROJECT_ROOT / "data" / "samples" / "sample_frame.jpg"
OUTPUT_PATH = PROJECT_ROOT / "data" / "samples" / "output_bbox.jpg"

BOX_COLOR = (0, 255, 0)


def main() -> None:
    frame = grab_frame(str(SOURCE))
    detector = OnnxYoloxDetector(MODEL_PATH)
    detections = detector.detect(frame)

    print(f"พบรถทั้งหมด {len(detections)} คัน")
    for det in detections:
        _draw_detection(frame, det)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(OUTPUT_PATH), frame)
    print(f"บันทึกผลที่ {OUTPUT_PATH}")


def _draw_detection(frame, det) -> None:
    x1, y1, x2, y2 = (int(v) for v in det.box)
    cv2.rectangle(frame, (x1, y1), (x2, y2), BOX_COLOR, 2)
    label = f"{det.class_name} {det.score:.2f}"
    cv2.putText(frame, label, (x1, max(y1 - 8, 0)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, BOX_COLOR, 2)


if __name__ == "__main__":
    main()
