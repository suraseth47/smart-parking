"""ผังช่องจอดหน้าสาธารณะแบบกำหนดเอง ให้ตรงกับการจัดวางจริงของลานจอด (ตั้งที่ โซนและการปิดโซน → ผังหน้าบ้าน)

เขียนเป็นข้อความ 1 บรรทัด = 1 คอลัมน์ เรียงจากซ้ายไปขวา (มองจากฝั่งทางเข้า / ฝั่งกล้อง อยู่ล่างจอ)
ในแต่ละบรรทัด รหัสช่องเรียงจาก "ด้านในสุด (บนจอ)" ลงมา "ฝั่งทางเข้า (ล่างจอ)"

    A-07..A-01 เริ่ม 3          ← ช่วงรหัส + เริ่มที่แถว 3 (เว้นด้านบน 2 แถว)
    | ทางวิ่งรถ (ห้ามจอด)        ← ขึ้นต้นด้วย | = ทางวิ่ง (ข้อความหลัง | เป็นป้าย ไม่ใส่ก็ได้)
    A-16..A-08
    . . A-21 A-20 A-19 A-18 A-17 ← จุด . = ช่องว่างบนผัง (ใช้แทน "เริ่ม" ได้)

    ซ้าย: รั้ว · ถนน              ← ป้ายสิ่งที่อยู่รอบลาน 4 ด้าน (บน / ล่าง / ซ้าย / ขวา) ใส่หรือไม่ใส่ก็ได้
    ขวา: 🏢 อาคารสำนักงาน

ช่องที่ไม่ได้เขียนในผัง จะต่อท้ายเป็นคอลัมน์สุดท้ายให้เอง (ไม่มีช่องหายจากหน้าสาธารณะ)
บรรทัดที่ขึ้นต้นด้วย # = หมายเหตุ
"""
from __future__ import annotations

import re

MAX_COLUMNS = 8
MAX_ROWS = 80
RANGE_RE = re.compile(r"^(.*?)(\d+)\.\.(.*?)(\d+)$")
START_RE = re.compile(r"\s+(?:เริ่ม|start)\s*(\d+)\s*$", re.IGNORECASE)
SIDE_RE = re.compile(r"^(บน|ล่าง|ซ้าย|ขวา|top|bottom|left|right)\s*[:：]\s*(.*)$", re.IGNORECASE)
SIDE_KEYS = {"บน": "top", "ล่าง": "bottom", "ซ้าย": "left", "ขวา": "right"}
MAX_SIDE_LABEL = 40


def parse_sides(text: str | None) -> dict[str, str]:
    """ป้ายรอบลาน {"top"|"bottom"|"left"|"right": ข้อความ} จากบรรทัด "ซ้าย: ..." (ไม่มี = ไม่แสดง)"""
    sides: dict[str, str] = {}
    for raw in (text or "").splitlines():
        m = SIDE_RE.match(raw.strip())
        if m and m.group(2).strip():
            key = SIDE_KEYS.get(m.group(1), m.group(1).lower())
            sides[key] = m.group(2).strip()[:MAX_SIDE_LABEL]
    return sides


def _expand(token: str) -> list[str]:
    """A-07..A-01 → [A-07, A-06, ..., A-01] (คงจำนวนหลักตามต้นแบบ)"""
    m = RANGE_RE.match(token)
    if not m:
        return [token]
    p1, n1, p2, n2 = m.groups()
    if p2 and p2 != p1:
        raise ValueError(f"ช่วงรหัส {token} ต้องขึ้นต้นเหมือนกันทั้ง 2 ฝั่ง")
    a, b = int(n1), int(n2)
    if abs(a - b) > MAX_ROWS:
        raise ValueError(f"ช่วงรหัส {token} ยาวเกินไป")
    width = len(n1)
    step = 1 if b >= a else -1
    return [f"{p1}{str(i).zfill(width)}" for i in range(a, b + step, step)]


def parse_layout(text: str, slot_codes: list[str] | None = None) -> list[dict]:
    """ข้อความ → [{"type": "slots", "cells": [code|None]}, {"type": "aisle", "label": str}]

    slot_codes = รหัสช่องจริงของโซน (ตรวจรหัสที่ไม่มี/ซ้ำ) — ValueError (ภาษาไทย) ถ้าผิด
    """
    known = set(slot_codes) if slot_codes is not None else None
    columns: list[dict] = []
    seen: set[str] = set()
    for n, raw in enumerate((text or "").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if SIDE_RE.match(line):
            continue  # ป้ายรอบลาน อ่านแยกด้วย parse_sides
        if line.startswith("|"):
            columns.append({"type": "aisle", "label": line[1:].strip()[:40]})
            continue
        cells: list[str | None] = []
        m = START_RE.search(line)
        if m:
            start = int(m.group(1))
            if not 1 <= start <= MAX_ROWS:
                raise ValueError(f"บรรทัด {n}: แถวเริ่มต้องอยู่ระหว่าง 1–{MAX_ROWS}")
            cells += [None] * (start - 1)
            line = line[: m.start()]
        for token in re.split(r"[\s,]+", line):
            if not token:
                continue
            if token == ".":
                cells.append(None)
                continue
            for code in _expand(token):
                if known is not None and code not in known:
                    raise ValueError(f"บรรทัด {n}: ไม่มีช่องรหัส {code} ในโซนนี้")
                if code in seen:
                    raise ValueError(f"บรรทัด {n}: ช่อง {code} ใส่ซ้ำ")
                seen.add(code)
                cells.append(code)
        if not any(cells):
            raise ValueError(f"บรรทัด {n}: ไม่มีรหัสช่องจอด")
        if len(cells) > MAX_ROWS:
            raise ValueError(f"บรรทัด {n}: ยาวเกิน {MAX_ROWS} แถว")
        columns.append({"type": "slots", "cells": cells})
    if sum(c["type"] == "slots" for c in columns) > MAX_COLUMNS:
        raise ValueError(f"ใส่คอลัมน์ช่องจอดได้ไม่เกิน {MAX_COLUMNS} คอลัมน์")
    return columns


def resolve_layout(text: str | None, slot_codes: list[str]) -> list[dict] | None:
    """ผังที่ใช้แสดงจริง: ตัดรหัสที่ไม่มีแล้วออก + ต่อช่องที่ไม่ได้อยู่ในผังเป็นคอลัมน์ท้าย — None = ใช้ผังอัตโนมัติ"""
    if not text or not text.strip():
        return None
    try:
        columns = parse_layout(text)
    except ValueError:
        return None
    present = set(slot_codes)
    used: set[str] = set()
    out: list[dict] = []
    for col in columns:
        if col["type"] == "aisle":
            out.append(col)
            continue
        cells = [c if c in present else None for c in col["cells"]]
        used.update(c for c in cells if c)
        if any(cells):
            out.append({"type": "slots", "cells": cells})
    rest = [c for c in slot_codes if c not in used]
    if rest:
        out.append({"type": "slots", "cells": rest})
    return out if any(c["type"] == "slots" for c in out) else None
