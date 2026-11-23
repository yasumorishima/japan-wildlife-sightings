"""出典ごとに、実際に取りに行った URL と公開元の版（Last-Modified）、取得の段階で
取り込まなかった行の数と理由を控える。

collect.py が出典ごとに reset() し、取得後に entries() / drops() を summary.json に書く。
取得日・URL・版が違う件数どうしを同じ条件のものとして比べないため、また行を黙って捨てないため。
"""
from __future__ import annotations

import hashlib
from collections import Counter

_seen: dict[str, dict] = {}
_drops: Counter = Counter()
_checks: list[dict] = []


def reset() -> None:
    _seen.clear()
    _drops.clear()
    _checks.clear()


def drop(reason: str, n: int = 1) -> None:
    """取り込まなかった行を理由つきで数える。空行のように記録でないものは数えない。"""
    _drops[reason] += n


def drops() -> dict[str, int]:
    return dict(_drops)


def record(url: str, resp=None) -> None:
    """同じ URL は 1 回だけ載せる（ArcGIS のページ送りなど）。"""
    if not url or url in _seen:
        return
    entry = {"url": url}
    headers = getattr(resp, "headers", None) or {}
    if headers.get("Last-Modified"):
        entry["last_modified"] = headers["Last-Modified"]
    # ファイル（PDF・CSV・xlsx・zip 等）は中身の sha256 も控える。Last-Modified を返さない公開元や、
    # 同じファイル名で差し替える公開元でも、版が変わったかが分かる。HTML や API の応答は取得ごとに変わるので除く
    ctype = (headers.get("Content-Type") or "").lower()
    if resp is not None and not any(t in ctype for t in ("html", "json")):
        try:
            entry["sha256"] = hashlib.sha256(resp.content).hexdigest()
        except Exception:
            pass
    _seen[url] = entry


def check(entry: dict) -> None:
    """取得した 1 ファイルについて、別の手段で数えた件数と読めた件数の突き合わせを控える。"""
    _checks.append(entry)


def checks() -> list[dict]:
    return list(_checks)


def hook(resp, *args, **kwargs):
    """requests.Session の response フックとして使う（PDF の取得はセッションを自前で持つ）。"""
    record(resp.url, resp)


def entries() -> list[dict]:
    return list(_seen.values())
