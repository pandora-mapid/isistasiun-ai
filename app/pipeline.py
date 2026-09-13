"""Wires T1 (verifier) + T3 (grounding) + T4 (vocab, via classify's category
matching) + the seam together for /copilot/query. This is "integrasi akhir"
in ai-onboarding-teman.md §3 terms — kept intentionally thin: no persona or
prompt-craft here, just plumbing so T1-T4 are demonstrably pluggable end to
end, per the onboarding doc's closing line ("modul T1-T4 dengan antarmuka
jelas ... supaya bisa dicolok ke service").
"""

from __future__ import annotations

import json
import logging

from app import seam
from app.answer import build_prompt, deterministic_answer
from app.classify import Analysis, classify
from app.grounding import build_context
from app.verifier import verify

logger = logging.getLogger(__name__)


def _parse_json_object(raw: str) -> dict | None:
    """Tolerant JSON extraction. Some models wrap the object in ```json fences
    or add stray prose around it; take the outermost {...} span and parse that
    so a well-formed answer isn't thrown away over formatting. Returns None if
    nothing parseable is found."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


def _try_generate(query: str, context: dict, *, retry_note: str | None = None) -> dict | None:
    prompt = build_prompt(query, context)
    if retry_note:
        prompt += f"\n\nCatatan: percobaan sebelumnya gagal verifikasi — perbaiki: {retry_note}"

    raw = seam.generate(prompt, json_mode=True)
    if not raw:
        return None
    parsed = _parse_json_object(raw)
    if parsed is None:
        logger.warning("model returned non-JSON output; degrading")
        return None
    if not isinstance(parsed, dict) or "answer_text" not in parsed:
        return None
    parsed.setdefault("claims", [])
    return parsed


def run(query: str, station_id: str = "") -> dict:
    """Full detail version, used by eval/runner.py (T2) to see what
    answer_query() only returns the FE-facing slice of: which path was taken
    (model vs. deterministic fallback) and the raw verifier result."""
    analysis: Analysis = classify(query, station_id)
    context = build_context(analysis)

    def _insufficient(candidate: dict) -> bool:
        # An intent that has grounded data to talk about but the model came
        # back with zero claims is treated as insufficient (not "verified
        # empty") — it would otherwise pass verification trivially while
        # saying nothing useful. `unknown`/out-of-scope answers legitimately
        # have no claims, so they're exempt.
        return not candidate["claims"] and analysis.intent != "unknown" and _has_groundable_data(context, analysis)

    verify_result = None
    used_fallback = True
    answer = None

    parsed = _try_generate(query, context)
    if parsed is not None:
        verify_result = verify(parsed, context)
        if verify_result.ok and not _insufficient(parsed):
            answer, used_fallback = parsed, False
        else:
            retried = _try_generate(query, context, retry_note=json.dumps(verify_result.to_dict(), ensure_ascii=False))
            if retried is not None:
                verify_result = verify(retried, context)
                if verify_result.ok and not _insufficient(retried):
                    answer, used_fallback = retried, False

    if answer is None:
        answer = deterministic_answer(analysis, context)

    return {
        "analysis": analysis,
        "context": context,
        "answer": answer,
        "used_fallback": used_fallback,
        "verify_result": verify_result,
    }


def answer_query(query: str, station_id: str = "") -> tuple[str, list[str], dict | None]:
    result = run(query, station_id)
    analysis = result["analysis"]
    return result["answer"]["answer_text"].strip(), analysis.layers, analysis.spatial_filter()


def _has_groundable_data(context: dict, analysis: Analysis) -> bool:
    if analysis.intent == "flow" and context.get("flow", {}).get("busiest"):
        return True
    if analysis.intent in ("spending_gap", "flow") and context.get("spending_gap"):
        return True
    if analysis.intent == "category_gap" and context.get("category_gap", {}).get("missing") is not None:
        return True
    if analysis.intent == "confidence" and context.get("confidence", {}).get("zones"):
        return True
    return False
