"""ทดสอบเชื่อมต่อกล้องจริงผ่าน ffmpeg แล้วแปล error ให้ Admin อ่านเข้าใจ (FR-22)"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ConnectionTestResult:
    ok: bool
    message: str
    snapshot_path: Path | None = None


def check_camera_connection(source: str, output_path: Path, timeout_s: int = 10) -> ConnectionTestResult:
    """เรียก ffmpeg ดึง 1 เฟรมจาก source (RTSP URL หรือไฟล์วิดีโอ/ภาพ)"""
    command = ["ffmpeg", "-y"]
    if source.startswith("rtsp://"):
        # option พวกนี้เป็นของโปรโตคอล RTSP เท่านั้น ใส่กับไฟล์ธรรมดาไม่ได้
        command += ["-rtsp_transport", "tcp", "-timeout", str(timeout_s * 1_000_000)]
    command += ["-i", source, "-frames:v", "1", str(output_path)]
    try:
        # encoding ระบุตรงๆ เป็น utf-8 เพราะ default locale encoding ของเครื่อง (เช่น cp874
        # บน Windows ไทย) ถอดข้อความ build ของ ffmpeg ไม่ได้ ทำให้ subprocess พังระหว่างอ่าน stderr
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s + 5,
        )
    except subprocess.TimeoutExpired:
        return ConnectionTestResult(ok=False, message="หมดเวลาเชื่อมต่อกล้อง (timeout)")

    if result.returncode == 0 and output_path.exists():
        return ConnectionTestResult(ok=True, message="เชื่อมต่อสำเร็จ", snapshot_path=output_path)

    return ConnectionTestResult(ok=False, message=classify_ffmpeg_error(result.stderr))


def classify_ffmpeg_error(stderr: str) -> str:
    """แปลงข้อความ error ดิบของ ffmpeg เป็นข้อความภาษาไทยที่ Admin อ่านเข้าใจ (FR-22)"""
    lower = stderr.lower()
    if "401" in lower or "unauthorized" in lower:
        return "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง (401 Unauthorized)"
    if "404" in lower or "not found" in lower:
        return "ไม่พบ stream นี้บนกล้อง (ตรวจ channel/stream path)"
    if "timed out" in lower or "timeout" in lower:
        return "หมดเวลาเชื่อมต่อกล้อง (ตรวจ IP/network/firewall)"
    if "connection refused" in lower:
        return "กล้องปฏิเสธการเชื่อมต่อ (ตรวจ IP/port)"
    if "no route to host" in lower:
        return "เข้าถึงกล้องไม่ได้ (ตรวจ network/VLAN)"
    return "เชื่อมต่อกล้องไม่สำเร็จ (ดู log เพิ่มเติม)"
