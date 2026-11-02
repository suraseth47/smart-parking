"""อีเมลแจ้งเตือนผู้ดูแล — กล้องขาดการเชื่อมต่อ / กล้องถูกขยับ / รถจอดในเขตห้ามจอด

ตั้งค่าที่ ตั้งค่าระบบ → อีเมลและลิงก์คำเชิญ → อีเมลแจ้งเตือน (เก็บในตาราง settings คีย์ "alert_mail")
ใช้ค่า SMTP ชุดเดียวกับอีเมลคำเชิญ

กติกา (worker เรียก process_alert_mail ทุก 1 นาที)
- แจ้งเตือนต้องค้างนานถึง delay_min นาทีก่อนส่ง (กันกล้องหลุดแวบเดียวแล้วส่งอีเมลรัว)
- รวมแจ้งเตือนใหม่ทุกเรื่องในรอบเดียวเป็นอีเมลฉบับเดียว
- เรื่องที่ส่งไปแล้วเมื่อกลับมาปกติ → ส่ง "กลับมาปกติ" (ถ้าเปิด send_resolved) — เรื่องที่เจ้าหน้าที่กดรับทราบเองไม่ส่ง
- ส่งไม่สำเร็จ → พัก 10 นาทีแล้วลองใหม่ (ไม่ทำเครื่องหมายว่าส่งแล้ว)
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import local_utc_offset_hours
from core.mailer import BRAND, MailContent
from core.models import Alert, Camera, Setting, User, UserRole

ALERT_MAIL_KEY = "alert_mail"
KINDS = {
    "connection": "กล้องขาดการเชื่อมต่อ",
    "moved": "กล้องอาจถูกขยับ / เปลี่ยนมุม",
    "no_parking": "รถจอดในเขตห้ามจอด / จอดซ้อนคัน",
}
DEFAULTS = {
    "enabled": False,
    "kinds": {k: True for k in KINDS},
    "delay_min": 5,
    "send_resolved": True,
    "to_admins": True,
    "extra": [],
}
MAX_EXTRA = 20
RETRY_AFTER = timedelta(minutes=10)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
THAI_MONTHS = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]


def load_alert_mail(db: Session) -> dict:
    row = db.get(Setting, ALERT_MAIL_KEY)
    saved = row.value if row and isinstance(row.value, dict) else {}
    cfg = {**DEFAULTS, **{k: v for k, v in saved.items() if k in DEFAULTS}}
    cfg["kinds"] = {k: bool((saved.get("kinds") or {}).get(k, True)) for k in KINDS}
    try:
        cfg["delay_min"] = max(0, min(120, int(cfg["delay_min"])))
    except (TypeError, ValueError):
        cfg["delay_min"] = DEFAULTS["delay_min"]
    cfg["extra"] = [e for e in (cfg.get("extra") or []) if isinstance(e, str)][:MAX_EXTRA]
    return cfg


def parse_extra(text: str) -> list[str]:
    """อีเมลเพิ่มเติม คั่นด้วย , ; หรือขึ้นบรรทัดใหม่ — ValueError (ภาษาไทย) ถ้ารูปแบบผิด"""
    items = [x.strip() for x in re.split(r"[,;\s]+", text or "") if x.strip()]
    bad = [x for x in items if not EMAIL_RE.match(x)]
    if bad:
        raise ValueError(f"รูปแบบอีเมลไม่ถูกต้อง: {', '.join(bad[:3])}")
    unique = list(dict.fromkeys(i.lower() for i in items))
    if len(unique) > MAX_EXTRA:
        raise ValueError(f"ใส่อีเมลเพิ่มเติมได้ไม่เกิน {MAX_EXTRA} รายการ")
    return unique


def recipients(db: Session, cfg: dict) -> list[str]:
    emails: list[str] = []
    if cfg.get("to_admins"):
        emails += [
            e.strip().lower()
            for e in db.scalars(
                select(User.email).where(User.role == UserRole.ADMIN, User.is_active.is_(True), User.email.is_not(None))
            ).all()
            if e and EMAIL_RE.match(e.strip())
        ]
    emails += cfg.get("extra") or []
    return list(dict.fromkeys(emails))


def alert_kind(source: str) -> tuple[str | None, int | None]:
    parts = (source or "").split(":")
    if len(parts) == 3 and parts[0] == "camera" and parts[1].isdigit() and parts[2] in KINDS:
        return parts[2], int(parts[1])
    return None, None


def thai_time(utc: datetime | None) -> str:
    if utc is None:
        return "-"
    t = utc + timedelta(hours=local_utc_offset_hours())
    return f"{t.day:02d}/{t.month:02d}/{t.year + 543} {t.hour:02d}:{t.minute:02d} น."


def duration_text(start: datetime, end: datetime) -> str:
    mins = max(0, int((end - start).total_seconds() // 60))
    if mins < 60:
        return f"{mins} นาที"
    if mins < 1440:
        return f"{mins // 60} ชม. {mins % 60} นาที"
    return f"{mins // 1440} วัน {(mins % 1440) // 60} ชม."


def build_alert_email(new: list[dict], resolved: list[dict], link: str | None) -> MailContent:
    """อีเมลฉบับเดียวรวมเรื่องใหม่ + เรื่องที่กลับมาปกติ — item: {kind_label, message, started, ended?, duration?}"""
    if new and len(new) == 1 and not resolved:
        subject = f"⚠️ {new[0]['kind_label']} - {BRAND}"
    elif new:
        subject = f"⚠️ แจ้งเตือนใหม่ {len(new)} เรื่อง" + (f" · กลับมาปกติ {len(resolved)} เรื่อง" if resolved else "") + f" - {BRAND}"
    elif len(resolved) == 1:
        subject = f"✅ กลับมาปกติ: {resolved[0]['kind_label']} - {BRAND}"
    else:
        subject = f"✅ กลับมาปกติ {len(resolved)} เรื่อง - {BRAND}"

    lines: list[str] = []
    parts: list[str] = ['<div style="font-family:Tahoma,sans-serif;font-size:14px;color:#1e2532;padding:8px;">']
    if new:
        lines.append("แจ้งเตือนใหม่")
        parts.append('<h3 style="margin:0 0 8px;color:#b45309;">⚠️ แจ้งเตือนใหม่</h3>')
        for i, item in enumerate(new, 1):
            lines.append(f"{i}. {item['kind_label']}: {item['message']} (เริ่ม {item['started']})")
            parts.append(
                '<div style="border-left:4px solid #f59e0b;background:#fff7e6;padding:8px 12px;margin:0 0 8px;border-radius:6px;">'
                f"<b>{html.escape(item['kind_label'])}</b><br>{html.escape(item['message'])}"
                f'<br><span style="color:#5b6476;font-size:12px;">เริ่ม {html.escape(item["started"])}</span></div>'
            )
    if resolved:
        lines.append("")
        lines.append("กลับมาปกติแล้ว")
        parts.append('<h3 style="margin:12px 0 8px;color:#15803d;">✅ กลับมาปกติแล้ว</h3>')
        for i, item in enumerate(resolved, 1):
            lines.append(f"{i}. {item['kind_label']}: {item['message']} (ปกติเมื่อ {item['ended']} · นาน {item['duration']})")
            parts.append(
                '<div style="border-left:4px solid #22c55e;background:#ecfdf3;padding:8px 12px;margin:0 0 8px;border-radius:6px;">'
                f"<b>{html.escape(item['kind_label'])}</b><br>{html.escape(item['message'])}"
                f'<br><span style="color:#5b6476;font-size:12px;">ปกติเมื่อ {html.escape(item["ended"])} · นาน {html.escape(item["duration"])}</span></div>'
            )
    if link:
        lines += ["", f"ดูรายละเอียด: {link}"]
        parts.append(f'<p style="margin:12px 0;"><a href="{html.escape(link)}" style="background:#2f6bec;color:#fff;padding:8px 14px;border-radius:8px;text-decoration:none;">ดูหน้าการแจ้งเตือน</a></p>')
    lines += ["", f"อีเมลอัตโนมัติจาก {BRAND} · ปิด/เปลี่ยนผู้รับได้ที่ ตั้งค่าระบบ → อีเมลและลิงก์คำเชิญ"]
    parts.append(f'<p style="color:#8a93a3;font-size:12px;">อีเมลอัตโนมัติจาก {BRAND} · ปิด/เปลี่ยนผู้รับได้ที่ ตั้งค่าระบบ → อีเมลและลิงก์คำเชิญ</p></div>')
    return MailContent(subject=subject, text="\n".join(lines), html="".join(parts))


def _item(alert: Alert, cameras: dict[int, str], now: datetime, resolved: bool) -> dict:
    kind, _camera_id = alert_kind(alert.source)
    item = {"kind_label": KINDS.get(kind, "ระบบแจ้งเตือน"), "message": alert.message, "started": thai_time(alert.created_at)}
    if resolved:
        end = alert.resolved_at or now
        item.update(ended=thai_time(end), duration=duration_text(alert.created_at, end))
    return item


_retry_after: datetime | None = None


def process_alert_mail(db: Session, now: datetime, send, link: str | None) -> dict:
    """หาเรื่องที่ต้องส่ง แล้วส่ง (send(to, content) โยน Exception ถ้าไม่สำเร็จ) — คืนสรุปผลไว้ทดสอบ/บันทึก log"""
    global _retry_after
    cfg = load_alert_mail(db)
    if not cfg["enabled"]:
        return {"sent": 0, "reason": "disabled"}
    if _retry_after is not None and now < _retry_after:
        return {"sent": 0, "reason": "retry_wait"}

    delay = timedelta(minutes=cfg["delay_min"])
    new_alerts = [
        a for a in db.scalars(select(Alert).where(Alert.resolved_at.is_(None), Alert.emailed_at.is_(None))).all()
        if cfg["kinds"].get(alert_kind(a.source)[0] or "", False) and a.created_at <= now - delay
    ]
    resolved_alerts = db.scalars(
        select(Alert).where(Alert.resolved_at.is_not(None), Alert.emailed_at.is_not(None), Alert.resolved_emailed_at.is_(None))
    ).all()
    # เจ้าหน้าที่กดรับทราบเอง / ปิดการส่ง "กลับมาปกติ" → ไม่ต้องส่ง แค่ทำเครื่องหมาย
    to_resolve = [a for a in resolved_alerts if cfg["send_resolved"] and a.resolved_by is None]
    for a in resolved_alerts:
        if a not in to_resolve:
            a.resolved_emailed_at = now
    if not new_alerts and not to_resolve:
        return {"sent": 0, "reason": "nothing"}

    to = recipients(db, cfg)
    if not to:
        return {"sent": 0, "reason": "no_recipients"}

    cameras = dict(db.execute(select(Camera.id, Camera.name)).all())
    content = build_alert_email(
        [_item(a, cameras, now, False) for a in new_alerts],
        [_item(a, cameras, now, True) for a in to_resolve],
        link,
    )
    try:
        for address in to:
            send(address, content)
    except Exception as exc:  # noqa: BLE001 — ส่งไม่ได้ ไม่ให้ worker ล่ม รอรอบหน้า
        _retry_after = now + RETRY_AFTER
        return {"sent": 0, "reason": "error", "error": str(exc)}
    _retry_after = None
    for a in new_alerts:
        a.emailed_at = now
    for a in to_resolve:
        a.resolved_emailed_at = now
    return {"sent": len(to), "new": len(new_alerts), "resolved": len(to_resolve), "subject": content.subject}


def reset_retry() -> None:
    global _retry_after
    _retry_after = None
