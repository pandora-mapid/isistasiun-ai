"""Deterministic answer/prompt building for /copilot/query.

`deterministic_answer` is the guaranteed-safe floor: it reads straight out of
`context` (built by app/grounding.py) and only ever states numbers that are
already there, so it is grounded by construction and needs no verifier pass.
It plays the same role here that Go's `Analysis.Answer()` plays in
intent.go/service.go — the reply used when the model is unavailable or fails
verification.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.classify import Analysis
from app.config import PURCHASE_CONVERSION

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"

_CATEGORY_LABELS = {
    "makanan_minuman": "makanan & minuman",
    "ritel_kemasan": "ritel kemasan",
    "apotek_kesehatan": "apotek & kesehatan",
    "jasa": "jasa",
    "lainnya": "lainnya",
}


def category_label(key: str) -> str:
    return _CATEGORY_LABELS.get(key, key)


def format_idr(value: float) -> str:
    """900000 -> "Rp0,9 jt" · 30000 -> "Rp30 rb". Round-trips through
    verifier.parse_id_number so prose the deterministic path writes is always
    self-consistent with the claims it emits."""
    if abs(value) >= 1_000_000:
        return f"Rp{value / 1_000_000:.1f} jt".replace(".", ",")
    if abs(value) >= 1_000:
        return f"Rp{value / 1_000:.0f} rb"
    return f"Rp{value:.0f}"


def format_idr_range(lo: float, hi: float) -> str:
    """(900000, 1600000) -> "Rp0,9 jt–Rp1,6 jt". Both sides share the unit the
    larger value would pick on its own (so a p10 under 1jt still reads as
    "0,9 jt" next to a p90 in jt, matching the worked example in
    isi-stasiun-ai-integration.md §2.1), and each side keeps its own suffix so
    the range still round-trips through parse_id_number number-by-number."""
    scale = max(abs(lo), abs(hi))
    if scale >= 1_000_000:
        return f"Rp{lo / 1_000_000:.1f} jt–Rp{hi / 1_000_000:.1f} jt".replace(".", ",")
    if scale >= 1_000:
        return f"Rp{lo / 1_000:.0f} rb–Rp{hi / 1_000:.0f} rb"
    return f"Rp{lo:.0f}–Rp{hi:.0f}"


def build_prompt(query: str, context: dict) -> str:
    template = (PROMPT_DIR / "copilot_query.md").read_text(encoding="utf-8")
    return template.format(query=query, context_json=json.dumps(context, ensure_ascii=False, indent=2))


def deterministic_answer(analysis: Analysis, context: dict) -> dict:
    parts: list[str] = []
    claims: list[dict] = []

    # Sudirman pagi has no Lewat denominator, so that slot is simply *absent*
    # from spending_gap context (app/grounding.py) rather than present-but-
    # flagged — "no such slot" already reads as "not estimated" below. The
    # confidence layer's is_thin_sample is a separate caveat surfaced only
    # for confidence-intent answers, not a blanket gate on every number (see
    # verifier._is_thin's docstring for why).
    if analysis.intent == "flow" and context.get("flow", {}).get("busiest"):
        b = context["flow"]["busiest"]
        # Gate counts are small integers the verifier's number sweep ignores by
        # design (not "figure-shaped"), so no claims are needed — the number is
        # read straight from grounded context (correct by construction).
        parts.append(
            f"Pintu paling ramai: {b['gate']} — {b['total']} orang "
            f"({b['masuk']} masuk, {b['keluar']} keluar) pada jendela survei."
        )

    elif analysis.intent in ("spending_gap", "flow") and context.get("spending_gap"):
        slots = context["spending_gap"]
        if analysis.time_slot:
            # A specific slot was asked for — if it's not in the data (e.g.
            # Sudirman pagi), say so; never silently substitute a different
            # slot's numbers for the one that was actually asked about.
            slot = analysis.time_slot if analysis.time_slot in slots else None
        else:
            slot = next(iter(slots), None)
        if slot is None:
            parts.append("Belum ada data kesenjangan belanja untuk slot yang ditanyakan (tak berdenominator / tidak diestimasi).")
        else:
            gap = slots[slot]["gap"]
            c_pct = int(round(PURCHASE_CONVERSION * 100))
            parts.append(
                f"Kesenjangan belanja pada slot {slot}: {format_idr_range(gap['p10'], gap['p90'])} "
                f"(estimasi, C={c_pct}%)."
            )
            claims.extend(
                [
                    {"value": gap["p10"], "unit": "IDR", "field_ref": f"spending_gap.{slot}.gap.p10"},
                    {"value": gap["p90"], "unit": "IDR", "field_ref": f"spending_gap.{slot}.gap.p90"},
                    {"value": PURCHASE_CONVERSION, "unit": "ratio", "field_ref": "assumptions.C"},
                ]
            )

    elif analysis.intent == "category_gap" and context.get("category_gap"):
        missing = context["category_gap"]["missing"]
        by_category = context["category_gap"].get("by_category", {})
        if missing:
            # Cite the real POI-in-catchment count (demand_count) when present,
            # emitting a grounded claim for it so the number is verifiable.
            segments: list[str] = []
            for c in missing:
                count = by_category.get(c, {}).get("demand_count")
                label = category_label(c)
                if count:
                    segments.append(f"{label} ({count} POI dalam 800 m)")
                    claims.append(
                        {"value": count, "unit": "count", "field_ref": f"category_gap.by_category.{c}.demand_count"}
                    )
                else:
                    segments.append(label)
            parts.append(
                "Kategori dengan permintaan terbaca di sekitar (POI dalam 800 m) tapi belum tersedia "
                "di dalam stasiun: " + " dan ".join(segments) + "."
            )
        else:
            parts.append("Tidak ada kategori yang teridentifikasi hilang untuk stasiun ini.")

    elif analysis.intent == "confidence" and context.get("confidence"):
        zones = context["confidence"]["zones"]
        thin_zones = [z["zone_id"] for z in zones if z["is_thin_sample"]]
        if thin_zones:
            parts.append(
                f"Zona bersampel tipis: {', '.join(thin_zones)} — tidak diestimasi, "
                "jangan dibaca sebagai aman maupun bermasalah."
            )
        else:
            parts.append("Semua zona pada stasiun ini memiliki sampel yang cukup untuk diestimasi.")

    elif analysis.intent == "compare" and context.get("compare", {}).get("stations"):
        # One grounded gap range per station, at the asked slot if the station
        # has it, else that station's biggest-gap slot. Each figure carries a
        # claim so the number-sweep verifies it; the "which is larger" reading
        # is left to the prose (no invented number).
        stations = context["compare"]["stations"]
        lines: list[str] = []
        for sid, sdata in stations.items():
            slots = sdata.get("slots", {})
            if not slots:
                continue
            slot = (
                analysis.time_slot
                if analysis.time_slot in slots
                else max(slots, key=lambda s: slots[s]["gap"]["p90"])
            )
            gap = slots[slot]["gap"]
            lines.append(
                f"{sdata['name']}: kesenjangan slot {slot} "
                f"{format_idr_range(gap['p10'], gap['p90'])}"
            )
            claims.extend(
                [
                    {"value": gap["p10"], "unit": "IDR", "field_ref": f"compare.stations.{sid}.slots.{slot}.gap.p10"},
                    {"value": gap["p90"], "unit": "IDR", "field_ref": f"compare.stations.{sid}.slots.{slot}.gap.p90"},
                ]
            )
        if lines:
            parts.append(
                "Perbandingan kesenjangan belanja — " + "; ".join(lines) + "."
            )
        else:
            parts.append(
                "Belum ada data kesenjangan untuk dibandingkan antar stasiun."
            )

    elif analysis.intent == "rent_flow_index" and context.get("rent_flow"):
        parts.append(
            "Indeks sewa per arus tersedia per petak — sebutkan nama petak/gerai spesifik untuk detail angkanya."
        )

    elif analysis.intent == "event_potential":
        # No REAL grounding source exists: the event_potential_scores table has
        # no seed, there's no field survey for event, and the FE disables the
        # Event layer as "belum ada data". So we do NOT state activation scores
        # (that would be inventing numbers — the one thing the verifier exists
        # to stop). Say so plainly instead of falling through to the generic
        # "unknown intent" message, which would misreport a successful
        # classification as a failed one. Wire real grounding here only once
        # event_potential_scores is actually populated.
        parts.append(
            "Potensi event & aktivasi belum punya sumber data di layanan ini; "
            "lihat layer event di peta untuk status terkini."
        )

    else:
        parts.append(
            "Belum jelas bagian mana yang ditanyakan. Coba sebut kesenjangan belanja, kategori usaha, "
            "indeks sewa, potensi event, arus pintu, atau kepercayaan data."
        )

    return {"answer_text": " ".join(parts), "claims": claims}
