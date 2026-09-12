from app.verifier import (
    extract_numbers_from_text,
    numbers_match,
    parse_id_number,
    verify,
)


def test_parse_id_number_million_with_comma_decimal():
    assert parse_id_number("Rp 1,8 jt") == 1_800_000


def test_parse_id_number_thousands_separator():
    assert parse_id_number("900.000") == 900_000


def test_parse_id_number_ratio_decimal():
    assert parse_id_number("0,95") == 0.95


def test_parse_id_number_thousand_suffix():
    assert parse_id_number("Rp30 rb") == 30_000


def test_extract_numbers_from_text_finds_tagged_and_grouped_numbers():
    text = "Gap Rp900.000 - Rp1,6 jt, dan biaya operasional 30 rb per hari."
    nums = extract_numbers_from_text(text)
    assert any(numbers_match(n, 900_000) for n in nums)
    assert any(numbers_match(n, 1_600_000) for n in nums)
    assert any(numbers_match(n, 30_000) for n in nums)


def test_extract_numbers_ignores_bare_small_integers():
    text = "Ada 6 topik dan 3 pintu yang bisa ditanyakan."
    assert extract_numbers_from_text(text) == []


CONTEXT = {
    "station_id": "s1",
    "assumptions": {"C": 0.95, "V": {"makanan_minuman": 25000}},
    "spending_gap": {
        "evening": {
            "gap": {"p10": 900_000, "p90": 1_600_000},
            "captured": {"p10": 200_000, "p90": 400_000},
            "potential": {"p10": 1_100_000, "p90": 2_000_000},
        }
    },
    "confidence": {"zones": [{"zone_id": "z1", "is_thin_sample": False}], "any_thin_sample": False},
}


def test_verify_passes_when_claim_matches_source():
    answer = {
        "answer_text": "Di Sudirman sore, gap belanja Rp0,9 jt–Rp1,6 jt (estimasi, C=95%).",
        "claims": [
            {"value": 900_000, "unit": "IDR", "field_ref": "spending_gap.evening.gap.p10"},
            {"value": 1_600_000, "unit": "IDR", "field_ref": "spending_gap.evening.gap.p90"},
        ],
    }
    result = verify(answer, CONTEXT)
    assert result.ok, result.to_dict()


def test_verify_fails_on_unreferenced_number():
    answer = {
        "answer_text": "Gap belanja sekitar Rp5 jt.",
        "claims": [],
    }
    result = verify(answer, CONTEXT)
    assert not result.ok
    assert result.unreferenced_numbers


def test_verify_fails_on_mismatched_claim():
    answer = {
        "answer_text": "Gap belanja Rp9 jt.",
        "claims": [{"value": 9_000_000, "unit": "IDR", "field_ref": "spending_gap.evening.gap.p10"}],
    }
    result = verify(answer, CONTEXT)
    assert not result.ok
    assert result.mismatches
    assert result.mismatches[0].field_ref == "spending_gap.evening.gap.p10"


def test_verify_fails_on_missing_field_ref():
    answer = {
        "answer_text": "Angka rahasia Rp10 jt.",
        "claims": [{"value": 10_000_000, "unit": "IDR", "field_ref": "spending_gap.evening.gap.nonexistent"}],
    }
    result = verify(answer, CONTEXT)
    assert not result.ok
    assert result.mismatches[0].expected is None


def test_verify_fails_on_thin_sample_confidence_claim():
    """Only confidence.* claims are gated on is_thin_sample — a spending_gap
    claim is NOT blanket-gated just because the station has some thin zone
    elsewhere (see app.verifier._is_thin's docstring: the worked example in
    isi-stasiun-ai-integration.md states a concrete range for Sudirman sore
    despite the dataset being thin-sample overall)."""
    thin_context = {
        **CONTEXT,
        "confidence": {
            "zones": [{"zone_id": "z1", "is_thin_sample": True, "confidence_score": 0.2}],
            "any_thin_sample": True,
        },
    }
    answer = {
        "answer_text": "Confidence score-nya 0,2.",
        "claims": [{"value": 0.2, "unit": "ratio", "field_ref": "confidence.zones.0.confidence_score"}],
    }
    result = verify(answer, thin_context)
    assert not result.ok
    assert result.violations


def test_verify_spending_gap_claim_not_gated_by_unrelated_thin_zone():
    thin_context = {
        **CONTEXT,
        "confidence": {"zones": [{"zone_id": "z1", "is_thin_sample": True}], "any_thin_sample": True},
    }
    answer = {
        "answer_text": "Gap belanja Rp0,9 jt.",
        "claims": [{"value": 900_000, "unit": "IDR", "field_ref": "spending_gap.evening.gap.p10"}],
    }
    result = verify(answer, thin_context)
    assert result.ok, result.to_dict()


def test_verify_fails_on_wrong_assumption():
    answer = {
        "answer_text": "Konversi beli diasumsikan C=80%.",
        "claims": [],
    }
    result = verify(answer, CONTEXT)
    assert not result.ok
    assert any("C=" in v for v in result.violations)


def test_verify_accepts_correct_assumption_mention():
    answer = {
        "answer_text": "Konversi beli diasumsikan C=95%.",
        "claims": [],
    }
    result = verify(answer, CONTEXT)
    assert result.ok, result.to_dict()
