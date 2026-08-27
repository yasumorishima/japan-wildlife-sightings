#!/usr/bin/env python3
"""地図ページ用の軽量 GeoJSON を作る。

`data/sightings.csv`（収録対象＝再配布が許されている出典だけ）から、地図に要る
列だけを残して `docs/data/sightings.min.geojson` を書く。座標は 5 桁（約 1m）に
丸め、状況の文は 90 字で切る。転送は GitHub Pages の gzip で約 1.3MB。
"""
from __future__ import annotations

import csv
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent
SRC = ROOT / "data" / "sightings.csv"
OUT = ROOT / "docs" / "data" / "sightings.min.geojson"


def main() -> int:
    feats, skipped = [], 0
    with SRC.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if not r["lat"] or not r["lon"]:
                skipped += 1
                continue
            feats.append({
                "type": "Feature",
                "geometry": {"type": "Point",
                             "coordinates": [round(float(r["lon"]), 5), round(float(r["lat"]), 5)]},
                "properties": {
                    "d": (r["occurred_at"] or "")[:10],
                    "s": r["species"],
                    "c": r["category"],
                    "p": r["pref"],
                    "m": r["municipality"] or "",
                    "n": r["count"] or "",
                    "t": (r["note"] or "")[:90],
                    "a": r["attribution"] or "",
                },
            })
    feats.sort(key=lambda f: f["properties"]["d"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"type": "FeatureCollection", "features": feats},
                              ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    years = sorted({f["properties"]["d"][:4] for f in feats if f["properties"]["d"]})
    print(f"地図用 {len(feats)} 件 -> {OUT.relative_to(ROOT)} "
          f"({OUT.stat().st_size/1e6:.2f}MB, 座標なしで除いた {skipped} 件, "
          f"{years[0]}〜{years[-1]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
