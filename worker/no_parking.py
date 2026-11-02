"""เขตห้ามจอด / รถจอดซ้อนคัน — นับรถที่ "จอดนิ่ง" ในเขตที่วาดไว้ แล้วแจ้งเตือนหลังบ้าน

แนวคิด
- ผู้ดูแลวาดเขตห้ามจอด (ทางวิ่ง หน้าทางออก หน้าช่องคนพิการ) ในหน้ากำหนดช่องจอด
- ทุกรอบตรวจจับ: footprint ของรถ (ครึ่งล่างของกรอบ) ที่อยู่ในเขต >= ครึ่งหนึ่ง ถือว่าอยู่ในเขต
- ติดตามรถแต่ละคันด้วยการเทียบตำแหน่งกับรอบก่อน (IoU) — รถที่วิ่งผ่าน/วนหาที่จอด
  ตำแหน่งเปลี่ยนทุกรอบ จะเริ่มนับเวลาใหม่ทุกครั้ง จึงไม่ถูกนับว่า "จอด"
- รถที่อยู่ตำแหน่งเดิมต่อเนื่อง >= dwell นาที = จอดในเขตห้ามจอด
- AI พลาดไม่เห็นรถได้ไม่เกิน MAX_MISSES รอบติดกัน (กันกระพริบ แบบเดียวกับ debounce ของช่องจอด)

ฟังก์ชันส่วนคำนวณเป็น pure function (ไม่ยุ่ง DB) — ทดสอบได้ใน tests/test_no_parking.py
"""
from __future__ import annotations

from datetime import datetime, timedelta

from shapely.geometry import Polygon, box
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models import Alert, AlertLevel

BoxXYXY = tuple[float, float, float, float]

IN_ZONE_MIN_FRACTION = 0.5  # footprint ต้องอยู่ในเขต >= 50% ของพื้นที่ footprint
TRACK_MATCH_IOU = 0.4  # ตำแหน่งรอบนี้ทับรอบก่อน >= ค่านี้ = รถคันเดิมที่ยังจอดอยู่
MAX_MISSES = 2  # AI ไม่เห็นรถคันนี้ได้ไม่เกิน 2 รอบติดกัน ก่อนถือว่ารถออกไปแล้ว
DEFAULT_DWELL_MIN = 5
MAX_ZONES = 20
ACK_SNOOZE = timedelta(hours=1)  # กด "รับทราบ" แล้ว ไม่แจ้งเรื่องเดิมของกล้องนี้ซ้ำภายใน 1 ชั่วโมง


def alert_source(camera_id: int) -> str:
    return f"camera:{camera_id}:no_parking"


def zone_shape(polygon: list[list[float]]) -> Polygon | None:
    if not polygon or len(polygon) < 3:
        return None
    shape = Polygon(polygon)
    if not shape.is_valid:
        shape = shape.buffer(0)  # รูปที่เส้นตัดกันเอง → แก้ให้ใช้ได้
    return shape if shape.area > 0 else None


def footprint_zone(footprint: BoxXYXY, zones: list[tuple[str, Polygon]]) -> str | None:
    """คืน id ของเขตที่ footprint อยู่ข้างใน (เลือกเขตที่ทับมากที่สุด) หรือ None"""
    fp = box(*footprint)
    if fp.area <= 0:
        return None
    best_id, best_fraction = None, 0.0
    for zone_id, shape in zones:
        fraction = fp.intersection(shape).area / fp.area
        if fraction > best_fraction:
            best_id, best_fraction = zone_id, fraction
    return best_id if best_fraction >= IN_ZONE_MIN_FRACTION else None


def iou(a: BoxXYXY, b: BoxXYXY) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def update_tracks(tracks: list[dict], detections: list[tuple[str, BoxXYXY]], now: datetime) -> list[dict]:
    """จับคู่รถในเขตรอบนี้กับรถที่ติดตามอยู่ (IoU สูงสุดก่อน) แล้วคืนรายการติดตามชุดใหม่

    tracks: [{"zone", "box", "first", "last", "miss"}] (เวลาเป็น ISO string เก็บลง JSON ได้)
    detections: [(zone_id, footprint), ...] ของรอบนี้
    """
    stamp = now.isoformat(timespec="seconds")
    pairs = []
    for ti, track in enumerate(tracks):
        for di, (zone_id, fp) in enumerate(detections):
            if zone_id != track["zone"]:
                continue
            score = iou(tuple(track["box"]), fp)
            if score >= TRACK_MATCH_IOU:
                pairs.append((score, ti, di))
    pairs.sort(reverse=True)

    used_tracks: set[int] = set()
    used_dets: set[int] = set()
    result: list[dict] = []
    for _score, ti, di in pairs:
        if ti in used_tracks or di in used_dets:
            continue
        used_tracks.add(ti)
        used_dets.add(di)
        track = dict(tracks[ti])
        track["box"] = [round(v, 4) for v in detections[di][1]]
        track["last"] = stamp
        track["miss"] = 0
        result.append(track)

    for ti, track in enumerate(tracks):
        if ti in used_tracks:
            continue
        miss = int(track.get("miss", 0)) + 1
        if miss <= MAX_MISSES:
            result.append({**track, "miss": miss})

    for di, (zone_id, fp) in enumerate(detections):
        if di not in used_dets:
            result.append({"zone": zone_id, "box": [round(v, 4) for v in fp], "first": stamp, "last": stamp, "miss": 0})
    return result


def parked_tracks(tracks: list[dict], dwell_min: int) -> list[dict]:
    """รถที่อยู่ตำแหน่งเดิมต่อเนื่องนานถึงเกณฑ์ = จอดในเขตห้ามจอด"""
    need = timedelta(minutes=max(1, dwell_min))
    out = []
    for track in tracks:
        try:
            stayed = datetime.fromisoformat(track["last"]) - datetime.fromisoformat(track["first"])
        except (KeyError, ValueError):
            continue
        if stayed >= need:
            out.append(track)
    return out


def summarize(zones: list[dict], tracks: list[dict], dwell_min: int, now: datetime | None = None) -> list[dict]:
    """สรุปรายเขต: [{"id", "name", "count", "longest_min"}] เฉพาะเขตที่มีรถจอดอยู่"""
    now = now or datetime.utcnow()
    names = {z.get("id"): z.get("name") or "เขตห้ามจอด" for z in zones}
    result: dict[str, dict] = {}
    for track in parked_tracks(tracks, dwell_min):
        zone_id = track["zone"]
        if zone_id not in names:
            continue
        item = result.setdefault(zone_id, {"id": zone_id, "name": names[zone_id], "count": 0, "longest_min": 0})
        item["count"] += 1
        minutes = int((now - datetime.fromisoformat(track["first"])).total_seconds() // 60)
        item["longest_min"] = max(item["longest_min"], minutes)
    order = list(names)
    return sorted(result.values(), key=lambda x: order.index(x["id"]))


def alert_message(camera_name: str, summary: list[dict], dwell_min: int) -> str:
    total = sum(item["count"] for item in summary)
    if len(summary) == 1:
        where = summary[0]["name"]
    else:
        where = ", ".join(f"{item['name']} {item['count']} คัน" for item in summary)
    return f"กล้อง {camera_name}: พบรถจอดในเขตห้ามจอด {total} คัน ({where}) จอดนานเกิน {dwell_min} นาที"


def process_no_parking(db: Session, camera, footprints: list[BoxXYXY], now: datetime) -> list[dict]:
    """รอบตรวจจับ 1 รอบของกล้อง: อัปเดตการติดตาม + เปิด/ปิดแจ้งเตือน คืนสรุปรายเขต"""
    zones = [z for z in (camera.no_parking_zones or []) if isinstance(z, dict)]
    shapes = [(z.get("id"), zone_shape(z.get("polygon") or [])) for z in zones]
    shapes = [(zid, shape) for zid, shape in shapes if zid and shape is not None]
    if not shapes:
        clear_no_parking(db, camera)
        return []

    detections = []
    for fp in footprints:
        zone_id = footprint_zone(fp, shapes)
        if zone_id:
            detections.append((zone_id, fp))

    previous = (camera.no_parking_state or {}).get("tracks") or []
    tracks = update_tracks(previous, detections, now)
    camera.no_parking_state = {"updated_at": now.isoformat(timespec="seconds"), "tracks": tracks}

    dwell = camera.no_parking_dwell_min or DEFAULT_DWELL_MIN
    summary = summarize(zones, tracks, dwell, now)
    if summary:
        upsert_alert(db, alert_source(camera.id), alert_message(camera.name, summary, dwell))
    else:
        close_alert(db, alert_source(camera.id))
    return summary


def clear_no_parking(db: Session, camera) -> None:
    """ไม่มีเขต / กล้องขาด / กล้องถูกขยับ → ล้างการติดตาม และปิดแจ้งเตือน (ข้อมูลเชื่อถือไม่ได้)"""
    if camera.no_parking_state:
        camera.no_parking_state = None
    close_alert(db, alert_source(camera.id))


def upsert_alert(db: Session, source: str, message: str) -> None:
    """เปิดแจ้งเตือน หรือแก้ข้อความของแจ้งเตือนที่เปิดอยู่ (จำนวนรถเปลี่ยน ไม่ต้องเริ่มนับเวลาใหม่)"""
    existing = db.scalar(
        select(Alert).where(Alert.source == source, Alert.resolved_at.is_(None)).order_by(Alert.created_at.desc())
    )
    if existing is not None:
        if existing.message != message:
            existing.message = message
        return
    acked = db.scalar(
        select(Alert)
        .where(
            Alert.source == source,
            Alert.resolved_by.is_not(None),
            Alert.resolved_at >= datetime.utcnow() - ACK_SNOOZE,
        )
        .limit(1)
    )
    if acked is not None:
        return
    db.add(Alert(level=AlertLevel.WARNING, source=source, message=message))


def close_alert(db: Session, source: str) -> None:
    now = datetime.utcnow()
    for alert in db.scalars(select(Alert).where(Alert.source == source, Alert.resolved_at.is_(None))).all():
        alert.resolved_at = now


def validate_zones(zones: list[dict]) -> list[dict]:
    """ตรวจ/ทำความสะอาดข้อมูลเขตจากหน้าเว็บ — ValueError พร้อมข้อความภาษาไทยถ้าผิด"""
    if len(zones) > MAX_ZONES:
        raise ValueError(f"วาดเขตห้ามจอดได้ไม่เกิน {MAX_ZONES} เขตต่อกล้อง")
    clean: list[dict] = []
    seen: set[str] = set()
    for index, zone in enumerate(zones, start=1):
        zone_id = str(zone.get("id") or f"npz-{index}")[:20]
        if zone_id in seen:
            zone_id = f"npz-{index}"
        seen.add(zone_id)
        name = str(zone.get("name") or "").strip()[:50] or f"เขตห้ามจอด {index}"
        polygon = zone.get("polygon") or []
        if len(polygon) < 3 or len(polygon) > 30:
            raise ValueError(f"{name}: ต้องมี 3-30 จุด")
        points = []
        for point in polygon:
            if len(point) != 2:
                raise ValueError(f"{name}: พิกัดไม่ถูกต้อง")
            x, y = float(point[0]), float(point[1])
            points.append([round(min(max(x, 0.0), 1.0), 4), round(min(max(y, 0.0), 1.0), 4)])
        if zone_shape(points) is None:
            raise ValueError(f"{name}: พื้นที่เป็นศูนย์ — วาดใหม่ให้เป็นรูปปิด")
        clean.append({"id": zone_id, "name": name, "polygon": points})
    return clean
