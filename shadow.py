#!/usr/bin/env python3
"""変更前と変更後のコードに同じ取得結果を読ませ、段ごとの違いを件数だけで出す。

  python3 shadow.py run --code . --cache C --out new.json [--only ID ...]
  python3 shadow.py run --code ../base --cache C --out old.json [--only ID ...]
  python3 shadow.py compare old.json new.json

考え方（Anthropic の「Messages API を Rust に移した」記事の確かめ方を借りた）:
- 正解は今動いているコード。テストが通るだけでは、実データでの振る舞いが同じとは言えない。
- 公開元へは 1 回だけ取りに行く。HTTP の応答を C に控え、2 回目以降の実行はそれを返す
  （同じ URL を何度取っても同じ中身になり、公開元にも負担を掛けない）。
- 取得行数 → 除外（理由別） → 読めず（理由別） → 件数 → id → 列 の順に比べ、最初にずれた段を出す。
- 行の中身は出さない。列ごとの値は短いハッシュにしてから比べ、出すのは「どの出典の・どの段の・
  何件」だけ（地名や番地を CI のログや PR に出さないため）。C の中身は公開元の生データなので、
  CI の成果物として上げない。
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import io
import json
import pathlib
import sys
from collections import Counter

STAGES = ["error", "fetched_rows", "dropped", "unparsed", "records", "ids", "fields"]


# ---- HTTP の応答を控えて返す -------------------------------------------------

def install_cache(cache: pathlib.Path):
    """requests の HTTPAdapter.send を差し替える。控えがあればそれを返し、無ければ取りに行って控える。

    同じ要求を同じ実行の中で 2 回出すこと（暗号を緩めてのやり直し等）があるので、
    要求ごとに応答を順に並べて控え、実行の中で何回目かで引く。
    """
    import requests
    from requests.adapters import HTTPAdapter
    from requests.structures import CaseInsensitiveDict
    from requests.utils import get_encoding_from_headers

    cache.mkdir(parents=True, exist_ok=True)
    original = HTTPAdapter.send
    seen = Counter()

    def key_of(request) -> str:
        body = request.body or b""
        if isinstance(body, str):
            body = body.encode()
        raw = f"{request.method} {request.url}\n".encode() + body
        return hashlib.sha256(raw).hexdigest()[:32]

    def build(request, meta: dict, content: bytes):
        if meta.get("error"):
            exc_type = getattr(requests.exceptions, meta["error"], requests.exceptions.ConnectionError)
            raise exc_type(f"控えた取得の失敗を再現: {meta['error']}", request=request)
        r = requests.Response()
        r.status_code = meta["status"]
        r.reason = meta.get("reason")
        r.headers = CaseInsensitiveDict(meta["headers"])
        r.url = meta["url"]
        r.encoding = get_encoding_from_headers(r.headers)
        r.request = request
        r.raw = io.BytesIO(content)
        r._content = content
        r._content_consumed = True
        return r

    def send(self, request, **kw):
        key = key_of(request)
        n = seen[key]
        seen[key] += 1
        stem = cache / f"{key}.{n}"
        meta_path = stem.with_suffix(stem.suffix + ".json")
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            body = stem.with_suffix(stem.suffix + ".bin")
            return build(request, meta, body.read_bytes() if body.exists() else b"")
        try:
            r = original(self, request, **kw)
            content = r.content  # stream=True でもここで読み切って控える
        except requests.exceptions.RequestException as exc:
            meta_path.write_text(json.dumps({"error": type(exc).__name__}), encoding="utf-8")
            raise
        stem.with_suffix(stem.suffix + ".bin").write_bytes(content)
        meta_path.write_text(json.dumps({
            "status": r.status_code, "reason": r.reason, "url": r.url,
            "headers": dict(r.headers)}, ensure_ascii=False), encoding="utf-8")
        return build(request, json.loads(meta_path.read_text(encoding="utf-8")), content)

    HTTPAdapter.send = send
    return original  # 戻すとき用（テスト）


# ---- 1 つの版のコードで全出典を通す ------------------------------------------

def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, default=str).encode()).hexdigest()[:12]


def run(code: pathlib.Path, cache: pathlib.Path, only: list[str] | None) -> dict:
    sys.path.insert(0, str(code.resolve()))
    install_cache(cache)
    import collect  # noqa: E402  --code の版を読む
    try:
        from collectors import fetchlog
    except ImportError:  # 取得の記録を持たない古い版
        fetchlog = None
    from collectors.adapters import ADAPTERS

    cfg = json.loads((code / "sources.json").read_text(encoding="utf-8"))
    out = {}
    for src in cfg["sources"]:
        if (only and src["id"] not in only) or src.get("frozen"):
            continue
        if fetchlog:
            fetchlog.reset()
        stats = Counter()
        res = {}
        try:
            rows = ADAPTERS[src["adapter"]](**src["params"])
            if "stats" in inspect.signature(collect.build).parameters:
                recs = collect.build(rows, src, stats)
            else:  # 数え上げを持たない古い版
                recs = collect.build(rows, src)
        except Exception as exc:  # noqa: BLE001  失敗も段の 1 つとして比べる
            out[src["id"]] = {"error": type(exc).__name__}
            print(f"[NG] {src['id']}: {type(exc).__name__}", file=sys.stderr)
            continue
        drops = Counter(fetchlog.drops()) if fetchlog else Counter()
        drops.update({k.split(":", 1)[1]: v for k, v in stats.items() if k.startswith("dropped:") and v})
        res["error"] = None
        res["fetched_rows"] = len(rows)
        res["dropped"] = dict(sorted(drops.items()))
        res["unparsed"] = {k.split(":", 1)[1]: v for k, v in sorted(stats.items())
                           if k.startswith("unparsed:") and v}
        res["records"] = len(recs)
        # id が重なる出典もあるので、id ごとに並べて持つ
        fields = {}
        for r in recs:
            fields.setdefault(r["id"], []).append({k: digest(v) for k, v in r.items()})
        res["fields"] = fields
        out[src["id"]] = res
        print(f"[ok] {src['id']:<24} rows={len(rows)} recs={len(recs)}", file=sys.stderr)
    return out


# ---- 2 つの結果を比べる ------------------------------------------------------

def compare(old: dict, new: dict) -> list[dict]:
    """出典ごとに、ずれた段と件数を返す。値そのものは返さない。"""
    diffs = []
    for sid in sorted(set(old) | set(new)):
        a, b = old.get(sid), new.get(sid)
        if a is None or b is None:
            diffs.append({"source": sid, "stage": "source", "detail": "旧のみ" if b is None else "新のみ"})
            continue
        found = []
        if a.get("error") != b.get("error"):
            found.append(("error", f"{a.get('error')} → {b.get('error')}"))
        if not (a.get("error") or b.get("error")):
            if a["fetched_rows"] != b["fetched_rows"]:
                found.append(("fetched_rows", f"{a['fetched_rows']} → {b['fetched_rows']}"))
            for stage in ("dropped", "unparsed"):
                for reason in sorted(set(a[stage]) | set(b[stage])):
                    x, y = a[stage].get(reason, 0), b[stage].get(reason, 0)
                    if x != y:
                        found.append((stage, f"{reason}: {x} → {y}"))
            if a["records"] != b["records"]:
                found.append(("records", f"{a['records']} → {b['records']}"))
            fa, fb = a["fields"], b["fields"]
            only_old = sum(len(fa[i]) for i in set(fa) - set(fb))
            only_new = sum(len(fb[i]) for i in set(fb) - set(fa))
            if only_old or only_new:
                found.append(("ids", f"旧のみ {only_old} 行 / 新のみ {only_new} 行"))
            changed = Counter()
            for i in set(fa) & set(fb):
                for ra, rb in zip(fa[i], fb[i]):
                    for k in sorted(set(ra) | set(rb)):
                        if ra.get(k) != rb.get(k):
                            changed[k] += 1
            for k, n in sorted(changed.items()):
                found.append(("fields", f"{k}: {n} 行"))
        if found:
            first = min(found, key=lambda f: STAGES.index(f[0]))[0]
            for stage, detail in found:
                diffs.append({"source": sid, "stage": stage, "detail": detail, "first": stage == first})
    return diffs


def report(diffs: list[dict]) -> str:
    if not diffs:
        return "変更前と変更後で、全出典の取得行数・除外・読めず・件数・id・列の値が一致しました。\n"
    lines = ["| 出典 | 段 | 違い |", "|---|---|---|"]
    for d in diffs:
        mark = " (最初のずれ)" if d.get("first") else ""
        lines.append(f"| {d['source']} | {d['stage']}{mark} | {d['detail']} |")
    sources = len({d["source"] for d in diffs})
    return (f"変更前と変更後で {sources} 出典に違いがあります。意図した変更かを確かめてください。"
            "値そのものは出していません（件数だけ）。\n\n" + "\n".join(lines) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--code", type=pathlib.Path, required=True)
    r.add_argument("--cache", type=pathlib.Path, required=True)
    r.add_argument("--out", type=pathlib.Path, required=True)
    r.add_argument("--only", action="append", default=None)
    c = sub.add_parser("compare")
    c.add_argument("old", type=pathlib.Path)
    c.add_argument("new", type=pathlib.Path)
    c.add_argument("--fail-on-diff", action="store_true")
    args = ap.parse_args()
    if args.cmd == "run":
        args.out.write_text(json.dumps(run(args.code, args.cache, args.only), ensure_ascii=False),
                            encoding="utf-8")
        return 0
    diffs = compare(json.loads(args.old.read_text(encoding="utf-8")),
                    json.loads(args.new.read_text(encoding="utf-8")))
    print(report(diffs))
    return 1 if diffs and args.fail_on_diff else 0


if __name__ == "__main__":
    raise SystemExit(main())
