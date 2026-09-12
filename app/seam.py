"""The seam: generate(prompt) -> raw text, swappable by AI_BACKEND.

  - "gemini": calls the Gemini API (same google-generativeai SDK + call shape
    as isistasiun-be/pipeline/shared/gemini.py, for consistency).
  - "groq":   calls Groq's OpenAI-compatible chat/completions over httpx. This
    is the API-only deploy path — the service runs on a plain VPS with no GPU.
  - "local":  calls a local OpenAI-compatible server (Ollama/vLLM) over httpx,
    for running an open model on the workstation GPU. Same wire format as groq;
    only base_url/model/key differ.
  - "stub":   canned/templated output, no network or key needed. Per
    ai-onboarding-teman.md: "verifier & eval bahkan tak perlu API key" — the
    verifier and eval must be exercisable offline.

Returns None on any failure (missing key, network error, bad response) rather
than raising — callers (main.py) must fall back to the deterministic template
built straight from grounded context, never block the map on this (the same
rule Go's copilot/service.go already applies one layer up). The one exception
is a misconfigured AI_BACKEND name, which is a deploy error, not a runtime one.
"""

from __future__ import annotations

import logging

import httpx

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


def _generate_openai_compatible(
    prompt: str,
    *,
    json_mode: bool,
    base_url: str,
    api_key: str,
    model: str,
    provider: str,
) -> str:
    """Shared client for any /chat/completions endpoint (Groq, Ollama, vLLM).

    Temperature is pinned to 0 for reproducibility (verifier/eval assume the
    model is as deterministic as the provider allows). json_mode requests a
    JSON object; providers that ignore response_format still tend to comply
    because the prompt itself demands JSON, and the pipeline degrades safely on
    non-JSON anyway (app/pipeline.py catches JSONDecodeError)."""
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload: dict = {
        "model": model,
        "temperature": 0.0,
        "messages": [{"role": "user", "content": prompt}],
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    resp = httpx.post(
        url, json=payload, headers=headers, timeout=settings.ai_request_timeout_seconds
    )
    resp.raise_for_status()
    data = resp.json()
    try:
        text = (data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise SeamError(f"unexpected {provider} response shape: {data!r}") from exc
    if not text:
        raise SeamError(f"empty response from {provider}")
    return text


def _generate_stub(prompt: str, *, json_mode: bool) -> str:
    """Deterministic canned text so tests/eval run with AI_BACKEND=stub and no
    key. Does not try to be a smart mock — it's a fixed placeholder that
    exercises the plumbing (seam -> verifier -> fallback), not the prompt."""
    if json_mode:
        return '{"answer_text": "(stub) tidak ada model terhubung.", "claims": []}'
    return "(stub) tidak ada model terhubung."


def _generate_with_backend(backend: str, prompt: str, *, json_mode: bool) -> str | None:
    """Runs one backend. Returns None on any *runtime* failure (missing key,
    network error, bad response) so the caller can try the next link in the
    chain or fall back deterministically. Raises SeamError only for an unknown
    backend name — that's a deploy misconfiguration, not a runtime condition."""
    backend = backend.lower()

    if backend == "stub":
        return _generate_stub(prompt, json_mode=json_mode)

    if backend == "gemini":
        if _looks_like_placeholder(settings.gemini_api_key):
            logger.warning("backend=gemini but GEMINI_API_KEY looks unset; skipping")
            return None
        try:
            return _generate_gemini(prompt, json_mode=json_mode)
        except Exception:
            logger.exception("gemini generation failed; trying next backend / fallback")
            return None

    if backend == "groq":
        if _looks_like_placeholder(settings.groq_api_key):
            logger.warning("backend=groq but GROQ_API_KEY looks unset; skipping")
            return None
        try:
            return _generate_openai_compatible(
                prompt,
                json_mode=json_mode,
                base_url=settings.groq_base_url,
                api_key=settings.groq_api_key,
                model=settings.groq_model,
                provider="groq",
            )
        except Exception:
            logger.exception("groq generation failed; trying next backend / fallback")
            return None

    if backend == "local":
        # No key check: local servers (Ollama) commonly need none. If the
        # server is down, httpx raises (fast connection-refused when the PC is
        # off) and we move on to the next backend.
        try:
            return _generate_openai_compatible(
                prompt,
                json_mode=json_mode,
                base_url=settings.local_base_url,
                api_key=settings.local_api_key,
                model=settings.local_model,
                provider="local",
            )
        except Exception:
            logger.exception("local generation failed; trying next backend / fallback")
            return None

    raise SeamError(f"unknown AI backend: {backend!r}")


def _backend_chain() -> list[str]:
    """AI_BACKENDS (comma-separated) wins if set, else the single AI_BACKEND."""
    chain = [b.strip() for b in settings.ai_backends.split(",") if b.strip()]
    return chain or [settings.ai_backend]


def generate(prompt: str, *, json_mode: bool = False) -> str | None:
    """Tries each backend in the configured chain until one returns text.
    Returns None only if every backend fails — callers then use the
    deterministic grounded fallback."""
    for backend in _backend_chain():
        out = _generate_with_backend(backend, prompt, json_mode=json_mode)
        if out:
            return out
    return None
