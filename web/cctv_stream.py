"""ดึงภาพสดจากกล้องสำหรับหน้า "กล้องวงจรปิด" ในหลังบ้าน (ภาพนิ่งอัปเดตทุก ~1 วินาที)

หลักการ:
- เปิดการเชื่อมต่อ RTSP ของกล้อง "เฉพาะตอนมีคนเปิดดู" (1 thread ต่อกล้อง)
- อ่านเฟรมต่อเนื่องเพื่อไม่ให้ภาพค้างใน buffer แต่บีบอัดเป็น JPEG แค่ทุก FRAME_INTERVAL_S
- ไม่มีใครขอภาพเกิน IDLE_STOP_S วินาที -> ปิดการเชื่อมต่อเอง (ไม่กินเน็ตของวัดตลอดเวลา)
- ใช้สตรีมย่อย (substream) ถ้าทำได้ เพื่อลดแบนด์วิดท์
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime

import cv2

FRAME_INTERVAL_S = 1.0
IDLE_STOP_S = 20.0
RECONNECT_DELAY_S = 3.0
MAX_WIDTH = 960
JPEG_QUALITY = 70
MAX_ACTIVE_CAMERAS = 8


def prefer_substream(url: str) -> str:
    """เปลี่ยน RTSP URL ของ Dahua/Hikvision ให้เป็นสตรีมย่อย (ความละเอียดต่ำกว่า ใช้เน็ตน้อยกว่า)

    - Dahua: subtype=0 -> subtype=1
    - Hikvision: /Streaming/Channels/<ch>01 -> <ch>02
    URL รูปแบบอื่นคืนค่าเดิม
    """
    if "subtype=0" in url:
        return url.replace("subtype=0", "subtype=1")
    marker = "/Streaming/Channels/"
    if marker in url:
        head, tail = url.split(marker, 1)
        digits = "".join(ch for ch in tail if ch.isdigit())
        rest = tail[len(digits):]
        if len(digits) >= 3 and digits.endswith("01"):
            return f"{head}{marker}{digits[:-2]}02{rest}"
    return url


def scaled_size(width: int, height: int, max_width: int = MAX_WIDTH) -> tuple[int, int]:
    """ย่อภาพให้กว้างไม่เกิน max_width โดยคงสัดส่วน (ไม่ขยายภาพเล็ก)"""
    if width <= max_width:
        return width, height
    ratio = max_width / width
    return max_width, max(1, round(height * ratio))


@dataclass
class _Grabber:
    camera_id: int
    url: str
    lock: threading.Lock = field(default_factory=threading.Lock)
    jpeg: bytes | None = None
    frame_at: datetime | None = None
    error: str | None = None
    last_access: float = field(default_factory=time.monotonic)
    stopped: bool = False

    def touch(self) -> None:
        self.last_access = time.monotonic()

    def is_idle(self) -> bool:
        return time.monotonic() - self.last_access > IDLE_STOP_S

    def run(self) -> None:
        if self.url.startswith("rtsp://"):
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
        try:
            while not self.is_idle():
                cap = cv2.VideoCapture(self.url)
                if not cap.isOpened():
                    self.error = "เชื่อมต่อกล้องไม่ได้"
                    cap.release()
                    time.sleep(RECONNECT_DELAY_S)
                    continue
                self._read_loop(cap)
                cap.release()
        finally:
            self.stopped = True

    def _read_loop(self, cap) -> None:
        last_encode = 0.0
        is_stream = self.url.startswith("rtsp://")
        while not self.is_idle():
            ok, frame = cap.read()
            if not ok or frame is None:
                self.error = "สัญญาณภาพขาดหาย กำลังเชื่อมต่อใหม่"
                return
            now = time.monotonic()
            if now - last_encode >= FRAME_INTERVAL_S:
                last_encode = now
                self._store(frame)
            if not is_stream:
                time.sleep(0.04)  # ไฟล์วิดีโอ (ตอนทดสอบ) อย่าอ่านเร็วเกินจริง

    def _store(self, frame) -> None:
        h, w = frame.shape[:2]
        new_w, new_h = scaled_size(w, h)
        if (new_w, new_h) != (w, h):
            frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        if ok:
            with self.lock:
                self.jpeg = buf.tobytes()
                self.frame_at = datetime.utcnow()
                self.error = None


class LiveFrameManager:
    """เก็บ grabber ของแต่ละกล้อง เปิด/ปิดตามความต้องการ"""

    def __init__(self) -> None:
        self._grabbers: dict[int, _Grabber] = {}
        self._lock = threading.Lock()

    def get_frame(self, camera_id: int, url: str, wait_s: float = 6.0) -> tuple[bytes | None, datetime | None, str | None]:
        """คืน (jpeg, เวลาเฟรมแบบ UTC, ข้อความ error) — เริ่มดึงภาพถ้ายังไม่ได้เริ่ม"""
        grabber = self._ensure(camera_id, url)
        if grabber is None:
            return None, None, f"เปิดดูพร้อมกันได้สูงสุด {MAX_ACTIVE_CAMERAS} กล้อง"
        grabber.touch()
        deadline = time.monotonic() + wait_s
        while grabber.jpeg is None and time.monotonic() < deadline and not grabber.stopped:
            time.sleep(0.2)
        with grabber.lock:
            return grabber.jpeg, grabber.frame_at, grabber.error

    def _ensure(self, camera_id: int, url: str) -> _Grabber | None:
        with self._lock:
            for cid in [cid for cid, g in self._grabbers.items() if g.stopped]:
                del self._grabbers[cid]
            grabber = self._grabbers.get(camera_id)
            if grabber is not None and grabber.url == url:
                return grabber
            if grabber is None and len(self._grabbers) >= MAX_ACTIVE_CAMERAS:
                return None
            grabber = _Grabber(camera_id=camera_id, url=url)
            self._grabbers[camera_id] = grabber
            threading.Thread(target=grabber.run, name=f"cctv-{camera_id}", daemon=True).start()
            return grabber


live_frames = LiveFrameManager()
