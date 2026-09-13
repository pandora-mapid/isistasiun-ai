import json
from pathlib import Path

from scripts.sync_observation_points import feature_collection


ROOT = Path(__file__).resolve().parents[1]


def test_observation_points_geojson_matches_canonical_json():
    source = json.loads(
        (ROOT / "data/source/field/observation-points.json").read_text(encoding="utf-8")
    )
    geojson = json.loads(
        (ROOT / "data/source/field/observation-points.geojson").read_text(encoding="utf-8")
    )

    assert geojson == feature_collection(source)


def test_canonical_entrances_are_unique_and_complete():
    source = json.loads(
        (ROOT / "data/source/field/observation-points.json").read_text(encoding="utf-8")
    )
    entrances = [row for row in source["data"] if row["type"] == "entrance"]

    assert len(entrances) == 5
    assert len({(row["station"], row["label"].casefold()) for row in entrances}) == 5
    assert {row["station"] for row in entrances} == {"Manggarai", "Sudirman"}
