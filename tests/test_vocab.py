from app.vocab import CANONICAL_CATEGORIES, normalize


def test_normalize_known_brands_from_field_survey():
    assert normalize("Indomaret Pintu Timur") == "ritel_kemasan"
    assert normalize("CFC") == "makanan_minuman"
    assert normalize("Family Mart") == "ritel_kemasan"
    assert normalize("Lawson") == "ritel_kemasan"
    assert normalize("Roti O") == "makanan_minuman"
    assert normalize("Apotek Kimia Farma") == "apotek_kesehatan"


def test_normalize_unknown_falls_back_to_lainnya():
    assert normalize("Toko Serbaguna XYZ123") == "lainnya"


def test_normalize_empty_string():
    assert normalize("") == "lainnya"
    assert normalize("   ") == "lainnya"


def test_normalize_case_insensitive():
    assert normalize("indomaret") == normalize("INDOMARET") == normalize("InDomaret")


def test_normalize_fuzzy_typo():
    # close enough to "indomaret" to hit the difflib fallback
    assert normalize("Indomart") == "ritel_kemasan"


def test_normalize_always_returns_canonical_category():
    for name in ["CFC", "apotek", "laundry kilat", "random gerai", ""]:
        assert normalize(name) in CANONICAL_CATEGORIES
