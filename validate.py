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
# 日本の陸域を含む緩い外接矩形。収録側と同じ定数を読む（別々に持つと、
# collect.py は通すのに validate.py が落とす値ができる）。
from collectors.normalize import JP_LAT as LAT_RANGE, JP_LON as LON_RANGE  # noqa: E402


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

    # 収録している出典の取得失敗は data/ の中身が古くなるので失敗にする。
    # 収録していない出典（アダプタだけ配っている県）の失敗は警告に留める。
    # 公開元のサイトは実行元によって届かないことがあり（2026-08-27: 山梨県は
    # GitHub の runner から接続タイムアウト、RPi5 からは応答あり）、1 県のために
    # 日次の更新ごと止めるのは割に合わない。
    warned = 0
    for s in summary["sources"]:
        if s.get("error"):
            if s.get("redistribute"):
                fails.append(f"収録対象の取得に失敗: {s['id']} {s['error']}")
            else:
                warned += 1
                print(f"警告: 取得できなかった出典（収録対象外）: {s['id']} {s['error'][:120]}")
        if s.get("redistribute") and s.get("license") in (None, "unknown"):
            fails.append(f"ライセンス未確認なのに収録対象: {s['id']}")
    if warned:
        print(f"警告 {warned} 件（収録対象外の出典が取れませんでした）")
    if warned > len(summary["sources"]) // 2:
        fails.append(f"取れなかった出典が多すぎます: {warned}/{len(summary['sources'])}")

    if fails:
        print("\nNG:")
        for f in fails:
            print(" -", f)
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
