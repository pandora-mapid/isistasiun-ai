"""Environment-backed settings. Mirrors the pattern in
isistasiun-be/pipeline/shared/config.py (dataclass + os.getenv + load_dotenv)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    # AI_BACKENDS (plural, comma-separated) = an ordered fallback chain tried
    # left to right until one answers, e.g. "local,gemini,groq". If empty, the
    # single AI_BACKEND is used (backwards-compatible). Recommended prod value:
    # local first (free, no rate limit, private), then gemini (more forgiving
    # free tier for sporadic traffic when local is down), then groq (fastest
    # but tightest limit — last resort). All degrade to the deterministic,
    # grounded fallback if the whole chain fails; the map never blocks.
    ai_backends: str = os.getenv("AI_BACKENDS", "")
    ai_backend: str = os.getenv("AI_BACKEND", "stub")
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

    # Groq — OpenAI-compatible; lets the service run on a plain VPS with no GPU
    # (deploy decision: API-only path). base_url is the OpenAI-compat root; the
    # seam appends /chat/completions.
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    # Groq rotates its hosted model catalog often (old IDs get 404
    # "model_not_found"). Verify against GET {base}/v1/models for the account;
    # override GROQ_MODEL in .env when this default is retired.
    groq_model: str = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
    groq_base_url: str = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")

    # Local model (Ollama/vLLM), also OpenAI-compatible. Default points at
    # Ollama's OpenAI-compat endpoint; vLLM users override LOCAL_BASE_URL.
    # api_key is usually unneeded locally (Ollama ignores it; some vLLM setups
    # want a non-empty dummy).
    local_base_url: str = os.getenv("LOCAL_BASE_URL", "http://localhost:11434/v1")
    # gemma3:4b is the chosen local model: 0% hallucination on the eval, clean
    # prose without the repetition qwen2.5:14b showed, and fast. Overridable via
    # LOCAL_MODEL, but the default must match the deployed decision so a fresh
    # deploy without an .env doesn't silently warm/serve the rejected model.
    local_model: str = os.getenv("LOCAL_MODEL", "gemma3:4b")
    local_api_key: str = os.getenv("LOCAL_API_KEY", "")

    # Timeout for a single LLM generation call. Larger than go_api_timeout_seconds
    # (model latency >> an analytics read), but deliberately kept well under the
    # BE's AI_SERVICE_TIMEOUT_SECONDS (30s): the pipeline may make two model
    # calls (generate + one verify-retry), so 2×12s + overhead still fits inside
    # BE's window, letting a slow model degrade to our own grounded reply instead
    # of BE timing out and dropping it. gemma3:4b warm answers in ~5s.
    ai_request_timeout_seconds: float = float(os.getenv("AI_REQUEST_TIMEOUT_SECONDS", "12"))

    go_api_base_url: str = os.getenv("GO_API_BASE_URL", "http://localhost:8080/api/v1")
    go_api_timeout_seconds: float = float(os.getenv("GO_API_TIMEOUT_SECONDS", "5"))

    app_port: int = int(os.getenv("APP_PORT", "8000"))


settings = Settings()

# Known assumption constants (§1 isi-stasiun-ai-integration.md). AI only *reads*
# these to check claims against — it never invents or recomputes them. If BE
# changes the pipeline constant, update it here too (single source per repo).
PURCHASE_CONVERSION = 0.95  # C
V_DEFAULTS = {
    "makanan_minuman": 25000,
    "ritel_kemasan": 30000,
}
