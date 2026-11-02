"""สถานะเครื่อง Server (CPU / RAM / ดิสก์ / อุณหภูมิ / เวลาประมวลผล AI) สำหรับแถบสถานะที่หัวเว็บหลังบ้าน

แยกส่วน "อ่านค่าจากเครื่อง" (ใช้ psutil) กับ "ตัดสินระดับ" (pure function มี pytest) ออกจากกัน
ค่าที่อ่านได้ในคอนเทนเนอร์ Docker = ค่าของทั้งเครื่อง (host / VM) ไม่ใช่เฉพาะคอนเทนเนอร์
"""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import psutil

# เกณฑ์สี (เปอร์เซ็นต์ / องศา) — เขียว < warn ≤ เหลือง < crit ≤ แดง
LEVELS = {
    "cpu": (70.0, 90.0),
    "ram": (80.0, 92.0),
    "disk": (80.0, 90.0),
    "temp": (70.0, 85.0),
}
# AI ต่อรอบ: เวลาประมวลผลรวมทุกกล้อง เทียบกับรอบตรวจจับ (เกิน 50% = เริ่มตึง, เกิน 80% = ไม่ทัน)
AI_LEVELS = (50.0, 80.0)
# ชื่อเซนเซอร์อุณหภูมิ CPU ที่พบบ่อยบน Linux (Intel / AMD / Raspberry Pi / ACPI)
CPU_SENSORS = ("coretemp", "k10temp", "zenpower", "cpu_thermal", "cpu-thermal", "acpitz")


def level(kind: str, value: float | None) -> str:
    """ระดับของค่า: ok / warn / crit / none (อ่านไม่ได้)"""
    if value is None:
        return "none"
    warn, crit = LEVELS[kind]
    return "crit" if value >= crit else "warn" if value >= warn else "ok"


def ai_load_percent(infer_ms: list[float], intervals_s: list[int]) -> float | None:
    """สัดส่วนเวลาที่ worker ใช้ประมวลผล AI ต่อรอบ (%) — worker ทำทีละกล้องในเธรดเดียว

    กล้องแต่ละตัวต้องการ infer_ms ทุก ๆ interval วินาที → ภาระรวม = Σ infer / interval
    """
    pairs = [(ms, s) for ms, s in zip(infer_ms, intervals_s) if ms is not None and s]
    if not pairs:
        return None
    return round(sum(ms / 1000 / s for ms, s in pairs) * 100, 1)


def ai_level(load: float | None) -> str:
    if load is None:
        return "none"
    warn, crit = AI_LEVELS
    return "crit" if load >= crit else "warn" if load >= warn else "ok"


def pick_cpu_temperature(sensors: dict) -> float | None:
    """เลือกอุณหภูมิ CPU จากผล psutil.sensors_temperatures() — ใช้ค่าสูงสุดของเซนเซอร์ CPU ที่รู้จัก"""
    for name in CPU_SENSORS:
        readings = [r.current for r in sensors.get(name, []) if r.current is not None and 0 < r.current < 150]
        if readings:
            return round(max(readings), 1)
    others = [r.current for rs in sensors.values() for r in rs if r.current is not None and 0 < r.current < 150]
    return round(max(others), 1) if others else None


def read_temperature() -> float | None:
    """อุณหภูมิ CPU ถ้าอ่านได้ — Server ที่เป็น VM (เช่นบน Proxmox) ส่วนใหญ่ไม่มีเซนเซอร์ จะได้ None"""
    sensors_fn = getattr(psutil, "sensors_temperatures", None)
    if sensors_fn is None:
        return None
    try:
        return pick_cpu_temperature(sensors_fn() or {})
    except Exception:  # noqa: BLE001 — บางเครื่องอ่าน /sys ไม่ได้ ถือว่าไม่มีเซนเซอร์
        return None


_cache: dict = {"at": 0.0, "data": None}
CACHE_SECONDS = 5  # หลายคนเปิดหน้าพร้อมกันจะไม่วัด CPU ซ้ำ ๆ


def read_machine(data_dir: Path) -> dict:
    """อ่านค่าเครื่อง (แคช 5 วินาที)"""
    now = time.monotonic()
    if _cache["data"] is not None and now - _cache["at"] < CACHE_SECONDS:
        return _cache["data"]
    vm = psutil.virtual_memory()
    try:
        disk = shutil.disk_usage(data_dir)
        disk_used, disk_total = disk.used, disk.total
    except OSError:
        disk_used = disk_total = None
    try:
        load1 = os.getloadavg()[0]
    except (OSError, AttributeError):
        load1 = None  # Windows ไม่มี load average
    data = {
        "cpu_percent": psutil.cpu_percent(interval=0.3),
        "cpu_count": psutil.cpu_count() or 1,
        "load1": round(load1, 2) if load1 is not None else None,
        "ram_used_gb": round((vm.total - vm.available) / 1024 ** 3, 1),
        "ram_total_gb": round(vm.total / 1024 ** 3, 1),
        "ram_percent": round(vm.percent, 1),
        "disk_used_gb": round(disk_used / 1024 ** 3, 1) if disk_total else None,
        "disk_total_gb": round(disk_total / 1024 ** 3, 1) if disk_total else None,
        "disk_percent": round(disk_used / disk_total * 100, 1) if disk_total else None,
        "temperature_c": read_temperature(),
        "uptime_h": round((time.time() - psutil.boot_time()) / 3600, 1),
    }
    _cache.update(at=now, data=data)
    return data
