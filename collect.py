#!/usr/bin/env python3
"""公開元から取得して、共通スキーマの 1 枚のデータセットに正規化する。

  python3 collect.py                 # 全出典
  python3 collect.py --only akita-kumadas
  python3 collect.py --no-write      # 取得と検算だけ

data/ に収録するのは license.redistribute が true の出典のみ。
それ以外は件数と品質だけ summary.json に載せる（アダプタは同梱する）。
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip

import json
import pathlib
import sys

from collectors import normalize
from collectors.adapters import ADAPTERS

ROOT = pathlib.Path(__file__).resolve().parent
FIELDS = ["id", "pref_code", "pref", "occurred_at", "species", "species_label",
          "category", "category_raw", "count", "municipality", "place", "lat", "lon",
          "note", "source_id", "source_page", "license", "attribution"]


def _num(v):
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", "").strip())
    except ValueError:
        return None


def build(rows: list[dict], src: dict) -> list[dict]:
    m = src.get("map", {})
    lic = src.get("license", {})
    out = []
    for i, row in enumerate(rows):
        def col(key):
            """map の値は列名 1 つでも候補リストでもよい。最初に値がある列を採る。"""
            names = m.get(key)
            if not names:
                return None
            for name in ([names] if isinstance(names, str) else names):
                v = row.get(name)
                if v not in (None, ""):
                    return v
            return None

        lat = row.get("_lat", None)
        lon = row.get("_lon", None)
        if lat is None:
            lat, lon = _num(col("lat")), _num(col("lon"))
        # 日付は候補列を順に試し、最初に解釈できたものを採る（同じ地図の中で
        # 層ごとに書式が違う出典があるため）。
        occurred = None
        names = m.get("occurred_at") or []
        for name in ([names] if isinstance(names, str) else names):
            occurred = normalize.occurred_at(row.get(name), col("time"),
                                             src.get("fiscal_year"))
            if occurred:
                break
        skey, slabel = normalize.species(col("species"), src.get("species_default"))
        ckey, craw = normalize.category(col("category"))
        # 出没区分の列を持たない出典（そもそも目撃情報だけを載せている等）は
        # 設定側で既定値を宣言できる。列から読めた場合はそちらを優先する。
        if ckey == "unknown" and src.get("category_default"):
            ckey = src["category_default"]
        if src.get("count_sum"):
            parts = [_num(row.get(c)) for c in src["count_sum"]]
            count = sum(p for p in parts if p) or None
        else:
            count = _num(col("count"))
        native = col("native_id")
        out.append({
            "id": f"{src['id']}:{native if native not in (None, '') else i}",
            "pref_code": src["pref_code"], "pref": src["pref"],
            "occurred_at": occurred, "species": skey, "species_label": slabel,
            "category": ckey, "category_raw": craw,
            "count": int(count) if count else None,
            "municipality": (col("municipality") or None), "place": (col("place") or None),
            "lat": lat, "lon": lon, "note": (col("note") or None),
            "source_id": src["id"], "source_page": src.get("page"),
            "license": lic.get("id"), "attribution": lic.get("attribution"),
        })
    return out


def quality(recs: list[dict]) -> dict:
    dates = sorted(r["occurred_at"][:10] for r in recs if r["occurred_at"])
    return {
        "records": len(recs),
        "with_coords": sum(1 for r in recs if r["lat"] is not None and r["lon"] is not None),
        "with_date": len(dates),
        "date_min": dates[0] if dates else None,
        "date_max": dates[-1] if dates else None,
        "species": sorted({r["species"] for r in recs}),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", action="append", default=None, help="出典 id を指定（複数可）")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()

    cfg = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))
    summary, shareable = [], []
    for src in cfg["sources"]:
        if args.only and src["id"] not in args.only:
            continue
        entry = {"id": src["id"], "pref": src["pref"], "adapter": src["adapter"],
                 "license": src["license"].get("id"),
                 "redistribute": bool(src["license"].get("redistribute"))}
        try:
            rows = ADAPTERS[src["adapter"]](**src["params"])
            recs = build(rows, src)
        except Exception as exc:  # 1 出典の失敗で全体を落とさない
            entry["error"] = f"{type(exc).__name__}: {exc}"
            summary.append(entry)
            print(f"[NG] {src['id']}: {entry['error']}", file=sys.stderr)
            continue
        entry.update(quality(recs))
        summary.append(entry)
        if entry["redistribute"]:
            shareable.extend(recs)
        print(f"[ok] {src['id']:<24} n={entry['records']:>6} 座標={entry['with_coords']:>6} "
              f"日付={entry['with_date']:>6} {entry['date_min']}..{entry['date_max']} "
              f"{'収録' if entry['redistribute'] else '収録しない(ライセンス未確認)'}")

    if args.no_write:
        return 0

    data = ROOT / "data"
    data.mkdir(exist_ok=True)
    shareable.sort(key=lambda r: (r["occurred_at"] or "", r["id"]))
    with (data / "sightings.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(shareable)
    geo = {"type": "FeatureCollection", "features": [
        {"type": "Feature",
         "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
         "properties": {k: v for k, v in r.items() if k not in ("lat", "lon")}}
        for r in shareable if r["lat"] is not None and r["lon"] is not None]}
    # GeoJSON は非圧縮で 20MB を超え、日次で履歴に積むと取り回せなくなるので gzip で置く。
    # mtime=0 で書く。既定だと実行時刻が gzip ヘッダに入り、中身が同じでも
    # 毎回バイト列が変わって 2MB の差分が履歴に積まれる。
    with (data / "sightings.geojson.gz").open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
            gz.write(json.dumps(geo, ensure_ascii=False).encode("utf-8"))
    (data / "summary.json").write_text(json.dumps(
        {"generated_at": dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat(),
         "records_published": len(shareable), "sources": summary},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n収録 {len(shareable)} 件 / 地物 {len(geo['features'])} 件 -> data/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
