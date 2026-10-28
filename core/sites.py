"""สิทธิ์รายสถานที่ (TOR 4.6) — pure function ไม่ยุ่งกับ DB"""
from __future__ import annotations


def effective_site_ids(role: str, site_ids: list | None) -> list[int] | None:
    """สถานที่ที่ผู้ใช้ดูแลได้: None = ทุกแห่ง

    Admin ดูแลทุกแห่งเสมอ (กันกรณีจำกัดแล้วไม่มีใครจัดการระบบได้)
    เจ้าหน้าที่/ผู้ชมที่ถูกจำกัดแต่รายการว่าง = ไม่เห็นสถานที่ใดเลย
    """
    if role == "admin" or site_ids is None:
        return None
    return sorted({int(s) for s in site_ids if isinstance(s, (int, str)) and str(s).isdigit()})


def normalize_site_ids(role: str, requested: list | None, existing_site_ids: set[int]) -> list[int] | None:
    """แปลงค่าที่ Admin เลือกมาก่อนเก็บ: ตัด id ที่ไม่มีอยู่จริงทิ้ง

    requested=None หรือบทบาท Admin -> None (= ทุกแห่ง รวมแห่งที่เพิ่มในอนาคต)
    """
    if requested is None or role == "admin":
        return None
    chosen = sorted({int(s) for s in requested if str(s).isdigit() and int(s) in existing_site_ids})
    return chosen


def google_maps_directions_url(latitude: float | None, longitude: float | None) -> str | None:
    """ลิงก์นำทางที่เปิดได้ทั้งแอป Google Maps บนมือถือและเว็บ (ไม่ต้องใช้ API key)"""
    if latitude is None or longitude is None:
        return None
    return f"https://www.google.com/maps/dir/?api=1&destination={latitude:.6f},{longitude:.6f}"
