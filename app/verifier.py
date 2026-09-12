"""T1 — zero-hallucination verifier (isi-stasiun-ai-integration.md's iron rule:
"AI tidak boleh menyebut angka yang tidak ada di data sumber"). Pure Python,
no LLM involved in checking — the LLM is the thing being checked.

Contract: the model is prompted (see app/prompts/copilot_query.md) to return
structured JSON `{answer_text, claims: [{value, unit, field_ref}]}` instead of
free prose. `verify()` then:
  1. checks every claim's value against the JSON source at its field_ref
     (tolerant of Indonesian-format rounding),
  2. sweeps answer_text for any number that isn't backed by a passing claim,
  3. checks any C=/V= assumption mentions against the known constants,
  4. flags a claim against a null/thin-sample source field as a violation —
     the answer must hedge ("tidak diestimasi") instead of stating a number.

A field_ref that fails step 1 for a *range* pair (p10/p90) is still checked
per-field, not as a pair — matching how claims are emitted (each claim is one
number with one field_ref).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.config import PURCHASE_CONVERSION, V_DEFAULTS
from app.grounding import get_field

_MULTIPLIERS = {"jt": 1_000_000, "juta": 1_000_000, "rb": 1_000, "ribu": 1_000}

# Numbers "in the wild" that look like an actual figure worth grounding:
# thousands-separated ("900.000"), comma-decimal ("0,95"), or tagged with
# Rp/jt/rb/ribu/%. This deliberately does NOT flag small bare integers like
# "3 pintu" or "6 topik" as claims needing a field_ref — those aren't the
# "angka karangan" (invented figures) the rule targets, and treating every
# digit in the prose as a claim would make the sweep useless from false
# positives. Tune this pattern if a real hallucination slips through it.
_NUMBER_TOKEN = re.compile(
    r"(?P<rp>Rp\.?\s*)?"
    r"(?P<num>\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+,\d+|\d+(?=\s*(?:jt|juta|rb|ribu|%)))"
    r"\s*(?P<mult>jt|juta|rb|ribu)?"
    r"(?P<pct>\s*%)?",
    re.IGNORECASE,
)

_ASSUMPTION_C = re.compile(r"(?i)\bC\s*=\s*(\d+(?:[.,]\d+)?)\s*%")
_ASSUMPTION_V = re.compile(
    r"(?i)\bV(?:\s*\(([a-z_]+)\))?\s*=\s*Rp\.?\s*([\d.,]+)\s*(jt|juta|rb|ribu)?"
)


def parse_id_number(raw: str) -> float:
    """"Rp 1,8 jt" -> 1_800_000.0 · "900.000" -> 900000.0 · "0,95" -> 0.95."""
    s = raw.strip()
    s = re.sub(r"(?i)^rp\.?\s*", "", s).strip()

    mult = 1
    m = re.search(r"(?i)\b(jt|juta|rb|ribu)\b\s*$", s)
    if m:
        mult = _MULTIPLIERS[m.group(1).lower()]
        s = s[: m.start()].strip()

    if "." in s and "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    elif "." in s:
        groups = s.split(".")
        if len(groups) > 1 and all(len(g) == 3 for g in groups[1:]):
            s = s.replace(".", "")
    return float(s) * mult


def extract_numbers_from_text(text: str) -> list[float]:
    """Sweeps prose for figure-shaped numbers, skipping spans already claimed
    by an assumption mention (C=.../V=...) so they aren't double-flagged."""
    claimed_spans: list[tuple[int, int]] = []
    for rx in (_ASSUMPTION_C, _ASSUMPTION_V):
        claimed_spans.extend(m.span() for m in rx.finditer(text))

    def _inside_claimed(pos: int) -> bool:
        return any(a <= pos < b for a, b in claimed_spans)

    out: list[float] = []
    for m in _NUMBER_TOKEN.finditer(text):
        if _inside_claimed(m.start()):
            continue
        num = m.group("num")
        mult = m.group("mult") or ""
        pct = m.group("pct")
        try:
            value = parse_id_number(f"{num} {mult}".strip())
        except ValueError:
            continue
        if pct:
            value = value / 100
        out.append(value)
    return out


def numbers_match(value: float, expected: float) -> bool:
    """Tolerant compare: exact for zero/near-zero expected, else within the
    "±1 digit signifikan" rounding tolerance the spec calls out — a relative
    tolerance covers e.g. "0,9 jt" (900_000) matching an exact 912_345."""
    if expected == 0:
        return abs(value) < 1
    return abs(value - expected) / abs(expected) <= 0.06


@dataclass
class Mismatch:
    field_ref: str
    expected: float | None
    got: float


@dataclass
class VerificationResult:
    ok: bool
    mismatches: list[Mismatch] = field(default_factory=list)
    unreferenced_numbers: list[float] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "mismatches": [m.__dict__ for m in self.mismatches],
            "unreferenced_numbers": self.unreferenced_numbers,
            "violations": self.violations,
        }


def _is_thin(context: dict, field_ref: str) -> bool:
    """Only confidence.* claims are gated here — that's the one field whose
    *value itself* is "is this sample thin" (LayerEntry.is_thin_sample).

    spending_gap/category_gap don't get a blanket "whole station is small-N,
    so hide every number" gate: isi-stasiun-ai-integration.md's own worked
    example states a concrete Rupiah range for Sudirman sore despite the
    dataset being thin overall (§G caveat 2). The doc's actual null/hidden
    case — Sudirman pagi has no Lewat denominator — is already represented by
    that slot being *absent* from spending_gap context (see
    app/grounding.py), which the answer builders already treat as
    "not available" rather than a number to gate here."""
    if field_ref.startswith("confidence."):
        confidence = context.get("confidence") or {}
        return bool(confidence.get("any_thin_sample"))
    return False


def verify(answer: dict, context: dict) -> VerificationResult:
    """answer: {"answer_text": str, "claims": [{"value","unit","field_ref"}]}."""
    result = VerificationResult(ok=True)
    answer_text = answer.get("answer_text", "")
    claims = answer.get("claims", [])

    referenced_values: list[float] = []
    for claim in claims:
        field_ref = claim.get("field_ref", "")
        value = claim.get("value")
        if value is None or not field_ref:
            result.violations.append(f"claim missing value/field_ref: {claim!r}")
            result.ok = False
            continue

        expected = get_field(context, field_ref)

        if expected is None:
            result.mismatches.append(Mismatch(field_ref, None, value))
            result.ok = False
            continue

        if _is_thin(context, field_ref):
            result.violations.append(
                f"claim on thin-sample field '{field_ref}' must hedge, not state a number"
            )
            result.ok = False
            continue

        if isinstance(expected, (int, float)) and not numbers_match(float(value), float(expected)):
            result.mismatches.append(Mismatch(field_ref, float(expected), float(value)))
            result.ok = False
            continue

        referenced_values.append(float(value))

    for num in extract_numbers_from_text(answer_text):
        if not any(numbers_match(num, ref) for ref in referenced_values):
            result.unreferenced_numbers.append(num)
            result.ok = False

    assumptions = context.get("assumptions", {"C": PURCHASE_CONVERSION, "V": V_DEFAULTS})
    for m in _ASSUMPTION_C.finditer(answer_text):
        stated = float(m.group(1).replace(",", ".")) / 100
        known = assumptions.get("C", PURCHASE_CONVERSION)
        if not numbers_match(stated, known):
            result.violations.append(f"stated C={stated} does not match known C={known}")
            result.ok = False
    for m in _ASSUMPTION_V.finditer(answer_text):
        category, raw_value, mult = m.group(1), m.group(2), m.group(3)
        stated = parse_id_number(f"{raw_value} {mult or ''}".strip())
        known_v = assumptions.get("V", V_DEFAULTS)
        known = known_v.get(category) if category else None
        if known is not None and not numbers_match(stated, known):
            result.violations.append(f"stated V({category})={stated} does not match known V={known}")
            result.ok = False

    return result
