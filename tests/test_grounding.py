from app.classify import Analysis
from app.grounding import build_context, fetch_category_gap, fetch_spending_gap, get_field

MANGGARAI = "a10a6cf2-0001-4f2b-9c1a-000000000001"
SUDIRMAN = "a10a6cf2-0002-4f2b-9c1a-000000000002"


def test_fetch_spending_gap_falls_back_to_fixtures_without_live_backend():
    rows = fetch_spending_gap(MANGGARAI)
    assert rows
    assert all(r["station_id"] == MANGGARAI for r in rows)


def test_sudirman_morning_is_absent_no_denominator():
    """§1 of isi-stasiun-ai-integration.md: Sudirman pagi has no Lewat
    denominator, so it must not be estimated — the fixture should not
    invent a morning row for it."""
    rows = fetch_spending_gap(SUDIRMAN)
    slots = {r["time_slot"] for r in rows}
    assert "morning" not in slots
    assert "evening" in slots


def test_category_gap_missing_matches_documented_example():
    """isi-stasiun-ai-integration.md §2.1 worked example: Sudirman evening
    missing categories are apotek_kesehatan and jasa."""
    rows = fetch_category_gap(SUDIRMAN)
    missing = {r["category"] for r in rows if r["demand_in_area"] and not r["available_in_station"]}
    assert missing == {"apotek_kesehatan", "jasa"}


def test_build_context_spending_gap_field_refs_resolve():
    analysis = Analysis(intent="spending_gap", station_id=SUDIRMAN, time_slot="evening")
    context = build_context(analysis)
    assert get_field(context, "spending_gap.evening.gap.p10") == 900_000
    assert get_field(context, "spending_gap.evening.gap.p90") == 1_600_000
    assert get_field(context, "assumptions.C") == 0.95


def test_build_context_missing_field_ref_returns_none():
    analysis = Analysis(intent="spending_gap", station_id=SUDIRMAN)
    context = build_context(analysis)
    assert get_field(context, "spending_gap.evening.gap.nonexistent") is None
    assert get_field(context, "does.not.exist") is None
