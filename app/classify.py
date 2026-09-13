"""Python mirror of isistasiun-be/backend/internal/copilot/intent.go.

Go already classifies intent deterministically and keeps that as the floor
(service.go: `merge` lets our answer improve the prose, never the filter this
module would derive). We re-run the same deterministic rules here rather than
receiving the classification over the wire, because the QueryRequest contract
is intentionally staying `{query, station_id}` (§5 of
isi-stasiun-ai-integration.md: "Default sekarang: tidak ada perubahan DTO").
We need *something* to decide which analytics to fetch for grounding, and it
must be deterministic too ("Intent tetap di Go ... jangan pindah ke LLM" —
this mirrors that rule locally rather than breaking it).

Keep this in sync with intent.go if the phrase tables there change; the two
are independent implementations of the same spec, not a shared library.
"""

from __future__ import annotations

from dataclasses import dataclass, field

INTENT_SPENDING_GAP = "spending_gap"
INTENT_CATEGORY_GAP = "category_gap"
INTENT_RENT_FLOW = "rent_flow_index"
INTENT_EVENT_POTENTIAL = "event_potential"
INTENT_CONFIDENCE = "confidence"
INTENT_FLOW = "flow"
INTENT_COMPARE = "compare"
INTENT_UNKNOWN = "unknown"

LAYER_GAP = "gap"
LAYER_POTENSI = "potensi"
LAYER_KEPERCAYAAN = "kepercayaan"
LAYER_KATEGORI = "kategori-hilang"
LAYER_ARUS = "arus"
LAYER_SEWA = "sewa"
LAYER_EVENT = "event"

CATEGORY_PHRASES: list[tuple[str, list[str]]] = [
    ("makanan_minuman", ["makanan", "minuman", "makan", "minum", "kopi", "kuliner", "f&b", "fnb", "resto", "kafe", "cafe"]),
    ("ritel_kemasan", ["ritel", "retail", "kemasan", "minimarket", "swalayan", "convenience", "oleh-oleh"]),
    ("apotek_kesehatan", ["apotek", "obat", "kesehatan", "farmasi", "klinik"]),
    ("jasa", ["jasa", "layanan", "servis", "laundry", "barbershop", "salon"]),
    ("lainnya", ["lainnya", "lain-lain"]),
]

SLOT_PHRASES: list[tuple[str, list[str]]] = [
    ("morning", ["pagi", "morning", "berangkat", "jam 6", "jam 7", "jam 8", "06.", "07.", "08."]),
    ("midday", ["siang", "midday", "makan siang", "jam 11", "jam 12", "jam 13", "11.", "12.", "13."]),
    ("evening", ["sore", "evening", "pulang kerja", "pulang", "jam 16", "jam 17", "jam 18", "16.", "17.", "18."]),
    ("night", ["malam", "night", "jam 19", "jam 20", "jam 21", "19.", "20.", "21."]),
]

# (intent, phrases, layers, endpoint) — order matters, see Classify() below.
INTENT_PHRASES: list[tuple[str, list[str], list[str], str]] = [
    (
        # Compare must sit ABOVE spending_gap: "bandingkan kesenjangan …" is a
        # comparison, not a single-station gap. Grounds on every station's
        # spending-gap (see grounding._compare_summary), station_id ignored.
        INTENT_COMPARE,
        ["banding", "dibanding", "versus", " vs ", "kedua stasiun", "kedua simpul", "antar stasiun", "antar simpul", "mana yang lebih", "manggarai dan sudirman", "sudirman dan manggarai"],
        [LAYER_GAP, LAYER_POTENSI],
        "/api/v1/analytics/spending-gap",
    ),
    (
        INTENT_CATEGORY_GAP,
        ["kategori", "usaha apa", "gerai apa", "jenis usaha", "belum ada", "kategori hilang", "yang kurang", "cocok dibuka", "peluang usaha", "tenant"],
        [LAYER_KATEGORI, LAYER_GAP],
        "/api/v1/analytics/category-gap",
    ),
    (
        INTENT_RENT_FLOW,
        ["sewa", "harga sewa", "petak", "mahal", "murah", "kemahalan", "kontrak", "tarif ruang"],
        [LAYER_SEWA],
        "/api/v1/analytics/rent-flow-index",
    ),
    (
        INTENT_EVENT_POTENTIAL,
        ["event", "acara", "bazar", "pop-up", "popup", "aktivasi", "tenant sementara", "kapan ramai untuk", "pameran"],
        [LAYER_EVENT, LAYER_ARUS],
        "/api/v1/analytics/event-potential",
    ),
    (
        INTENT_CONFIDENCE,
        ["sampel", "sample", "kepercayaan", "confidence", "seberapa yakin", "akurat", "data tipis", "bisa dipercaya", "keandalan"],
        [LAYER_KEPERCAYAAN],
        "/api/v1/confidence-layer",
    ),
    (
        INTENT_FLOW,
        ["arus", "pejalan", "ramai", "orang lewat", "pintu mana", "trafik", "traffic", "lalu lalang", "penumpang"],
        [LAYER_ARUS, LAYER_GAP],
        "/api/v1/analytics/spending-gap",
    ),
    (
        INTENT_SPENDING_GAP,
        ["kesenjangan", "gap", "potensi", "belanja", "peluang", "pendapatan", "tertangkap", "rupiah", "omzet", "non-tiket"],
        [LAYER_GAP, LAYER_POTENSI],
        "/api/v1/analytics/spending-gap",
    ),
]


@dataclass
class Analysis:
    intent: str = INTENT_UNKNOWN
    category: str = ""
    time_slot: str = ""
    station_id: str = ""
    layers: list[str] = field(default_factory=lambda: [LAYER_GAP])
    endpoint: str = "/api/v1/analytics/spending-gap"

    def spatial_filter(self) -> dict | None:
        f: dict = {}
        if self.station_id:
            f["station_id"] = self.station_id
        if self.category:
            f["category"] = self.category
        if self.time_slot:
            f["time_slot"] = self.time_slot
        return f or None


def _contains_any(q: str, phrases: list[str]) -> bool:
    return any(p in q for p in phrases)


def _match_first(q: str, table: list[tuple[str, list[str]]]) -> str:
    for key, phrases in table:
        if _contains_any(q, phrases):
            return key
    return ""


def classify(query: str, station_id: str = "") -> Analysis:
    q = query.lower()

    a = Analysis(
        station_id=station_id,
        category=_match_first(q, CATEGORY_PHRASES),
        time_slot=_match_first(q, SLOT_PHRASES),
    )

    for intent, phrases, layers, endpoint in INTENT_PHRASES:
        if _contains_any(q, phrases):
            a.intent = intent
            a.layers = layers
            a.endpoint = endpoint
            break

    if a.intent == INTENT_UNKNOWN and (a.category or a.time_slot):
        a.intent = INTENT_SPENDING_GAP
        a.layers = [LAYER_GAP, LAYER_POTENSI]

    return a
