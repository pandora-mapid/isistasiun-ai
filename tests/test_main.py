import pytest
from fastapi.testclient import TestClient

from app import seam
from app.main import app

SUDIRMAN = "a10a6cf2-0002-4f2b-9c1a-000000000002"
MANGGARAI = "a10a6cf2-0001-4f2b-9c1a-000000000001"

client = TestClient(app)


@pytest.fixture(autouse=True)
def force_deterministic_fallback(monkeypatch):
    """Every test here exercises the grounded/deterministic path, not a live
    Gemini call — network calls don't belong in unit tests. seam.generate is
    what pipeline.py calls, so patching it here covers every caller."""
    monkeypatch.setattr(seam, "generate", lambda *a, **k: None)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_copilot_query_rejects_empty_query():
    resp = client.post("/copilot/query", json={"query": "   "})
    assert resp.status_code == 400


def test_copilot_query_rejects_too_long_query():
    resp = client.post("/copilot/query", json={"query": "a" * 501})
    assert resp.status_code == 400


def test_copilot_query_unknown_intent_has_no_filter():
    resp = client.post("/copilot/query", json={"query": "halo, apa kabar?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["spatial_filter"] is None
    assert "kesenjangan belanja" in body["answer"] or "kategori usaha" in body["answer"]


def test_copilot_query_spending_gap_matches_dto_shape():
    resp = client.post(
        "/copilot/query",
        json={"query": "berapa kesenjangan belanja sore ini?", "station_id": SUDIRMAN},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"answer", "suggested_layers", "spatial_filter"}
    assert body["spatial_filter"] == {"station_id": SUDIRMAN, "time_slot": "evening"}
    assert "gap" in body["suggested_layers"]
    # Grounded straight from fixtures/spending_gap.json — must appear verbatim.
    assert "0,9" in body["answer"] and "1,6" in body["answer"]


def test_copilot_query_category_gap_matches_documented_example():
    resp = client.post(
        "/copilot/query",
        json={"query": "kategori apa yang belum ada di sudirman sore?", "station_id": SUDIRMAN},
    )
    assert resp.status_code == 200
    answer = resp.json()["answer"]
    assert "apotek" in answer.lower()
    assert "jasa" in answer.lower()


def test_copilot_query_event_potential_states_no_data_not_a_number():
    # Event has no real data source (event_potential_scores is unseeded, no
    # field survey, FE disables the layer). The AI must NOT state an activation
    # score — it must say there's no data. Guards against re-introducing an
    # invented event number.
    resp = client.post(
        "/copilot/query",
        json={"query": "kapan ramai untuk bazar / pop-up di stasiun ini?", "station_id": SUDIRMAN},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "event" in body["suggested_layers"]  # classification still works
    assert "belum punya sumber data" in body["answer"].lower()


def test_copilot_query_flow_names_busiest_gate():
    # "pintu mana paling ramai" must name the busiest gate, not fall back to a
    # spending-gap answer. Manggarai busiest = Pintu A (76).
    resp = client.post(
        "/copilot/query",
        json={"query": "pintu mana paling ramai di manggarai?", "station_id": MANGGARAI},
    )
    assert resp.status_code == 200
    answer = resp.json()["answer"].lower()
    assert "pintu a" in answer
    assert "76" in answer


def test_copilot_query_compare_grounds_both_stations():
    # "bandingkan Manggarai dengan Sudirman" is a featured suggested question in
    # the FE. It must NOT fall to the "belum jelas" unknown answer — it maps to
    # the compare intent and states a grounded gap per station (both share the
    # evening slot in fixtures: Manggarai 0,8-1,4 jt; Sudirman 0,9-1,6 jt).
    resp = client.post("/copilot/query", json={"query": "bandingkan Manggarai dengan Sudirman"})
    assert resp.status_code == 200
    body = resp.json()
    answer = body["answer"]
    assert "Perbandingan" in answer
    assert "Manggarai" in answer and "Sudirman" in answer
    assert "belum jelas" not in answer.lower()
    # grounded evening ranges appear verbatim
    assert "0,8" in answer and "1,4" in answer
    assert "0,9" in answer and "1,6" in answer
    assert "gap" in body["suggested_layers"]


def test_brief_endpoint_shape():
    resp = client.post("/brief", json={"station_id": SUDIRMAN, "time_slot": "evening"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["station_id"] == SUDIRMAN
    assert body["top_missing_categories"] == ["apotek_kesehatan", "jasa"]
    assert any("C = 95%" in a for a in body["assumptions"])


def test_explain_known_entity():
    resp = client.post("/explain", json={"entity_id": "manggarai-petak-05", "station_id": MANGGARAI})
    assert resp.status_code == 200
    body = resp.json()
    assert body["entity_id"] == "manggarai-petak-05"
    assert 0 <= body["score"] <= 1
    assert body["confidence"] is None


def test_explain_unknown_entity_returns_404():
    resp = client.post("/explain", json={"entity_id": "does-not-exist"})
    assert resp.status_code == 404
