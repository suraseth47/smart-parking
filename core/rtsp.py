"""ประกอบ RTSP URL จาก preset ของแต่ละยี่ห้อกล้อง (SPEC ข้อ 5.5) — pure function"""
from __future__ import annotations

from core.models import CameraBrand, CameraStream


def build_rtsp_url(
    brand: CameraBrand,
    host: str,
    port: int,
    channel: int,
    stream: CameraStream,
    username: str,
    password: str,
    rtsp_url_custom: str | None,
) -> str:
    """คืน RTSP URL เต็มสำหรับต่อกล้อง; โยน ValueError ถ้าข้อมูลไม่พอ"""
    if brand == CameraBrand.CUSTOM:
        if not rtsp_url_custom:
            raise ValueError("กล้อง custom ต้องกรอก RTSP URL เอง")
        return rtsp_url_custom

    if brand == CameraBrand.HIKVISION:
        suffix = "01" if stream == CameraStream.MAIN else "02"
        return f"rtsp://{username}:{password}@{host}:{port}/Streaming/Channels/{channel}{suffix}"

    if brand == CameraBrand.DAHUA:
        subtype = 0 if stream == CameraStream.MAIN else 1
        return (
            f"rtsp://{username}:{password}@{host}:{port}"
            f"/cam/realmonitor?channel={channel}&subtype={subtype}"
        )

    raise ValueError(f"ไม่รู้จักยี่ห้อกล้อง: {brand}")
