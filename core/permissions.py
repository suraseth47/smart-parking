"""สิทธิ์รายเมนู — pure function ไม่ยุ่งกับ DB

แต่ละบทบาทมี "เพดานสิทธิ์" (ทำได้สูงสุดแค่ไหน) Admin ติ๊กลดสิทธิ์ของผู้ใช้แต่ละคนได้
แต่เพิ่มเกินเพดานของบทบาทไม่ได้ — เช่น ผู้ชมจะได้สิทธิ์กล้องวงจรปิดไม่ได้เด็ดขาด
ผู้ดูแลระบบได้ทุกเมนูเสมอ (กันกรณีติ๊กออกแล้วไม่มีใครจัดการระบบได้)

users.permissions = None หมายถึง "ใช้สิทธิ์ตามบทบาท" (ทุกเมนูที่บทบาทนั้นทำได้)
"""
from __future__ import annotations

# (คีย์, ชื่อไทย, ชื่ออังกฤษ) เรียงตามเมนูด้านซ้าย
PERMISSIONS: list[tuple[str, str, str]] = [
    ("live", "สถานะช่องจอดสด", "Live Status"),
    ("cctv", "กล้องวงจรปิด", "CCTV Monitor"),
    ("override", "แก้สถานะช่องด้วยมือ", "Manual Override"),
    ("reports", "รายงานและสถิติ", "Reports"),
    ("cameras", "กล้องและช่องจอด", "Cameras & Slots"),
    ("calibration", "ช่วยวาดช่องอัตโนมัติ", "Auto Slot Setup"),
    ("validation", "ทดสอบความแม่นยำ", "Accuracy Test"),
    ("users", "ผู้ใช้และสิทธิ์", "Users & Access"),
    ("audit", "ประวัติการใช้งาน", "Audit Log"),
    ("settings", "ตั้งค่าความปลอดภัย", "Security Settings"),
]
ALL_KEYS: tuple[str, ...] = tuple(key for key, _, _ in PERMISSIONS)

ROLE_MAX: dict[str, tuple[str, ...]] = {
    "admin": ALL_KEYS,
    "operator": ("live", "cctv", "override", "reports"),
    "viewer": ("live", "reports"),
}


def role_permissions(role: str) -> tuple[str, ...]:
    """เพดานสิทธิ์ของบทบาท (บทบาทที่ไม่รู้จัก = ไม่มีสิทธิ์อะไร)"""
    return ROLE_MAX.get(role, ())


def effective_permissions(role: str, custom: list[str] | None) -> list[str]:
    """สิทธิ์ที่ใช้จริง = สิทธิ์ที่ติ๊กไว้ ∩ เพดานของบทบาท (เรียงตามเมนู)"""
    allowed = role_permissions(role)
    if role == "admin" or custom is None:
        return list(allowed)
    chosen = set(custom)
    return [key for key in allowed if key in chosen]


def normalize_permissions(role: str, requested: list[str] | None) -> list[str] | None:
    """แปลงค่าที่ Admin ติ๊กมาให้เก็บลง DB: ตัดสิทธิ์ที่เกินบทบาททิ้ง
    และคืน None ถ้าเท่ากับสิทธิ์เต็มของบทบาท (จะได้ตามบทบาทอัตโนมัติถ้าภายหลังเพิ่มเมนูใหม่)
    """
    if requested is None or role == "admin":
        return None
    allowed = role_permissions(role)
    chosen = [key for key in allowed if key in set(requested)]
    return None if len(chosen) == len(allowed) else chosen


def has_any_permission(role: str, custom: list[str] | None, keys: tuple[str, ...]) -> bool:
    granted = set(effective_permissions(role, custom))
    return any(key in granted for key in keys)
