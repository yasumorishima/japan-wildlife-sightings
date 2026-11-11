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
META = ROOT / "docs" / "data" / "meta.json"
_ANIMAL = {"tsukinowaguma": "クマ", "higuma": "ヒグマ", "bear": "クマ", "inoshishi": "イノシシ",
           "shika": "シカ", "saru": "サル", "kamoshika": "カモシカ"}


def write_meta() -> None:
    """地図に出す鮮度の情報（作った日時と、収録している出典ごとの最新の記録・状態）。

    出典の一覧を地図ページに手書きすると、出典を足し引きするたびに直し漏れが出るので、
    summary.json と sources.json から作る。
    """
    summary = json.loads((ROOT / "data" / "summary.json").read_text(encoding="utf-8"))
    cfg = {s["id"]: s for s in json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))["sources"]}
    out = []
    for e in summary["sources"]:
        src = cfg.get(e["id"])
        if not src or not e.get("redistribute") or not e.get("records"):
            continue
        # 名前は市町村名（定数か、市町村の帰属表示）か、県名
        attribution = (src.get("license") or {}).get("attribution") or ""
        place = ((src.get("constants") or {}).get("municipality")
                 or (attribution if attribution.endswith(("市", "町", "村")) else None) or src["pref"])
        animal = _ANIMAL.get(src.get("species_default") or "")
        if e.get("frozen"):
            status, since = "frozen", e["frozen"].get("fetched")
        elif e.get("reused_previous"):
            status, since = "stale", (e.get("failing_since") or "")[:10]
        else:
            status, since = "ok", (e.get("last_success_at") or summary["generated_at"])[:10]
        out.append({"label": f"{place}（{animal}）" if animal else place, "pref_code": src["pref_code"],
                    "records": e["records"], "latest": e.get("date_max"), "status": status, "since": since})
    out.sort(key=lambda x: (x["pref_code"], x["label"]))
    META.write_text(json.dumps({"generated_at": summary["generated_at"][:16], "sources": out},
                               ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


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
    OUT.parent.mkdir(parents=True, exist_ok=True)
    # 1 地物を 1 行で書く。全体が 1 行だと、数件の変化でも git が差分を取りにくく、毎日大きく積まれる
    feats.sort(key=lambda f: (f["properties"]["d"], f["geometry"]["coordinates"]))
    body = ",\n".join(json.dumps(f, ensure_ascii=False, separators=(",", ":")) for f in feats)
    OUT.write_text('{"type":"FeatureCollection","features":[\n' + body + "\n]}\n", encoding="utf-8")
    write_meta()
    years = sorted({f["properties"]["d"][:4] for f in feats if f["properties"]["d"]})
    print(f"地図用 {len(feats)} 件 -> {OUT.relative_to(ROOT)} "
          f"({OUT.stat().st_size/1e6:.2f}MB, 座標なしで除いた {skipped} 件, "
          f"{years[0]}〜{years[-1]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
