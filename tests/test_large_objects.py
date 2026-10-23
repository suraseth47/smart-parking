"""โหมด "นับวัตถุขนาดใหญ่เป็นรถ" — กล้องที่มองรถจากด้านบนใกล้ๆ แล้วโมเดลทายชื่อผิด

ตัวเลขกรอบอ้างอิงจากภาพจริงของ Cam1 (1920x1080) ที่ทดสอบเมื่อ 23 ต.ค.:
รถสีเงินช่อง A-02 ถูกทายเป็น cell_phone, รถช่อง A-01 ถูกทายเป็น backpack
"""
from dataclasses import dataclass

import numpy as np

from worker.detector import COCO_CLASS_NAMES, VEHICLE_CLASSES, _postprocess_other_classes
from worker.occupancy import box_area, compute_slot_score, is_occupied, select_vehicle_boxes
from worker.vehicle_boxes import LARGE_OBJECT_MIN_SCORE, detect_vehicle_footprints

W, H = 1920, 1080


@dataclass
class FakeDetection:
    box: tuple
    score: float
    class_name: str


CAR_FAR = FakeDetection((1327, 233, 1883, 1065), 0.78, "car")
PHONE_ON_A02 = FakeDetection((391, 375, 742, 1085), 0.49, "cell_phone")
BACKPACK_ON_A01 = FakeDetection((103, 457, 397, 1085), 0.28, "backpack")
SMALL_BOTTLE = FakeDetection((900, 500, 930, 560), 0.6, "bottle")
PERSON_NEAR = FakeDetection((800, 200, 1100, 1080), 0.9, "person")
MOTORCYCLE = FakeDetection((600, 400, 1000, 1000), 0.8, "motorcycle")


def test_box_area_clips_to_frame():
    assert box_area((0.0, 0.0, 0.5, 0.5)) == 0.25
    assert box_area((-0.5, 0.5, 0.5, 1.5)) == 0.25  # ส่วนที่ล้นภาพไม่นับ


def test_mode_off_counts_only_vehicles():
    boxes = select_vehicle_boxes([CAR_FAR, PHONE_ON_A02, BACKPACK_ON_A01], W, H, None)
    assert len(boxes) == 1


def test_mode_on_counts_large_misclassified_objects():
    boxes = select_vehicle_boxes([CAR_FAR, PHONE_ON_A02, BACKPACK_ON_A01], W, H, 0.03)
    assert len(boxes) == 3


def test_mode_on_ignores_small_objects():
    assert select_vehicle_boxes([SMALL_BOTTLE], W, H, 0.03) == []


def test_mode_on_never_counts_people_animals_or_motorcycles():
    assert select_vehicle_boxes([PERSON_NEAR, MOTORCYCLE], W, H, 0.01) == []


def test_real_cam1_slots_become_occupied_in_large_object_mode():
    """ช่อง A-02 ที่วาดเป็นแถบข้างรถ (พิกัดประมาณจากภาพจริง) ต้องขึ้นว่ามีรถเมื่อเปิดโหมดนี้"""
    slot_a02 = [[0.3354, 0.5519], [0.3812, 0.5537], [0.3854, 0.8704], [0.3313, 0.8667]]

    class Detector:
        def detect(self, image, other_classes_min_score=None):
            dets = [CAR_FAR]
            if other_classes_min_score is not None:
                dets += [d for d in (PHONE_ON_A02, BACKPACK_ON_A01) if d.score >= other_classes_min_score]
            return dets

    frame = np.zeros((H, W, 3), np.uint8)
    off = detect_vehicle_footprints(Detector(), frame, None)
    on = detect_vehicle_footprints(Detector(), frame, 0.03)
    assert not is_occupied(compute_slot_score(slot_a02, off), 0.3)
    assert is_occupied(compute_slot_score(slot_a02, on), 0.3)


def test_postprocess_other_classes_skips_vehicle_classes_and_names_correctly():
    decoded = np.zeros((3, 85), np.float32)
    decoded[:, :4] = [[100, 100, 50, 50], [300, 300, 60, 60], [500, 500, 40, 40]]
    decoded[:, 4] = 1.0
    phone_id = COCO_CLASS_NAMES.index("cell_phone")
    decoded[0, 5 + phone_id] = 0.5           # โทรศัพท์ -> ต้องได้
    decoded[1, 5 + 2] = 0.9                  # car -> ต้องไม่อยู่ในผลคลาสอื่น
    decoded[2, 5 + phone_id] = 0.1           # ต่ำกว่าเกณฑ์ -> ตัดทิ้ง
    result = _postprocess_other_classes(decoded, 1.0, LARGE_OBJECT_MIN_SCORE, 0.45)
    assert [d.class_name for d in result] == ["cell_phone"]
    assert result[0].box == (75.0, 75.0, 125.0, 125.0)
    assert all(name in COCO_CLASS_NAMES for name in VEHICLE_CLASSES.values())
