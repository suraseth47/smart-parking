"""กติกานับช่องว่างสำหรับหน้าเว็บสาธารณะ (FR-12..15) — pure function ใช้ร่วม web/worker"""
from __future__ import annotations

from dataclasses import dataclass

COUNTABLE_TYPES = {"normal", "disabled", "ev"}  # reserved ไม่นับเป็นที่ว่างสาธารณะ (FR-12)
UNKNOWN_RATIO_NO_DATA = 0.5  # unknown >= 50% ของโซน -> "ไม่มีข้อมูล" (FR-14)


@dataclass
class SlotInfo:
    """ข้อมูลช่องจอด 1 ช่อง เท่าที่ต้องใช้คำนวณยอดสาธารณะ"""

    zone_id: int
    type: str  # "normal" | "disabled" | "ev" | "reserved"
    state: str  # "free" | "occupied" | "unknown"
    is_active: bool
    layout_status: str  # "draft" | "published"
    code: str = ""


@dataclass
class ZoneInfo:
    """ข้อมูลโซน 1 โซน"""

    id: int
    code: str
    name_th: str
    name_en: str
    is_public: bool
    is_closed: bool


@dataclass
class ZoneSummary:
    code: str
    name_th: str
    name_en: str
    status: str  # "ok" | "partial" | "no_data" | "closed"
    free: int | None = None
    capacity: int | None = None
    free_disabled: int | None = None
    free_ev: int | None = None


@dataclass
class TotalSummary:
    free: int
    capacity: int
    free_disabled: int
    free_ev: int
    excluded_zones: list[str]


def filter_countable_slots(slots: list[SlotInfo]) -> list[SlotInfo]:
    """กรองเฉพาะช่องที่นับยอดสาธารณะได้: published, is_active, type ไม่ใช่ reserved (FR-12)"""
    return [
        s
        for s in slots
        if s.layout_status == "published" and s.is_active and s.type in COUNTABLE_TYPES
    ]


def summarize_zone(zone: ZoneInfo, slots: list[SlotInfo]) -> ZoneSummary:
    """สรุปยอดว่างของ 1 โซน (FR-13, FR-14)"""
    if zone.is_closed:
        return ZoneSummary(code=zone.code, name_th=zone.name_th, name_en=zone.name_en, status="closed")

    countable = filter_countable_slots(slots)
    capacity = len(countable)
    if capacity == 0:
        return ZoneSummary(code=zone.code, name_th=zone.name_th, name_en=zone.name_en, status="no_data")

    unknown_ratio = sum(1 for s in countable if s.state == "unknown") / capacity
    if unknown_ratio >= UNKNOWN_RATIO_NO_DATA:
        return ZoneSummary(code=zone.code, name_th=zone.name_th, name_en=zone.name_en, status="no_data")

    free_slots = [s for s in countable if s.state == "free"]
    status = "partial" if unknown_ratio > 0 else "ok"

    return ZoneSummary(
        code=zone.code,
        name_th=zone.name_th,
        name_en=zone.name_en,
        status=status,
        free=len(free_slots),
        capacity=capacity,
        free_disabled=sum(1 for s in free_slots if s.type == "disabled"),
        free_ev=sum(1 for s in free_slots if s.type == "ev"),
    )


def summarize_total(zone_summaries: list[ZoneSummary]) -> TotalSummary:
    """รวมยอดทั้งลาน ไม่นับโซนที่ no_data/closed และแจ้งว่าตัดโซนไหนออกไปบ้าง (FR-14, FR-15)"""
    included = [z for z in zone_summaries if z.status in ("ok", "partial")]
    excluded_zones = [z.code for z in zone_summaries if z.status in ("no_data", "closed")]

    return TotalSummary(
        free=sum(z.free or 0 for z in included),
        capacity=sum(z.capacity or 0 for z in included),
        free_disabled=sum(z.free_disabled or 0 for z in included),
        free_ev=sum(z.free_ev or 0 for z in included),
        excluded_zones=excluded_zones,
    )


def build_public_summary(
    zones: list[ZoneInfo], slots: list[SlotInfo]
) -> tuple[list[ZoneSummary], TotalSummary]:
    """ประกอบข้อมูลสรุปทั้งหมดสำหรับ /api/public/summary (FR-12..15)

    โซนที่ is_public=False จะไม่ถูกนำมาแสดงเลย (ไม่ใช่แค่ไม่นับรวม)
    """
    public_zones = [z for z in zones if z.is_public]
    summaries = [
        summarize_zone(zone, [s for s in slots if s.zone_id == zone.id]) for zone in public_zones
    ]
    return summaries, summarize_total(summaries)


def build_zone_slot_map(zone: ZoneInfo, slots: list[SlotInfo]) -> list[dict] | None:
    """รายการช่องจอดของ 1 โซนสำหรับแสดงเป็นแผนผังในหน้าสาธารณะ เรียงตามรหัส (ต่อขยาย FR-17)

    คืน None ถ้าโซนปิด (ไม่ต้องแสดงแผนผัง) — มิฉะนั้นคืนเฉพาะช่องที่นับยอดสาธารณะได้
    (ตัด reserved/draft/inactive ออกตาม FR-12) เรียงรหัสจากน้อยไปมาก
    """
    if zone.is_closed:
        return None
    countable = filter_countable_slots(slots)
    return sorted(
        ({"code": s.code, "state": s.state} for s in countable),
        key=lambda item: item["code"],
    )


def build_slot_maps(zones: list[ZoneInfo], slots: list[SlotInfo]) -> dict[str, list[dict] | None]:
    """สร้างแผนผังช่องจอดของทุกโซนสาธารณะ ใช้คู่กับ build_public_summary"""
    public_zones = [z for z in zones if z.is_public]
    return {
        zone.code: build_zone_slot_map(zone, [s for s in slots if s.zone_id == zone.id])
        for zone in public_zones
    }
