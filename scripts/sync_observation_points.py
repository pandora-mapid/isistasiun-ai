"""Generate observation-points.geojson from the canonical JSON fixture."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/source/field/observation-points.json"
TARGET = ROOT / "data/source/field/observation-points.geojson"


def feature_collection(payload: dict) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "id": row["id"],
                    "station": row["station"],
                    "type": row["type"],
                    "label": row["label"],
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [row["lon"], row["lat"]],
                },
            }
            for row in payload["data"]
        ],
    }


def main() -> None:
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    TARGET.write_text(
        json.dumps(feature_collection(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
