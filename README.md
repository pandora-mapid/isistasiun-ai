# isistasiun-ai

FastAPI service for the AI subsystem's T1–T4 modules (see
[`../AI/ai-onboarding-teman.md`](../AI/ai-onboarding-teman.md) for the task brief and
[`../AI/isi-stasiun-ai-integration.md`](../AI/isi-stasiun-ai-integration.md) for the
BE/FE-facing contract). It is the `AI_SERVICE_URL` target
`isistasiun-be/backend/internal/copilot/client.go` calls.

## What's here

| Module | File | Task |
|---|---|---|
| T1 — zero-hallucination verifier | [`app/verifier.py`](app/verifier.py) | Checks every number the model claims against the source JSON; flags unreferenced numbers, mismatches, thin-sample violations, wrong assumption mentions. |
| T2 — eval harness | [`eval/`](eval/) | Runs `eval/dataset.jsonl` through the real pipeline, reports intent/filter accuracy, hallucination-rate, hedge compliance, out-of-scope handling. |
| T3 — grounding fetchers + fixtures | [`app/grounding.py`](app/grounding.py), [`fixtures/`](fixtures/) | Reads Go's analytics endpoints (falls back to fixtures if the backend is down) and reshapes them into the nested structure T1's `field_ref` paths walk. |
| T4 — category vocab | [`app/vocab.py`](app/vocab.py), [`data/vocab_lookup.json`](data/vocab_lookup.json) | Maps a gerai/POI name to one of the 5 canonical categories. |

`app/main.py`, `app/pipeline.py`, `app/seam.py`, `app/classify.py`, `app/answer.py`,
`app/brief.py`, `app/explain.py` are the plumbing that wires T1–T4 into a running
service (the onboarding doc calls this "integrasi akhir" and explicitly parks it as
someone else's job — it's included here anyway so the modules are demonstrably
pluggable end to end, kept as thin as possible: no persona/prompt design beyond a
single grounded-JSON-in, structured-JSON-out template).

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux
pip install -r requirements.txt
cp .env.example .env            # then set GEMINI_API_KEY and AI_BACKEND=gemini
uvicorn app.main:app --reload
```

Or via the isistasiun-be Docker Compose stack (adds an `ai` service — see the
root `CLAUDE.md`/`docker-compose.yml` there):

```bash
cd ../isistasiun-be && docker compose up -d ai
```

`AI_BACKEND=stub` (the `.env.example` default) needs no key at all — verifier and
eval logic are pure Python and fully testable offline, per the onboarding doc.

## Backends (the seam — `app/seam.py`)

`AI_BACKEND` swaps the generation seam. Every backend degrades to the
deterministic, grounded fallback on any failure (missing key, network error, bad
response), so the map is never blocked on the model.

| `AI_BACKEND` | Uses | Needs | When |
|---|---|---|---|
| `stub` | canned output | nothing | tests/eval offline (default) |
| `gemini` | Gemini API | `GEMINI_API_KEY` | if you already run Gemini elsewhere |
| `groq` | Groq API (OpenAI-compatible) | `GROQ_API_KEY` | **plain VPS deploy, no GPU** |
| `local` | Ollama/vLLM (OpenAI-compatible) | `LOCAL_BASE_URL`, `LOCAL_MODEL` | run an open model on the **workstation GPU** |

`groq` and `local` share one OpenAI-compatible `/chat/completions` client over
`httpx` (no extra dependency). For `local` with Ollama:
`ollama serve` then `ollama pull qwen2.5:14b-instruct`; for vLLM set
`LOCAL_BASE_URL=http://localhost:8000/v1`. Temperature is pinned to 0 on every
backend for reproducibility.

## Test

```bash
pytest
```

## Eval

```bash
python -m eval.build_dataset   # regenerate eval/dataset.jsonl after changing classify.py
python -m eval.runner          # writes eval/report.json + eval/report.md
```

The dataset has 23 rows (spec asks for "~50" — this is a starter set; extend
`eval/build_dataset.py`'s `ROWS` and re-run). `expected_intent`/`expected_filter` are
computed by calling `app.classify.classify()` itself rather than hand-typed, so they
can't drift from the classifier — which also means intent/filter accuracy here is a
regression check on `classify.py`, not an independent measurement of it. The metric
that matters most, hallucination-rate, is independent: it comes from `app.verifier`
grading whatever the model (or the deterministic fallback) actually said.

## Endpoints

- `POST /copilot/query` — **real**, matches `isistasiun-be/backend/internal/copilot/dto.go`
  exactly. Classifies the query the same way Go's `intent.go` does (an independent
  Python mirror — the wire contract is intentionally staying `{query, station_id}`,
  see `isi-stasiun-ai-integration.md` §5, so nothing is sent over the wire to avoid
  re-deriving), grounds via T3, asks the model for structured JSON
  (`{answer_text, claims[]}`), verifies via T1, and falls back to a
  guaranteed-grounded deterministic template if the model is unavailable or fails
  verification twice.
- `POST /brief`, `POST /explain` — match the JSON shapes in
  `isi-stasiun-ai-integration.md` §2.2/§2.3, but **nothing in Go or the frontend
  calls them yet**. Built deterministically from grounded context, no LLM/persona
  work (that's explicitly out of this task's scope).

## Known gaps (surfacing rather than guessing further)

- **`/explain`** has no real backing model anywhere in the codebase (no Go endpoint,
  no pipeline output for entity scores/factor weights). It only answers for entities
  in `fixtures/rent_flow_index.json` (real Lampiran D rent-vs-flow data), computes
  `score` via one documented formula (min-max normalized rent-flow index — see the
  module docstring), and leaves `confidence` as `null` with a note rather than
  inventing a number. Whoever owns the actual explain-score model should replace
  this.
- **`PURCHASE_CONVERSION = 0.95`** is defined in `app/config.py` (AI's read-only
  copy per §1/§3 of the integration doc) but the pipeline
  (`isistasiun-be/pipeline/analysis/monte_carlo.py`) does not yet apply it as a
  named constant — that's the pipeline owner's change, not made here.
- **Eval dataset is 24 rows**, not ~50 (see above).
