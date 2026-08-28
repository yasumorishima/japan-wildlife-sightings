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
        lat, lon = normalize.in_japan(lat, lon)
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
        # 同じ出典が年度ごとに別データセットで公開されると通し番号が毎年 1 に戻る。
        # カタログ由来の行は _dataset を持つので、それで id を分ける。
        native_key = native if native not in (None, "") else i
        scope = row.get("_dataset_id") or row.get("_dataset")
        if scope and native not in (None, ""):
            native_key = f"{scope}:{native}"
        out.append({
            "id": f"{src['id']}:{native_key}",
            "pref_code": src["pref_code"], "pref": src["pref"],
            "occurred_at": occurred, "species": skey, "species_label": slabel,
            "category": ckey, "category_raw": craw,
            "count": int(count) if count else None,
            "municipality": (col("municipality") or None), "place": (col("place") or None),
            "lat": lat, "lon": lon, "note": (col("note") or None),
            "source_id": src["id"], "source_page": src.get("page"),
            "license": lic.get("id"), "attribution": lic.get("attribution"),
        })
        # 出典が単一の市町村ぶんしか持たない等、列に無い事実を設定側で補える
        for key, value in (src.get("constants") or {}).items():
            if not out[-1].get(key):
                out[-1][key] = value
        # 様式によっては行番号だけが入った空行が末尾に続く。設定側で「これが無い行は
        # 記録ではない」と宣言できるようにする（山口県は日付の無い行が空行）。
        if any(out[-1].get(k) in (None, "") for k in (src.get("require") or [])):
            out.pop()
    # 同じ記録が複数の資源に載る出典がある。石川県は 1 件の出没を要因ごとの表に
    # 重ねて載せるので 3,901 行が 2,701 件になり（1,200 行が重複）、金沢市は年度ごとに
    # 累積スナップショットを並べる（古い 696 行は新しい 754 行の部分集合）。
    # 何を同じ記録と見なすかは出典ごとに違うので設定で宣言する。
    if src.get("dedupe_by"):
        unknown = [c for c in src["dedupe_by"] if c not in FIELDS]
        if unknown:
            raise KeyError(f"{src['id']}: dedupe_by に無い列 {unknown}")
        # 先に来た行を残すと区分の重い記録が消える。石川県は同じ出没が「目撃」の表と
        # 「人身被害」の表の両方に載っており、先勝ちだと人身被害が 24 件から 15 件に減った。
        rank = {"injury": 0, "damage": 1, "capture": 2, "trace": 3, "sighting": 4, "unknown": 5}
        pos, uniq = {}, []
        for rec in out:
            key = tuple(rec.get(c) for c in src["dedupe_by"])
            if any(k is None or k == "" for k in key):
                # 鍵が欠けている行まで畳むと、無関係な記録が 1 件にまとまる
                uniq.append(rec)
                continue
            i = pos.get(key)
            if i is None:
                pos[key] = len(uniq)
                uniq.append(rec)
            elif rank.get(rec["category"], 9) < rank.get(uniq[i]["category"], 9):
                uniq[i] = rec
        out = uniq
    return out


def previous_rows(source_id: str) -> list[dict]:
    """前回 data/ に書いた行のうち、その出典ぶんを読み直す。

    公開元が実行元によっては届かないことがある（石川県のカタログは GitHub の
    runner の IP から 403、RPi5 からは 200）。届かない回に収録済みの行を消すと、
    公開しているデータセットから数千件が黙って落ちるので、前回ぶんを残す。
    """
    path = ROOT / "data" / "sightings.csv"
    if not path.exists():
        return []
    out = []
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row.get("source_id") != source_id:
                continue
            rec = {k: (v if v != "" else None) for k, v in row.items()}
            for key in ("lat", "lon"):
                rec[key] = float(rec[key]) if rec[key] is not None else None
            rec["count"] = int(float(rec["count"])) if rec["count"] is not None else None
            out.append(rec)
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
            if entry["redistribute"]:
                prev = previous_rows(src["id"])
                if prev:
                    entry["reused_previous"] = len(prev)
                    entry.update(quality(prev))
                    shareable.extend(prev)
                    print(f"[!!] {src['id']}: 取得できないので前回の {len(prev)} 件を"
                          f"そのまま残します（データは更新されていません）", file=sys.stderr)
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
