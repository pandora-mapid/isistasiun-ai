"""Offline tests for the generation seam (app/seam.py). No network: httpx.post
is monkeypatched. Covers the OpenAI-compatible backends (groq/local), the
degrade-to-None contract on failure, and backend selection."""

import dataclasses

import httpx
import pytest

from app import seam
from app.config import Settings


def _with_settings(monkeypatch, **overrides):
    # Isolate from any real .env that load_dotenv() pulled in: default the
    # chain to empty so a test setting only `ai_backend` isn't overridden by a
    # developer's AI_BACKENDS. Chain tests pass `ai_backends` explicitly.
    overrides.setdefault("ai_backends", "")
    monkeypatch.setattr(seam, "settings", dataclasses.replace(Settings(), **overrides))


class _FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self._status = status

    def raise_for_status(self):
        if self._status >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)

    def json(self):
        return self._payload


def _chat_payload(content):
    return {"choices": [{"message": {"content": content}}]}


def test_stub_backend_needs_no_network():
    # Default Settings() has AI_BACKEND=stub unless env overrides; assert the
    # JSON-mode stub is valid, parseable, claim-free plumbing output.
    out = seam._generate_stub("ignored", json_mode=True)
    assert '"answer_text"' in out and '"claims": []' in out


def test_groq_happy_path(monkeypatch):
    _with_settings(monkeypatch, ai_backend="groq", groq_api_key="sk-real-key")
    captured = {}

    def fake_post(url, json, headers, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return _FakeResponse(_chat_payload('{"answer_text": "ok", "claims": []}'))

    monkeypatch.setattr(seam.httpx, "post", fake_post)

    out = seam.generate("hello", json_mode=True)
    assert out == '{"answer_text": "ok", "claims": []}'
    assert captured["url"].endswith("/chat/completions")
    assert captured["headers"]["Authorization"] == "Bearer sk-real-key"
    assert captured["json"]["response_format"] == {"type": "json_object"}
    assert captured["json"]["temperature"] == 0.0


def test_groq_missing_key_degrades(monkeypatch):
    _with_settings(monkeypatch, ai_backend="groq", groq_api_key="changeme")
    # Must not even attempt a request when the key is a placeholder.
    monkeypatch.setattr(
        seam.httpx, "post", lambda *a, **k: pytest.fail("should not call network")
    )
    assert seam.generate("hi", json_mode=True) is None


def test_local_no_auth_header_and_reachable(monkeypatch):
    _with_settings(monkeypatch, ai_backend="local", local_api_key="")
    captured = {}

    def fake_post(url, json, headers, timeout):
        captured["headers"] = headers
        return _FakeResponse(_chat_payload("plain text answer"))

    monkeypatch.setattr(seam.httpx, "post", fake_post)

    out = seam.generate("hi", json_mode=False)
    assert out == "plain text answer"
    assert "Authorization" not in captured["headers"]  # local server needs no key
    assert "response_format" not in captured  # not requested when json_mode=False


def test_network_error_degrades_to_none(monkeypatch):
    _with_settings(monkeypatch, ai_backend="local")

    def boom(*a, **k):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(seam.httpx, "post", boom)
    assert seam.generate("hi", json_mode=True) is None


def test_malformed_response_degrades_to_none(monkeypatch):
    _with_settings(monkeypatch, ai_backend="groq", groq_api_key="sk-real-key")
    monkeypatch.setattr(
        seam.httpx, "post", lambda *a, **k: _FakeResponse({"unexpected": "shape"})
    )
    assert seam.generate("hi", json_mode=True) is None


def test_unknown_backend_raises(monkeypatch):
    _with_settings(monkeypatch, ai_backend="does-not-exist")
    with pytest.raises(seam.SeamError):
        seam.generate("hi")


def test_chain_falls_through_local_to_groq(monkeypatch):
    # AI_BACKENDS chain: local is down (connection refused) -> groq answers.
    _with_settings(
        monkeypatch, ai_backends="local,groq", groq_api_key="sk-real-key"
    )

    def fake_post(url, json, headers, timeout):
        if "11434" in url:  # local Ollama down
            raise httpx.ConnectError("connection refused")
        return _FakeResponse(_chat_payload('{"answer_text": "from groq", "claims": []}'))

    monkeypatch.setattr(seam.httpx, "post", fake_post)
    assert seam.generate("hi", json_mode=True) == '{"answer_text": "from groq", "claims": []}'


def test_chain_all_fail_returns_none(monkeypatch):
    # Whole chain down -> None, so the caller uses the deterministic fallback.
    _with_settings(monkeypatch, ai_backends="local,groq", groq_api_key="sk-real-key")
    monkeypatch.setattr(
        seam.httpx, "post", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("down"))
    )
    assert seam.generate("hi", json_mode=True) is None
