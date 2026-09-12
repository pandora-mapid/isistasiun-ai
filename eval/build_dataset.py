"""Generates eval/dataset.jsonl.

expected_intent/expected_filter are computed by calling the actual
app.classify.classify() rather than hand-typed, so the dataset's ground truth
can't drift from the classifier it's meant to test against (see
eval/runner.py for what "against" means here — this dataset mainly targets
T1's hallucination-rate/hedge/out_of_scope metrics; intent/filter accuracy is
a sanity check on the deterministic classifier, not the eval's main point,
since classify() authoring its own ground truth would be circular for THAT
specific metric — see README's "Known gaps" note).

Re-run after changing app/classify.py's phrase tables:
    python -m eval.build_dataset
"""

from __future__ import annotations

import json
from pathlib import Path

from app.classify import classify

MANGGARAI = "a10a6cf2-0001-4f2b-9c1a-000000000001"
SUDIRMAN = "a10a6cf2-0002-4f2b-9c1a-000000000002"

# (query, station_id, expect_behavior, note)
# expect_behavior: normal | out_of_scope | thin_sample
ROWS: list[tuple[str, str | None, str, str]] = [
    # --- spending_gap ---
    ("berapa kesenjangan belanja di sudirman sore?", SUDIRMAN, "normal", "core intent, station+slot"),
    ("apa itu kesenjangan belanja?", None, "normal", "no station/slot mentioned"),
    ("potensi omzet yang belum tertangkap gerai berapa?", MANGGARAI, "normal", "spending_gap phrase variety"),
    ("berapa kesenjangan belanja sudirman pagi?", SUDIRMAN, "thin_sample", "Sudirman pagi tak berdenominator"),
    ("gap rupiah non-tiket kira-kira berapa di manggarai sore?", MANGGARAI, "normal", "spending_gap phrase variety + slot"),
    # --- category_gap ---
    ("kategori apa yang belum ada di sudirman sore?", SUDIRMAN, "normal", "doc worked example §2.1"),
    ("apotek apa yang belum ada di manggarai?", MANGGARAI, "normal", "category_gap + explicit category"),
    ("jenis usaha apa yang cocok dibuka di manggarai jasa?", MANGGARAI, "normal", "category_gap + jasa category"),
    ("tenant apa yang jadi peluang usaha di sudirman pagi?", SUDIRMAN, "normal", "category_gap ignores time-of-day (CategoryGapResponse has no time_slot field) — mentioning 'pagi' should not change the answer or force a hedge"),
    # --- rent_flow_index ---
    ("berapa harga sewa petak kosong di manggarai?", MANGGARAI, "normal", "rent_flow, real Lampiran D data"),
    ("kontrak tarif ruang di sudirman berapa?", SUDIRMAN, "normal", "rent_flow phrase variety"),
    # --- event_potential ---
    ("kapan waktu terbaik untuk event pop-up di sudirman?", SUDIRMAN, "normal", "event_potential, no grounding source yet"),
    ("aktivasi bazar di manggarai kapan ramai untuk pengunjung?", MANGGARAI, "normal", "event_potential phrase variety"),
    # --- confidence ---
    ("seberapa yakin data confidence di manggarai pagi?", MANGGARAI, "normal", "confidence + slot"),
    ("apakah data sudirman bisa dipercaya atau sampel tipis?", SUDIRMAN, "thin_sample", "confidence, all zones thin per fixture"),
    # --- flow ---
    ("ramai di pintu mana jam 17 di manggarai?", MANGGARAI, "normal", "flow + jam-based slot"),
    ("berapa arus pejalan kaki lalu lalang di sudirman malam?", SUDIRMAN, "normal", "flow + night slot"),
    # --- multi-filter ---
    ("kategori apotek yang belum ada di sudirman sore?", SUDIRMAN, "normal", "category_gap, category+slot+station"),
    ("makanan apa yang paling laku di siang hari manggarai?", MANGGARAI, "normal", "bare category+slot -> spending_gap default reading"),
    # --- out_of_scope ---
    ("siapa presiden indonesia sekarang?", None, "out_of_scope", "unrelated to the 6 topics"),
    ("rekomendasikan resep nasi goreng enak dong", None, "out_of_scope", "unrelated to the 6 topics"),
    ("bisa bantu isi formulir pajak saya?", None, "out_of_scope", "unrelated to the 6 topics"),
    ("halo, apa kabar?", None, "out_of_scope", "greeting, no topic signal"),
]


def main() -> None:
    out_path = Path(__file__).resolve().parent / "dataset.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for query, station_id, behavior, note in ROWS:
            analysis = classify(query, station_id or "")
            row = {
                "query": query,
                "station_id": station_id,
                "expected_intent": analysis.intent,
                "expected_filter": analysis.spatial_filter(),
                "expect_behavior": behavior,
                "note": note,
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"wrote {len(ROWS)} rows to {out_path}")


if __name__ == "__main__":
    main()
