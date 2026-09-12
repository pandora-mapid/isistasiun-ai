"""T3 — grounding fetchers + fixtures.

Fetches analytics JSON from the Go backend (read-only — "AI memanggil endpoint
ini sendiri, tidak ada perubahan kode Go yang dibutuhkan",
isi-stasiun-ai-integration.md §3.1) and falls back to fixtures/ when the
backend is unreachable, so the service runs standalone.

build_context() reshapes whatever came back into the nested structure T1's
`field_ref` paths walk (e.g. "spending_gap.evening.gap.p10") — see the module
docstring in verifier.py for why that shape was chosen.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from app.config import PURCHASE_CONVERSION, V_DEFAULTS, settings

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def _load_fixture(name: str) -> list[dict[str, Any]]:
    path = FIXTURES_DIR / name
    with path.open(encoding="utf-8") as f:
        return json.load(f)["data"]


def _fetch(path: str, params: dict[str, str] | None = None) -> list[dict[str, Any]] | None:
    """GETs `{GO_API_BASE_URL}{path}`. Returns None (not raise) on any failure
    so callers can fall back to fixtures — grounding must never crash the
    request just because the backend happens to be down (§3.6 in the BE
    CLAUDE.md: the map/AI answer must degrade, not break)."""
    if not settings.go_api_base_url:
        return None
    url = settings.go_api_base_url.rstrip("/") + path
    try:
        resp = httpx.get(url, params=params, timeout=settings.go_api_timeout_seconds)
        resp.raise_for_status()
        return resp.json()["data"]
    except (httpx.HTTPError, KeyError, ValueError):
        return None


def fetch_stations() -> list[dict[str, Any]]:
    return _fetch("/stations") or _load_fixture("stations.json")


def fetch_spending_gap(station_id: str | None = None) -> list[dict[str, Any]]:
    if station_id:
        rows = _fetch(f"/analytics/spending-gap/{station_id}")
    else:
        rows = _fetch("/analytics/spending-gap")
    if rows is None:
        rows = _load_fixture("spending_gap.json")
        if station_id:
            rows = [r for r in rows if r["station_id"] == station_id]
    return rows


def fetch_category_gap(station_id: str | None = None) -> list[dict[str, Any]]:
    rows = _fetch("/analytics/category-gap", params={"station_id": station_id} if station_id else None)
    if rows is None:
        rows = _load_fixture("category_gap.json")
        if station_id:
            rows = [r for r in rows if r["station_id"] == station_id]
    return rows


def fetch_confidence(station_id: str | None = None) -> list[dict[str, Any]]:
    rows = _fetch("/confidence-layer", params={"station_id": station_id} if station_id else None)
    if rows is None:
        rows = _load_fixture("confidence_layer.json")
        if station_id:
            rows = [r for r in rows if r["station_id"] == station_id]
    return rows


def fetch_rent_flow_index(station_id: str | None = None) -> list[dict[str, Any]]:
    rows = _fetch("/analytics/rent-flow-index", params={"station_id": station_id} if station_id else None)
    if rows is None:
        rows = _load_fixture("rent_flow_index.json")
        if station_id:
            rows = [r for r in rows if r["station_id"] == station_id]
    return rows


def _spending_gap_by_slot(station_id: str | None) -> dict[str, dict[str, dict[str, float]]]:
    out: dict[str, dict[str, dict[str, float]]] = {}
    for row in fetch_spending_gap(station_id):
        out[row["time_slot"]] = {
            "potential": {"p10": row["potential_low_p10"], "p90": row["potential_high_p90"]},
            "captured": {"p10": row["captured_low_p10"], "p90": row["captured_high_p90"]},
            "gap": {"p10": row["gap_low_p10"], "p90": row["gap_high_p90"]},
        }
    return out


def _category_gap_summary(station_id: str | None) -> dict[str, Any]:
    rows = fetch_category_gap(station_id)
    missing = [r["category"] for r in rows if r["demand_in_area"] and not r["available_in_station"]]
    available = [r["category"] for r in rows if r["available_in_station"]]
    return {"missing": missing, "available": available, "by_category": {r["category"]: r for r in rows}}


def _confidence_summary(station_id: str | None) -> dict[str, Any]:
    rows = fetch_confidence(station_id)
    return {"zones": rows, "any_thin_sample": any(r["is_thin_sample"] for r in rows)}


def build_context(analysis: "Analysis") -> dict[str, Any]:  # noqa: F821 - app.classify.Analysis, avoids import cycle
    """Minimal JSON slice for the prompt + the source-of-truth `field_ref`
    targets the verifier checks claims against. Only fetches what the
    classified intent needs, not the whole backend, per T3's brief."""
    station_id = analysis.station_id or None

    context: dict[str, Any] = {
        "station_id": station_id,
        "assumptions": {
            "C": PURCHASE_CONVERSION,
            "V": V_DEFAULTS,
        },
    }

    # "unknown" is deliberately excluded: classify() only leaves intent as
    # unknown when it found *no* signal at all (category, slot, or intent
    # phrase) — a bare category/slot mention is already promoted to
    # spending_gap there. So a genuinely unknown query (e.g. "halo, apa
    # kabar?") has nothing to ground and should get the generic 6-topics
    # fallback in app/answer.py, not a spending_gap answer for whichever
    # station happened to be in context.
    if analysis.intent in ("spending_gap", "flow"):
        context["spending_gap"] = _spending_gap_by_slot(station_id)
    if analysis.intent == "category_gap":
        context["category_gap"] = _category_gap_summary(station_id)
    if analysis.intent == "confidence":
        context["confidence"] = _confidence_summary(station_id)
    if analysis.intent == "rent_flow_index":
        context["rent_flow"] = {r["plot_id"]: r for r in fetch_rent_flow_index(station_id)}

    # Confidence is cheap and cross-cuts every intent (thin-sample hedging
    # applies regardless of what was asked), so always include it.
    context.setdefault("confidence", _confidence_summary(station_id))

    return context


def get_field(context: dict[str, Any], field_ref: str) -> Any:
    """Walks a dotted field_ref ("spending_gap.evening.gap.p10", or
    "confidence.zones.0.confidence_score" for a list segment) into context.
    Returns None if any segment is missing — used by the verifier to tell
    "not grounded" from "grounded but None"."""
    node: Any = context
    for part in field_ref.split("."):
        if isinstance(node, dict):
            if part not in node:
                return None
            node = node[part]
        elif isinstance(node, list):
            if not part.isdigit() or int(part) >= len(node):
                return None
            node = node[int(part)]
        else:
            return None
    return node
