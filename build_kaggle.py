#!/usr/bin/env python3
"""Kaggle に上げるファイル一式を _kaggle/ に作る。

data/ にある収録済みデータ（再配布が許されている出典だけ）をそのまま使う。
列の説明と CSV の見出しが食い違えば失敗するので、スキーマを変えたら COLUMNS も直すこと。

  python3 build_kaggle.py            # _kaggle/ を作る
"""
from __future__ import annotations

import collections
import csv
import gzip
import json
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent
DATA = ROOT / "data"
OUT = ROOT / "_kaggle"

COLUMNS = {
    "id": "Unique id: source_id, a colon, then the publisher's id or the row number",
    "pref_code": "Prefecture code (JIS X 0401, two digits)",
    "pref": "Prefecture name in Japanese",
    "occurred_at": "When the animal was seen, ISO 8601. YYYY-MM-DD when the source gives no time; empty when it gives no date",
    "species": "Normalised species: tsukinowaguma (Asian black bear), higuma (brown bear), inoshishi (wild boar), "
               "shika (sika deer), saru (Japanese macaque), kamoshika (Japanese serow), bear (bear, species not stated), unknown",
    "species_label": "Species name in Japanese",
    "category": "Normalised report type: sighting, trace (tracks, droppings), damage, injury (a person hurt), capture, unknown",
    "category_raw": "Report type as written by the publisher",
    "count": "Number of animals, when published",
    "municipality": "City, town or village",
    "place": "Place name or address as written by the publisher",
    "lat": "Latitude, WGS84; empty when the source has no coordinates",
    "lon": "Longitude, WGS84; empty when the source has no coordinates",
    "note": "The publisher's description of the situation (Japanese)",
    "source_id": "Source id (see attribution.csv)",
    "source_page": "Page of the publisher where the data comes from",
    "license": "Licence of the source",
    "attribution": "Name to credit when using the record",
}


def col_type(name: str) -> str:
    if name == "occurred_at":
        return "datetime"
    if name in ("lat", "lon"):
        return "number"
    if name == "count":
        return "integer"
    return "string"


def main() -> int:
    with (DATA / "sightings.csv").open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        header = reader.fieldnames
        rows = list(reader)
    if header != list(COLUMNS):
        print(f"sightings.csv の列 {header} と COLUMNS {list(COLUMNS)} が食い違う")
        return 1
    summary = json.loads((DATA / "summary.json").read_text(encoding="utf-8"))
    by_id = {s["id"]: s for s in summary["sources"]}

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    shutil.copy(DATA / "sightings.csv", OUT / "sightings.csv")
    shutil.copy(DATA / "summary.json", OUT / "summary.json")
    with gzip.open(DATA / "sightings.geojson.gz", "rb") as src, (OUT / "sightings.geojson").open("wb") as dst:
        shutil.copyfileobj(src, dst)

    # 出典ごとの表示（CC BY の帰属表示に使う）
    counts = collections.Counter(r["source_id"] for r in rows)
    first = {}
    for r in rows:
        first.setdefault(r["source_id"], r)
    attr = []
    for sid in sorted(counts, key=lambda s: (-counts[s], s)):
        r, s = first[sid], by_id.get(sid, {})
        attr.append({"source_id": sid, "pref": r["pref"], "attribution": r["attribution"],
                     "license": r["license"], "source_page": r["source_page"], "records": counts[sid],
                     "date_min": s.get("date_min") or "", "date_max": s.get("date_max") or ""})
    with (OUT / "attribution.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(attr[0]))
        w.writeheader()
        w.writerows(attr)

    dates = sorted(r["occurred_at"][:10] for r in rows if r["occurred_at"])
    table = ["| Source | Prefecture | Attribution | Licence | Records |", "|---|---|---|---|---:|"]
    table += [f"| [{a['source_id']}]({a['source_page']}) | {a['pref']} | {a['attribution']} | {a['license']} | {a['records']:,} |"
              for a in attr]
    desc = (ROOT / "kaggle" / "description.md").read_text(encoding="utf-8")
    for k, v in {"RECORDS": f"{len(rows):,}", "SOURCES": str(len(attr)),
                 "WITH_COORDS": f"{sum(1 for r in rows if r['lat']):,}",
                 "DATE_MIN": dates[0], "DATE_MAX": dates[-1],
                 "GENERATED": summary["generated_at"][:10], "SOURCE_TABLE": "\n".join(table),
                 "COLUMN_TABLE": "\n".join(["| Column | Description |", "|---|---|"]
                                           + [f"| `{c}` | {d} |" for c, d in COLUMNS.items()])}.items():
        desc = desc.replace("{" + k + "}", v)

    meta = json.loads((ROOT / "kaggle" / "dataset-metadata.json").read_text(encoding="utf-8"))
    meta["description"] = desc.strip()
    meta["resources"] = [
        {"path": "sightings.csv", "description": "One row per sighting, all published sources",
         "schema": {"fields": [{"name": c, "type": col_type(c), "description": d} for c, d in COLUMNS.items()]}},
        {"path": "sightings.geojson", "description": "Rows with coordinates as GeoJSON points (same properties as the CSV)"},
        {"path": "attribution.csv", "description": "Licence and attribution for each source"},
        {"path": "summary.json", "description": "Per-source counts and data quality of the last build"},
    ]
    (OUT / "dataset-metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"_kaggle/: {len(rows)} records, {len(attr)} sources, {dates[0]}..{dates[-1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
