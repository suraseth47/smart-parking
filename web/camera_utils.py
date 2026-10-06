"""ฟังก์ชันช่วยเกี่ยวกับกล้องที่ web/routers ใช้ร่วมกัน"""
from __future__ import annotations

from core.models import Camera
from core.rtsp import build_rtsp_url
from core.security import decrypt_camera_password


def build_camera_url(camera: Camera) -> str:
    """ถอดรหัสผ่านกล้องแล้วประกอบเป็น RTSP URL เต็ม (ใช้ตอนต่อกล้องจริงเท่านั้น)"""
    password = decrypt_camera_password(camera.password_enc) if camera.password_enc else ""
    return build_rtsp_url(
        brand=camera.brand,
        host=camera.host,
        port=camera.port,
        channel=camera.channel,
        stream=camera.stream,
        username=camera.username or "",
        password=password,
        rtsp_url_custom=camera.rtsp_url_custom,
    )
