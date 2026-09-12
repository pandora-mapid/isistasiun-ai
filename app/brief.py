"""POST /brief — §2.2 of isi-stasiun-ai-integration.md.

Built entirely from grounded context, no LLM call: persona/prose design for
brief generation is explicitly out of this task's scope
(ai-onboarding-teman.md §3), so this wires T3's grounding straight into the
documented JSON shape rather than attempting brief "writing".
"""

from __future__ import annotations

from app.answer import category_label, format_idr, format_idr_range
from app.config import PURCHASE_CONVERSION, V_DEFAULTS
from app.grounding import build_context
from app.classify import Analysis


def build_brief(station_id: str, time_slot: str | None = None) -> dict:
    analysis = Analysis(intent="spending_gap", station_id=station_id, time_slot=time_slot or "")
    context = build_context(analysis)

    slots = context.get("spending_gap", {})
    if time_slot:
        # A specific slot was asked for — if it's not in the data (e.g.
        # Sudirman pagi), say so; never silently substitute another slot.
        slot = time_slot if time_slot in slots else None
    else:
        slot = next(iter(slots), None)

    # Same rule as app/answer.py: a slot with no denominator is simply absent
    # from context (see app/grounding.py), not present-but-thin-flagged — the
    # doc's own §2.2 example states a concrete headline for Sudirman sore
    # despite the dataset being thin-sample overall.
    thin_zones = [z["zone_id"] for z in (context.get("confidence") or {}).get("zones", []) if z["is_thin_sample"]]

    if slot:
        gap = slots[slot]["gap"]
        c_pct = int(round(PURCHASE_CONVERSION * 100))
        headline = f"Slot {slot}: kesenjangan belanja {format_idr_range(gap['p10'], gap['p90'])} (estimasi, C={c_pct}%)."
        captured = slots[slot]["captured"]
        captured_range = format_idr_range(captured["p10"], captured["p90"])
    else:
        headline = "Belum ada data slot waktu untuk stasiun ini (tak berdenominator / tidak diestimasi)."
        captured_range = "tidak diestimasi"

    cat_context = build_context(Analysis(intent="category_gap", station_id=station_id))
    missing = cat_context.get("category_gap", {}).get("missing", [])

    v_note = ", ".join(f"{category_label(k)}={format_idr(v)}" for k, v in V_DEFAULTS.items())

    return {
        "station_id": station_id,
        "headline": headline,
        "captured_range": captured_range,
        "assumptions": [f"C = {int(round(PURCHASE_CONVERSION * 100))}% dari masuk", f"V = {v_note} (dapat disetel)"],
        "top_missing_categories": missing,
        "confidence_note": (
            f"Sampel tipis: {', '.join(thin_zones)}." if thin_zones else "Sampel cukup untuk seluruh zona."
        ),
    }
