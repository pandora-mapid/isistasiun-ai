# Source data (provenance untuk fixtures)

Data lapangan & sewa Manggarai/Sudirman yang **mendasari** `fixtures/`. Ditaruh di sini agar fixtures bisa ditelusuri — **bukan** dibaca runtime oleh service (service baca fixtures/ atau Go analytics). Asumsi & caveat lengkap ada di `_meta` tiap file.

## Isi

| File | Isi |
|---|---|
| `field/entry-conversion.json` | Per gerai per blok: `lewat`, `masuk`, `beli_est`(=0,95×masuk), `E`, `slot`, `source`. |
| `field/flow-observations.json` | Arus gerbang (Manggarai A/B, Sudirman atas). |
| `field/observation-points.json` / `.geojson` | Titik pintu/gerai/ruko/potensi + koordinat. |
| `rent/manggarai-instation.json` | Sewa in-station Manggarai (Space by KAI): tenant, luas, Rp/thn, koordinat, kosong/terisi. |
| `rent/sekitar.json` | Sewa pasar sekitar (99.co), kedua stasiun incl Sudirman. |

## Peta source → fixture

| Fixture | Diturunkan dari |
|---|---|
| `stations.json` | koordinat stasiun (field points) |
| `rent_flow_index.json` | `rent/manggarai-instation.json` (offered_rent real) ÷ arus stasiun |
| `confidence_layer.json` | jumlah blok terukur per (stasiun,slot) di `field/entry-conversion.json` |
| `category_gap.json` | kategori gerai tersurvei (available) vs demand kawasan |
| `spending_gap.json` | `captured` dari `masuk×0,95×V`; `potential`/`gap` = placeholder model (tugas pipeline BE) |

## Keputusan sadar yang sudah dikunci test — JANGAN diubah tanpa update test

- **Sudirman pagi TIDAK ada di `spending_gap`** — lewat-nya 0 (padat, tak terhitung) → tak diestimasi. (`test_sudirman_morning_is_absent`)
- **Sudirman evening gap** p10=900k, p90=1,6jt. (`test_build_context...`, `test_copilot_query_spending_gap`)
- **Kategori hilang Sudirman = {apotek_kesehatan, jasa}**. (`test_category_gap...`, `test_brief...`)
- **`manggarai-petak-05`** = petak kosong (rent_flow). (`test_explain_known_entity`)

## Catatan

- Sewa tenant in-station di `manggarai-instation.json` ber-flag `nilaikomersialvis:false` (KAI tak menampilkan publik) → untuk peta publik pakai petak KOSONG + pasar; nilai kontrak tenant untuk tier operator/agregat.
- Sudirman in-station tak ada di API KAI (verified by-coordinate) → Sudirman rent hanya dari `rent/sekitar.json` (pasar).
- `sekitar.json` belum masuk `rent_flow_index` (butuh keputusan denominator arus untuk titik pasar) — tersedia di sini bila mau dipakai.
- Regenerasi field data: `scripts/build_field_seed.js` (di root workspace `mapid/`); rent KAI via `space-api.kai.id/api/v1/komersialasetram`.

## Demand kategori (POI real) → `category_gap`

`demand/poi-demand-counts.json` = jumlah POI nyata dalam **800 m** tiap stasiun per kategori, ditarik dari **MAPID Data Premium** (POI Data Bumi/BPS) yang diimpor ke project GEO MAPID `6a7c39a75c1a774d47489a8b` (~13.000 POI Jakpus+Jaksel dipindai). Ini yang mengubah `category_gap.demand_in_area` dari asumsi jadi bukti, dan mengisi `demand_count` di `fixtures/category_gap.json`.

| Stasiun | makanan_minuman | ritel_kemasan | apotek_kesehatan | jasa |
|---|---|---|---|---|
| Manggarai | 21 | 4 | 13 | 55 |
| Sudirman | 30 | 20 | 4 | 71 |

`available_in_station` tetap dari survei lapangan (gerai di dalam), bukan dari POI ini → apotek & jasa = **hilang** (ada permintaan, 0 di dalam) di kedua stasiun. Method: `get_layer` paginated (skip/limit 200), haversine ≤ 800 m, dedup NAMA+koordinat.
