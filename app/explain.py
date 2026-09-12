"""POST /explain — §2.3 of isi-stasiun-ai-integration.md.

No per-entity "explain score" model exists anywhere in the codebase yet (no
Go endpoint, no pipeline computation) — inventing factor weights to fill the
PRD's example shape would be exactly the kind of ungrounded number T1 exists
to catch. So this only answers for entities backed by real data we do have
(rent_flow_index, Lampiran D of isi-stasiun-ai-integration.md — real in-station
rent vs. measured flow for Manggarai), computes `score` via one transparent,
documented formula (min-max normalize the rent-flow index across known
plots), and reports the real fields behind it instead of fabricated weights.
`confidence` is left null rather than invented, with a note explaining why —
see README "Known gaps" for the follow-up this leaves for whoever owns
"integrasi akhir".
"""

from __future__ import annotations

from app.grounding import fetch_rent_flow_index


def explain_entity(entity_id: str, station_id: str | None = None) -> dict | None:
    rows = fetch_rent_flow_index(station_id)
    by_id = {r["plot_id"]: r for r in rows}
    row = by_id.get(entity_id)
    if row is None:
        return None

    indices = [r["index"] for r in rows]
    lo, hi = min(indices), max(indices)
    score = 0.5 if hi == lo else (row["index"] - lo) / (hi - lo)
    label = "tinggi" if score >= 0.66 else "sedang" if score >= 0.33 else "rendah"

    return {
        "entity_id": entity_id,
        "score": round(score, 2),
        "label": label,
        "factors": [
            {
                "factor": "rent_flow_index",
                "value": row["index"],
                "field_ref": f"rent_flow.{entity_id}.index",
            },
            {
                "factor": "offered_rent_idr_per_year",
                "value": row["offered_rent"],
                "field_ref": f"rent_flow.{entity_id}.offered_rent",
            },
            {
                "factor": "measured_flow",
                "value": row["measured_flow"],
                "field_ref": f"rent_flow.{entity_id}.measured_flow",
            },
        ],
        "confidence": None,
        "confidence_note": (
            "Skor dihitung dari rent-flow index terukur (min-max ternormalisasi antar petak); "
            "belum ada model confidence per-entity, jadi field ini sengaja tidak diisi angka karangan."
        ),
    }
