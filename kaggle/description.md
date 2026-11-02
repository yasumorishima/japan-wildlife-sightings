Point records of **bear, wild boar, deer and monkey sightings** published by Japanese prefectures and cities, merged into one common schema. Rebuilt every day by GitHub Actions in [japan-wildlife-sightings](https://github.com/yasumorishima/japan-wildlife-sightings) from the original open data files (CKAN CSV and ArcGIS layers), and checked by `validate.py` before anything is published.

日本の自治体が公開しているクマ・イノシシ・シカ・サル等の出没情報を、共通スキーマの 1 枚にそろえたデータセットです。毎日 GitHub Actions で公開元から取り直しています。

**{RECORDS} records from {SOURCES} sources** ({WITH_COORDS} with coordinates), {DATE_MIN} to {DATE_MAX}. Last build: {GENERATED}.

Map: https://yasumorishima.github.io/japan-wildlife-sightings/

## Files

- `sightings.csv` — one row per sighting (UTF-8). Columns are described below.
- `sightings.geojson` — the same rows that have coordinates, as GeoJSON points (WGS84).
- `attribution.csv` — one row per source: licence, the attribution to show, the source page and the record count.
- `summary.json` — per-source counts, date range and data quality of the last build.

## Which sources are included

Only sources whose terms explicitly allow redistribution (CC BY 4.0, CC BY, or Japan's Public Data License 1.0, which is compatible with CC BY 4.0). Other prefectures publish sighting maps too, but their terms forbid or do not state redistribution, so they are not in this dataset; the repository ships the code to fetch them for your own use. The judgement for every source, with quotes from the terms, is in [docs/licenses.md](https://github.com/yasumorishima/japan-wildlife-sightings/blob/main/docs/licenses.md).

When a source cannot be reached on a given day (some block requests from outside Japan), the previous day's records for that source are kept, and `summary.json` says so.

{SOURCE_TABLE}

## Columns of sightings.csv

{COLUMN_TABLE}

## Licence and attribution

The data stays under each source's licence. When you use it, credit the sources named in the `attribution` column (or `attribution.csv`), for example: 「出典：秋田県、京都府、… のオープンデータを加工して作成」. The code is MIT.

## Caveats

- `occurred_at` is ISO 8601; sources without a time give `YYYY-MM-DD`, and some rows have no date.
- Three Kanazawa sources give only a town name, so `lat`/`lon` are empty.
- `species` and `category` are normalised; the publisher's original wording is kept in `species_label` / `category_raw`, and values that could not be classified are `unknown` rather than guessed.
- A sighting reported to more than one publisher can appear more than once.
