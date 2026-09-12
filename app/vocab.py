"""T4 — normalize a gerai/POI name into one of the 5 canonical categories.

Canonical set and matching style deliberately mirror
isistasiun-be/backend/internal/copilot/intent.go's categoryPhrases (keyword,
first-match-wins, ordered) so a category mentioned in a copilot query and a
category assigned to a real gerai name land in the same bucket. See
data/vocab_lookup.json for the reviewed table and its sourcing notes.
"""

from __future__ import annotations

import difflib
import json
import re
from pathlib import Path
from typing import Iterable

LOOKUP_PATH = Path(__file__).resolve().parent.parent / "data" / "vocab_lookup.json"

CANONICAL_CATEGORIES = ["makanan_minuman", "ritel_kemasan", "apotek_kesehatan", "jasa", "lainnya"]

# Fixed order: more specific buckets before the catch-alls, so e.g. "apotek"
# (apotek_kesehatan) is tried before generic "toko" terms.
_CATEGORY_ORDER = ["makanan_minuman", "ritel_kemasan", "apotek_kesehatan", "jasa", "lainnya"]


def _load_lookup() -> dict[str, list[str]]:
    with LOOKUP_PATH.open(encoding="utf-8") as f:
        raw = json.load(f)
    return {k: v for k, v in raw.items() if not k.startswith("_")}


_LOOKUP = _load_lookup()


def _normalize_text(s: str) -> str:
    s = s.strip().lower()
    return re.sub(r"\s+", " ", s)


def _all_keywords() -> Iterable[tuple[str, str]]:
    for category, keywords in _LOOKUP.items():
        for kw in keywords:
            yield kw, category


def normalize(nama_gerai: str) -> str:
    """"Indomaret Pintu Timur" -> "ritel_kemasan". Unknown -> "lainnya"
    (never raises — an unrecognized name is a data-quality note, not an
    error the caller should have to handle)."""
    if not nama_gerai or not nama_gerai.strip():
        return "lainnya"

    q = _normalize_text(nama_gerai)

    for category in _CATEGORY_ORDER:
        for kw in _LOOKUP.get(category, []):
            if kw in q:
                return category

    # Fuzzy fallback: catches typos/variants of known brand names
    # ("Indomart" -> "indomaret") that no substring match would catch.
    all_kw = [kw for kw, _ in _all_keywords()]
    close = difflib.get_close_matches(q, all_kw, n=1, cutoff=0.8)
    if close:
        matched = close[0]
        for category in _CATEGORY_ORDER:
            if matched in _LOOKUP.get(category, []):
                return category

    return "lainnya"
