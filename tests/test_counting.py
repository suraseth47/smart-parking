from core.counting import (
    SlotInfo,
    ZoneInfo,
    build_public_summary,
    build_slot_maps,
    build_zone_slot_map,
    filter_countable_slots,
    summarize_total,
    summarize_zone,
)


def slot(zone_id=1, type="normal", state="free", is_active=True, layout_status="published", code=""):
    return SlotInfo(
        zone_id=zone_id, type=type, state=state, is_active=is_active, layout_status=layout_status, code=code
    )


def zone(id=1, code="A", is_public=True, is_closed=False):
    return ZoneInfo(id=id, code=code, name_th=f"โซน {code}", name_en=f"Zone {code}", is_public=is_public, is_closed=is_closed)


# ---------- filter_countable_slots (FR-12) ----------

def test_filter_excludes_draft_slots():
    slots = [slot(layout_status="draft"), slot(layout_status="published")]
    assert len(filter_countable_slots(slots)) == 1


def test_filter_excludes_inactive_slots():
    slots = [slot(is_active=False), slot(is_active=True)]
    assert len(filter_countable_slots(slots)) == 1


def test_filter_excludes_reserved_type():
    slots = [slot(type="reserved"), slot(type="normal"), slot(type="disabled"), slot(type="ev")]
    assert len(filter_countable_slots(slots)) == 3


# ---------- summarize_zone (FR-13, FR-14) ----------

def test_zone_with_no_slots_is_no_data():
    result = summarize_zone(zone(), [])
    assert result.status == "no_data"
    assert result.free is None


def test_zone_closed_overrides_everything():
    slots = [slot(state="free")] * 10
    result = summarize_zone(zone(is_closed=True), slots)
    assert result.status == "closed"
    assert result.free is None


def test_zone_unknown_ratio_exactly_50_percent_is_no_data():
    slots = [slot(state="unknown"), slot(state="free")]  # 1/2 = 50%
    result = summarize_zone(zone(), slots)
    assert result.status == "no_data"


def test_zone_unknown_ratio_below_50_percent_is_partial():
    slots = [slot(state="unknown"), slot(state="free"), slot(state="free")]  # 1/3 = 33%
    result = summarize_zone(zone(), slots)
    assert result.status == "partial"
    assert result.free == 2
    assert result.capacity == 3


def test_zone_with_zero_unknown_is_ok():
    slots = [slot(state="free"), slot(state="occupied")]
    result = summarize_zone(zone(), slots)
    assert result.status == "ok"
    assert result.free == 1
    assert result.capacity == 2


def test_zone_counts_free_disabled_and_ev_separately():
    slots = [
        slot(type="normal", state="free"),
        slot(type="disabled", state="free"),
        slot(type="ev", state="free"),
        slot(type="disabled", state="occupied"),  # ไม่ว่าง ไม่นับ
    ]
    result = summarize_zone(zone(), slots)
    assert result.free == 3
    assert result.free_disabled == 1
    assert result.free_ev == 1


def test_zone_ignores_reserved_and_draft_and_inactive_slots_in_capacity():
    slots = [
        slot(type="reserved", state="free"),
        slot(layout_status="draft", state="free"),
        slot(is_active=False, state="free"),
        slot(type="normal", state="free"),
    ]
    result = summarize_zone(zone(), slots)
    assert result.capacity == 1
    assert result.free == 1


# ---------- summarize_total (FR-14, FR-15) ----------

def test_total_excludes_no_data_and_closed_zones():
    summaries = [
        summarize_zone(zone(code="A"), [slot(state="free"), slot(state="free")]),
        summarize_zone(zone(code="B", is_closed=True), [slot(state="free")]),
        summarize_zone(zone(code="C"), []),  # no_data
    ]
    total = summarize_total(summaries)
    assert total.free == 2
    assert total.capacity == 2
    assert sorted(total.excluded_zones) == ["B", "C"]


def test_total_sums_across_ok_and_partial_zones():
    zone_a = summarize_zone(zone(code="A"), [slot(state="free"), slot(state="occupied")])
    zone_b_slots = [slot(state="free"), slot(state="free"), slot(state="unknown")]  # 1/3 unknown = partial
    zone_b = summarize_zone(zone(code="B"), zone_b_slots)
    total = summarize_total([zone_a, zone_b])
    assert total.free == 1 + 2
    assert total.capacity == 2 + 3
    assert total.excluded_zones == []


# ---------- build_public_summary ----------

def test_build_public_summary_excludes_non_public_zones_entirely():
    zones = [zone(id=1, code="A", is_public=True), zone(id=2, code="STAFF", is_public=False)]
    slots = [slot(zone_id=1, state="free"), slot(zone_id=2, state="free")]
    summaries, total = build_public_summary(zones, slots)
    assert [z.code for z in summaries] == ["A"]
    assert total.capacity == 1


def test_build_public_summary_end_to_end():
    zones = [zone(id=1, code="A"), zone(id=2, code="B", is_closed=True)]
    slots = [
        slot(zone_id=1, type="normal", state="free"),
        slot(zone_id=1, type="disabled", state="occupied"),
        slot(zone_id=2, type="normal", state="free"),
    ]
    summaries, total = build_public_summary(zones, slots)
    by_code = {z.code: z for z in summaries}
    assert by_code["A"].status == "ok"
    assert by_code["A"].free == 1
    assert by_code["B"].status == "closed"
    assert total.free == 1
    assert total.excluded_zones == ["B"]


# ---------- build_zone_slot_map / build_slot_maps (แผนผังช่องจอดหน้าสาธารณะ) ----------

def test_zone_slot_map_none_for_closed_zone():
    assert build_zone_slot_map(zone(is_closed=True), [slot(code="A-01")]) is None


def test_zone_slot_map_excludes_reserved_and_draft_and_inactive():
    slots = [
        slot(code="A-01", type="reserved"),
        slot(code="A-02", type="normal", layout_status="draft"),
        slot(code="A-03", type="normal", is_active=False),
        slot(code="A-04", type="normal"),
    ]
    result = build_zone_slot_map(zone(), slots)
    assert [s["code"] for s in result] == ["A-04"]


def test_zone_slot_map_sorted_by_code():
    slots = [slot(code="A-03"), slot(code="A-01"), slot(code="A-02")]
    result = build_zone_slot_map(zone(), slots)
    assert [s["code"] for s in result] == ["A-01", "A-02", "A-03"]


def test_zone_slot_map_includes_state():
    slots = [slot(code="A-01", state="occupied"), slot(code="A-02", state="unknown")]
    result = build_zone_slot_map(zone(), slots)
    assert {s["code"]: s["state"] for s in result} == {"A-01": "occupied", "A-02": "unknown"}


def test_build_slot_maps_skips_non_public_zones():
    zones = [zone(id=1, code="A", is_public=True), zone(id=2, code="B", is_public=False)]
    slots = [slot(zone_id=1, code="A-01"), slot(zone_id=2, code="B-01")]
    result = build_slot_maps(zones, slots)
    assert list(result.keys()) == ["A"]


def test_build_slot_maps_per_zone():
    zones = [zone(id=1, code="A"), zone(id=2, code="B", is_closed=True)]
    slots = [slot(zone_id=1, code="A-01"), slot(zone_id=2, code="B-01")]
    result = build_slot_maps(zones, slots)
    assert [s["code"] for s in result["A"]] == ["A-01"]
    assert result["B"] is None
