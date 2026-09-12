"""The seam: generate(prompt) -> raw text, swappable by AI_BACKEND.

  - "gemini": calls the Gemini API (same google-generativeai SDK + call shape
    as isistasiun-be/pipeline/shared/gemini.py, for consistency).
  - "stub": canned/templated output, no network or key needed. Per
    ai-onboarding-teman.md: "verifier & eval bahkan tak perlu API key" — T1
    and T2 must be exercisable offline.
  - "local": placeholder for a future Ollama/vLLM seam (out of this task's
    scope — ai-onboarding-teman.md §3 excludes "model lokal + seam GPU").

Returns None on any failure (missing key, network error, bad response) rather
than raising — callers (main.py) must fall back to the deterministic template
built straight from grounded context, never block the map on this (the same
rule Go's copilot/service.go already applies one layer up).
"""

from __future__ import annotations

import logging

from app.config import settings

logger = logging.getLogger(__name__)


class SeamError(RuntimeError):
    pass


def _looks_like_placeholder(key: str) -> bool:
    return not key or key.strip().lower() in {"changeme", "your-api-key-here", ""}


def _generate_gemini(prompt: str, *, json_mode: bool) -> str:
    import google.generativeai as genai  # deferred: heavy, network-only path

    genai.configure(api_key=settings.gemini_api_key)
    model = genai.GenerativeModel(settings.gemini_model)
    generation_config = {"temperature": 0.0}
    if json_mode:
        generation_config["response_mime_type"] = "application/json"

    response = model.generate_content(prompt, generation_config=generation_config)
    text = (getattr(response, "text", "") or "").strip()
    if not text:
        raise SeamError("empty response from Gemini")
    return text


def _generate_stub(prompt: str, *, json_mode: bool) -> str:
    """Deterministic canned text so tests/eval run with AI_BACKEND=stub and no
    key. Does not try to be a smart mock — it's a fixed placeholder that
    exercises the plumbing (seam -> verifier -> fallback), not the prompt."""
    if json_mode:
        return '{"answer_text": "(stub) tidak ada model terhubung.", "claims": []}'
    return "(stub) tidak ada model terhubung."


def generate(prompt: str, *, json_mode: bool = False) -> str | None:
    backend = settings.ai_backend.lower()

    if backend == "stub":
        return _generate_stub(prompt, json_mode=json_mode)

    if backend == "gemini":
        if _looks_like_placeholder(settings.gemini_api_key):
            logger.warning("AI_BACKEND=gemini but GEMINI_API_KEY looks unset; degrading")
            return None
        try:
            return _generate_gemini(prompt, json_mode=json_mode)
        except Exception:
            logger.exception("gemini generation failed; degrading to deterministic fallback")
            return None

    if backend == "local":
        raise NotImplementedError(
            "AI_BACKEND=local (Ollama/vLLM) is out of this module's scope — see app/seam.py docstring"
        )

    raise SeamError(f"unknown AI_BACKEND: {settings.ai_backend!r}")
