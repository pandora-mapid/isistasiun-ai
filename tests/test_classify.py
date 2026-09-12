from app.classify import classify


def test_classify_spending_gap_default():
    a = classify("berapa kesenjangan belanja di sini?")
    assert a.intent == "spending_gap"


def test_classify_category_gap_beats_spending_gap_phrase_overlap():
    """"kategori apa yang potensinya besar" contains "potensi" (a spending_gap
    phrase) but should still classify as category_gap — mirrors intent.go's
    comment that specific intents are tried before the spending_gap catch-all."""
    a = classify("kategori apa yang potensinya besar di sudirman?")
    assert a.intent == "category_gap"


def test_classify_extracts_category_and_slot():
    a = classify("kategori apotek apa yang belum ada sore ini?")
    assert a.category == "apotek_kesehatan"
    assert a.time_slot == "evening"


def test_classify_unknown_with_no_signal():
    a = classify("halo, apa kabar?")
    assert a.intent == "unknown"


def test_classify_bare_slot_defaults_to_spending_gap():
    a = classify("bagaimana kondisi pagi ini?")
    assert a.intent == "spending_gap"
    assert a.time_slot == "morning"


def test_spatial_filter_omits_unset_keys():
    a = classify("halo")
    assert a.spatial_filter() is None
    a2 = classify("kesenjangan belanja sore", station_id="s1")
    assert a2.spatial_filter() == {"station_id": "s1", "time_slot": "evening"}
