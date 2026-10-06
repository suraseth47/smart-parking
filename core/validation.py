"""คำนวณ % ความแม่นยำของ Validation tool (NFR-4) — pure function ไม่ยุ่งกับ DB"""
from __future__ import annotations


def compute_accuracy(all_slot_results: list[list[dict]]) -> dict:
    """รวมผลจากทุกภาพใน job แล้วคำนวณ % ความแม่นยำ (NFR-4)

    all_slot_results: ผล slot_results ของแต่ละภาพ เช่น
        [[{"detected_state": "occupied", "confirmed_state": "occupied"}, ...], ...]

    นับเฉพาะรายการที่คนกดยืนยันแล้ว (confirmed_state ไม่ใช่ None) และระบบไม่ได้
    ตอบ "unknown" (ตรวจจับไม่ได้เลย ไม่ใช่กรณีวัดความแม่นยำ free/occupied ตาม A4)
    """
    total = 0
    correct = 0
    for slot_results in all_slot_results:
        for item in slot_results:
            if item.get("confirmed_state") is None:
                continue
            if item.get("detected_state") == "unknown":
                continue
            total += 1
            if item["detected_state"] == item["confirmed_state"]:
                correct += 1

    accuracy_pct = round(correct / total * 100, 1) if total > 0 else None
    return {"total_compared": total, "correct": correct, "accuracy_pct": accuracy_pct}
