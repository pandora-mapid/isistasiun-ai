"""FastAPI service — AI_SERVICE_URL target for isistasiun-be's copilot.Client
(internal/copilot/client.go). Endpoints and field names below are locked to
isi-stasiun-ai-integration.md §2 and must not be renamed without BE/FE
coordination (§5 there: "mengubah copilot/dto.go -> koordinasi dulu").
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.brief import build_brief
from app.explain import explain_entity
from app.pipeline import answer_query

app = FastAPI(title="isistasiun-ai", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# POST /copilot/query — §2.1. Request/response shape mirrors
# isistasiun-be/backend/internal/copilot/dto.go exactly.
# ---------------------------------------------------------------------------


class QueryRequest(BaseModel):
    # No Pydantic max_length here on purpose: Go's contract returns 400 for
    # an over-long query (see intent.go's handler), and a Pydantic Field
    # constraint would 422 before the handler runs. The manual check below
    # keeps the same status code Go uses.
    query: str
    station_id: str | None = None


class QueryResponse(BaseModel):
    answer: str
    suggested_layers: list[str] | None = None
    spatial_filter: dict | None = None


@app.post("/copilot/query", response_model=QueryResponse)
def copilot_query(req: QueryRequest) -> QueryResponse:
    query = req.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query wajib diisi")
    if len(query) > 500:
        raise HTTPException(status_code=400, detail="query terlalu panjang (maksimal 500 karakter)")

    answer, layers, spatial_filter = answer_query(query, req.station_id or "")
    return QueryResponse(answer=answer, suggested_layers=layers or None, spatial_filter=spatial_filter)


# ---------------------------------------------------------------------------
# POST /brief — §2.2. Not called by Go/FE yet; deterministic, see app/brief.py.
# ---------------------------------------------------------------------------


class BriefRequest(BaseModel):
    station_id: str
    time_slot: str | None = None


class BriefResponse(BaseModel):
    station_id: str
    headline: str
    captured_range: str
    assumptions: list[str]
    top_missing_categories: list[str]
    confidence_note: str


@app.post("/brief", response_model=BriefResponse)
def brief(req: BriefRequest) -> BriefResponse:
    return BriefResponse(**build_brief(req.station_id, req.time_slot))


# ---------------------------------------------------------------------------
# POST /explain — §2.3. Not called by Go/FE yet; only answers for entities
# backed by real rent_flow_index data — see app/explain.py docstring.
# ---------------------------------------------------------------------------


class ExplainRequest(BaseModel):
    entity_id: str
    station_id: str | None = None


class ExplainFactor(BaseModel):
    factor: str
    value: float
    field_ref: str


class ExplainResponse(BaseModel):
    entity_id: str
    score: float
    label: str
    factors: list[ExplainFactor]
    confidence: float | None
    confidence_note: str


@app.post("/explain", response_model=ExplainResponse)
def explain(req: ExplainRequest) -> ExplainResponse:
    result = explain_entity(req.entity_id, req.station_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"tidak ada data rent-flow untuk entity_id={req.entity_id!r}",
        )
    return ExplainResponse(**result)
