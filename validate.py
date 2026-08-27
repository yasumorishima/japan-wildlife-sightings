#!/usr/bin/env python3
"""生成物が壊れていないかを機械的に確かめる。CI からも実行する。

「ファイルが出来た」は中身が正しい証明にならないので、ここで数える。
"""
import collections
import gzip
import csv
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
DATA = ROOT / "data"
# 日本の陸域を含む緩い外接矩形（与那国島〜択捉島）
LAT_RANGE, LON_RANGE = (20.0, 46.5), (122.0, 154.0)


def main() -> int:
    fails = []
    rows = list(csv.DictReader((DATA / "sightings.csv").open(encoding="utf-8")))
    with gzip.open(DATA / "sightings.geojson.gz", "rt", encoding="utf-8") as fh:
        geo = json.load(fh)
    summary = json.loads((DATA / "summary.json").read_text(encoding="utf-8"))

    print(f"records={len(rows)} features={len(geo['features'])} sources={len(summary['sources'])}")
    if len(rows) != summary["records_published"]:
        fails.append(f"summary の件数 {summary['records_published']} と CSV {len(rows)} が食い違う")

    ids = collections.Counter(r["id"] for r in rows)
    dup = [k for k, v in ids.items() if v > 1]
    if dup:
        fails.append(f"id が重複: {len(dup)} 件 例 {dup[:3]}")

    out_of_range = 0
    for r in rows:
        try:
            lat, lon = float(r["lat"]), float(r["lon"])
        except (TypeError, ValueError):
            fails.append(f"座標が数値でない: {r['id']}")
            break
        if not (LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LON_RANGE[0] <= lon <= LON_RANGE[1]):
            out_of_range += 1
    if out_of_range:
        fails.append(f"日本の範囲外の座標: {out_of_range} 件")

    no_date = sum(1 for r in rows if not r["occurred_at"])
    print("日付なし:", no_date)
    if no_date > len(rows) * 0.05:
        fails.append(f"日付を解釈できない行が 5% を超えた: {no_date}/{len(rows)}")

    print("獣種:", dict(collections.Counter(r["species"] for r in rows).most_common()))
    print("出没区分:", dict(collections.Counter(r["category"] for r in rows).most_common(6)))
    print("都道府県:", dict(collections.Counter(r["pref"] for r in rows).most_common()))
    dates = sorted(r["occurred_at"][:10] for r in rows if r["occurred_at"])
    print("期間:", dates[0], "..", dates[-1])

    for s in summary["sources"]:
        if s.get("error"):
            fails.append(f"取得に失敗した出典: {s['id']} {s['error']}")
        if s.get("redistribute") and s.get("license") in (None, "unknown"):
            fails.append(f"ライセンス未確認なのに収録対象: {s['id']}")

    if fails:
        print("\nNG:")
        for f in fails:
            print(" -", f)
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
