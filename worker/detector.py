"""Detector interface และการตรวจจับรถด้วยโมเดล YOLOX (ONNX Runtime) ตาม FR-2

หมายเหตุ: ขั้นตอน decode/postprocess อ้างอิงวิธีของ YOLOX (Apache-2.0)
เพราะโมเดลที่ export แบบนี้ยังไม่ decode กรอบในกราฟ ต้องแปลงเองหลัง inference
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np
import onnxruntime as ort

# คลาสของ COCO ที่สนใจ (ไม่นับ motorcycle ตาม FR-2)
VEHICLE_CLASSES = {2: "car", 5: "bus", 7: "truck"}

# ชื่อคลาสทั้ง 80 ของ COCO เรียงตาม class id — ใช้กับโหมด "นับวัตถุขนาดใหญ่เป็นรถ"
# (กล้องที่มองรถจากด้านบนใกล้ๆ โมเดลมักหากรอบเจอแต่ทายชื่อผิด เช่น cell_phone, suitcase)
COCO_CLASS_NAMES = (
    "person bicycle car motorcycle airplane bus train truck boat traffic_light fire_hydrant "
    "stop_sign parking_meter bench bird cat dog horse sheep cow elephant bear zebra giraffe "
    "backpack umbrella handbag tie suitcase frisbee skis snowboard sports_ball kite baseball_bat "
    "baseball_glove skateboard surfboard tennis_racket bottle wine_glass cup fork knife spoon bowl "
    "banana apple sandwich orange broccoli carrot hot_dog pizza donut cake chair couch "
    "potted_plant bed dining_table toilet tv laptop mouse remote keyboard cell_phone microwave "
    "oven toaster sink refrigerator book clock vase scissors teddy_bear hair_drier toothbrush"
).split()

INPUT_SIZE = (640, 640)  # (height, width) ตามที่โมเดล yolox_s ถูกเทรนมา
STRIDES = (8, 16, 32)


@dataclass
class Detection:
    """ผลตรวจจับ 1 คัน: กรอบพิกัดจริงบนภาพต้นฉบับ (x1, y1, x2, y2)"""

    box: tuple[float, float, float, float]
    score: float
    class_name: str


class Detector(Protocol):
    """สัญญากลางของตัวตรวจจับรถ เพื่อให้สลับโมเดลได้ภายหลังโดยไม่แก้โค้ดส่วนอื่น"""

    def detect(
        self, image: np.ndarray, other_classes_min_score: float | None = None
    ) -> list[Detection]: ...


class OnnxYoloxDetector:
    """ตรวจจับรถด้วยโมเดล YOLOX ที่ export เป็น ONNX"""

    def __init__(
        self,
        model_path: Path,
        conf_threshold: float = 0.35,
        nms_threshold: float = 0.45,
    ):
        self.session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name
        self.conf_threshold = conf_threshold
        self.nms_threshold = nms_threshold

    def detect(
        self, image: np.ndarray, other_classes_min_score: float | None = None
    ) -> list[Detection]:
        """ตรวจจับรถ (car/bus/truck) — ถ้าส่ง other_classes_min_score มา จะคืนวัตถุคลาสอื่น
        ที่ score ถึงเกณฑ์นี้มาด้วย (ใช้ inference รอบเดียวกัน ไม่เปลืองเพิ่ม)
        """
        padded, ratio = _preprocess(image, INPUT_SIZE)
        raw_output = self.session.run(None, {self.input_name: padded[None, :, :, :]})[0]
        decoded = _decode_outputs(raw_output[0], INPUT_SIZE)
        detections = _postprocess(decoded, ratio, self.conf_threshold, self.nms_threshold)
        if other_classes_min_score is not None:
            detections += _postprocess_other_classes(
                decoded, ratio, other_classes_min_score, self.nms_threshold
            )
        return detections


def _preprocess(image: np.ndarray, input_size: tuple[int, int]) -> tuple[np.ndarray, float]:
    """ย่อภาพแบบรักษาสัดส่วน (letterbox) แล้วเติมขอบสีเทา (114) ให้ครบขนาด input"""
    padded_img = np.full((input_size[0], input_size[1], 3), 114, dtype=np.uint8)
    ratio = min(input_size[0] / image.shape[0], input_size[1] / image.shape[1])
    new_w, new_h = int(image.shape[1] * ratio), int(image.shape[0] * ratio)
    resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    padded_img[:new_h, :new_w] = resized
    chw = padded_img.transpose(2, 0, 1).astype(np.float32)
    return np.ascontiguousarray(chw), ratio


def _decode_outputs(outputs: np.ndarray, input_size: tuple[int, int]) -> np.ndarray:
    """แปลงผลดิบของ YOLOX (anchor-free) ให้เป็นพิกัด cx,cy,w,h บนภาพขนาด input_size"""
    grids = []
    strides_per_point = []
    for stride in STRIDES:
        h, w = input_size[0] // stride, input_size[1] // stride
        xv, yv = np.meshgrid(np.arange(w), np.arange(h))
        grid = np.stack((xv, yv), axis=2).reshape(-1, 2)
        grids.append(grid)
        strides_per_point.append(np.full((grid.shape[0], 1), stride))
    grids = np.concatenate(grids, axis=0)
    strides_per_point = np.concatenate(strides_per_point, axis=0)

    decoded = outputs.copy()
    decoded[:, :2] = (decoded[:, :2] + grids) * strides_per_point
    decoded[:, 2:4] = np.exp(decoded[:, 2:4]) * strides_per_point
    return decoded


def _postprocess(
    decoded: np.ndarray, ratio: float, conf_threshold: float, nms_threshold: float
) -> list[Detection]:
    """กรองเฉพาะรถยนต์/รถบรรทุก/รถบัสที่ confidence พอ แล้วตัดกรอบซ้ำด้วย NMS"""
    boxes_cxcywh = decoded[:, :4]
    objectness = decoded[:, 4]
    class_scores = decoded[:, 5:]

    detections: list[Detection] = []
    for class_id, class_name in VEHICLE_CLASSES.items():
        scores = objectness * class_scores[:, class_id]
        keep_idx = np.where(scores >= conf_threshold)[0]
        if len(keep_idx) == 0:
            continue

        boxes_xywh = _cxcywh_to_xywh(boxes_cxcywh[keep_idx]) / ratio
        kept = cv2.dnn.NMSBoxes(
            boxes_xywh.tolist(), scores[keep_idx].tolist(), conf_threshold, nms_threshold
        )
        for i in np.array(kept).reshape(-1):
            x, y, w, h = boxes_xywh[i]
            box = (float(x), float(y), float(x + w), float(y + h))
            detections.append(Detection(box, float(scores[keep_idx][i]), class_name))
    return detections


def _postprocess_other_classes(
    decoded: np.ndarray, ratio: float, conf_threshold: float, nms_threshold: float
) -> list[Detection]:
    """วัตถุที่ไม่ใช่รถ: แต่ละจุดเลือกคลาสที่มั่นใจที่สุด (ไม่รวมคลาสรถ) แล้วตัดกรอบซ้ำด้วย NMS"""
    class_scores = decoded[:, 5:].copy()
    class_scores[:, list(VEHICLE_CLASSES)] = 0.0  # คลาสรถจัดการแยกใน _postprocess แล้ว
    class_ids = class_scores.argmax(axis=1)
    scores = decoded[:, 4] * class_scores[np.arange(len(class_ids)), class_ids]
    keep_idx = np.where(scores >= conf_threshold)[0]
    if len(keep_idx) == 0:
        return []

    boxes_xywh = _cxcywh_to_xywh(decoded[keep_idx, :4]) / ratio
    kept = cv2.dnn.NMSBoxes(boxes_xywh.tolist(), scores[keep_idx].tolist(), conf_threshold, nms_threshold)
    detections: list[Detection] = []
    for i in np.array(kept).reshape(-1):
        x, y, w, h = boxes_xywh[i]
        name = COCO_CLASS_NAMES[int(class_ids[keep_idx][i])]
        detections.append(Detection((float(x), float(y), float(x + w), float(y + h)), float(scores[keep_idx][i]), name))
    return detections


def _cxcywh_to_xywh(boxes: np.ndarray) -> np.ndarray:
    """แปลง (center_x, center_y, w, h) เป็น (x_top_left, y_top_left, w, h) สำหรับ cv2.dnn.NMSBoxes"""
    xywh = np.empty_like(boxes)
    xywh[:, 0] = boxes[:, 0] - boxes[:, 2] / 2
    xywh[:, 1] = boxes[:, 1] - boxes[:, 3] / 2
    xywh[:, 2] = boxes[:, 2]
    xywh[:, 3] = boxes[:, 3]
    return xywh
