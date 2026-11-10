"""ผังช่องจอดหน้าสาธารณะแบบกำหนดเอง (core/map_layout.py)"""
import pytest

from core.map_layout import parse_layout, resolve_layout

CODES = [f"A-{i:02d}" for i in range(1, 22)]
MUNICIPAL = "A-07..A-01 เริ่ม 3\n| ทางวิ่งรถ (ห้ามจอด)\nA-16..A-08\nA-21..A-17 เริ่ม 3\n"


def test_municipal_layout_matches_real_lot():
    cols = parse_layout(MUNICIPAL, CODES)
    assert [c["type"] for c in cols] == ["slots", "aisle", "slots", "slots"]
    assert cols[0]["cells"] == [None, None, "A-07", "A-06", "A-05", "A-04", "A-03", "A-02", "A-01"]
    assert cols[1]["label"] == "ทางวิ่งรถ (ห้ามจอด)"
    assert cols[2]["cells"][0] == "A-16" and cols[2]["cells"][-1] == "A-08"
    assert cols[3]["cells"] == [None, None, "A-21", "A-20", "A-19", "A-18", "A-17"]


def test_dots_comments_and_commas():
    cols = parse_layout("# หมายเหตุ\n. A-01, A-02\n|\n", ["A-01", "A-02"])
    assert cols == [{"type": "slots", "cells": [None, "A-01", "A-02"]}, {"type": "aisle", "label": ""}]


def test_unknown_and_duplicate_codes_are_rejected():
    with pytest.raises(ValueError, match="ไม่มีช่องรหัส A-99"):
        parse_layout("A-01 A-99", CODES)
    with pytest.raises(ValueError, match="ใส่ซ้ำ"):
        parse_layout("A-01 A-02\nA-02", CODES)


def test_resolve_appends_missing_slots_and_drops_removed():
    out = resolve_layout("A-01 A-02 A-50\n|", ["A-01", "A-02", "A-03"])
    assert out == [{"type": "slots", "cells": ["A-01", "A-02", None]}, {"type": "aisle", "label": ""},
                   {"type": "slots", "cells": ["A-03"]}]


def test_resolve_empty_or_broken_text_falls_back_to_auto():
    assert resolve_layout("", CODES) is None
    assert resolve_layout("A-01..B-05", CODES) is None


def test_side_labels_are_read_and_not_treated_as_columns():
    text = MUNICIPAL + "บน: ด้านในลาน\nล่าง: ทางเข้า\nซ้าย: รั้ว · ถนน\nขวา: 🏢 อาคารสำนักงานเทศบาล\nright:\n"
    from core.map_layout import parse_sides

    assert parse_sides(text) == {"top": "ด้านในลาน", "bottom": "ทางเข้า", "left": "รั้ว · ถนน", "right": "🏢 อาคารสำนักงานเทศบาล"}
    assert len(parse_layout(text, CODES)) == 4
