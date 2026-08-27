"""セルが複数行に折り返す PDF の表を、文字の座標から組み直す。

`pdftotext -layout` は桁揃えのテキストしか出さないので、1 つのセルが 2 行に
折り返す様式（山梨など）では列がずれる。ここでは `-bbox-layout` の語ごとの
座標を使い、(1) 日付の語を 1 件の起点にして行を切り、(2) 語の左端を寄せて
列を作る。列の位置は決め打ちせず、そのページの語の分布から作る。
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile

WORD = re.compile(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>')
PAGE = re.compile(r"<page width=", re.I)
DATE_WORD = re.compile(r"^[RHS]\d{1,2}[.]\d{1,2}[.]\d{1,2}$")


def _bbox_xml(data: bytes) -> str:
    if not shutil.which("pdftotext"):
        raise RuntimeError("pdftotext が無い（poppler-utils を入れてください）")
    with tempfile.NamedTemporaryFile(suffix=".pdf") as fh:
        fh.write(data)
        fh.flush()
        out = subprocess.run(["pdftotext", "-bbox-layout", fh.name, "-"],
                             capture_output=True, timeout=300)
    return out.stdout.decode("utf-8", "replace")


def _pages(xml: str) -> list[list[tuple]]:
    """ページごとの語（xMin, yMin, xMax, yMax, text）に分ける。"""
    out = []
    for chunk in re.split(r"<page\b", xml)[1:]:
        words = [(float(a), float(b), float(c), float(d), t)
                 for a, b, c, d, t in WORD.findall(chunk) if t.strip()]
        if words:
            out.append(words)
    return out


def _columns(words: list[tuple], gap: float = 6.0) -> list[float]:
    """語の左端をまとめて列の左端を作る。決め打ちしないのでページ様式に追従する。"""
    lefts = sorted(w[0] for w in words)
    cols, cur = [], [lefts[0]]
    for x in lefts[1:]:
        if x - cur[-1] > gap:
            cols.append(min(cur))
            cur = [x]
        else:
            cur.append(x)
    cols.append(min(cur))
    return cols


def _assign(x: float, cols: list[float]) -> int:
    idx = 0
    for i, c in enumerate(cols):
        if x >= c - 1.0:
            idx = i
        else:
            break
    return idx


def _learn_centers(words, anchors, want=None):
    """1 ページ目の値の並びから列の左端を学ぶ。

    見出し行から列を作ろうとすると、1 件目の折り返し本文が見出しより上に来る様式で
    本文を巻き込む（実際に混ざった）。値の並びは折り返しがあっても列ごとに揃うので、
    そちらから学ぶほうが安定する。名前は出典側の設定で与える。
    """
    body = [w for w in words if w[1] >= anchors[0][1] - 6]
    if not body:
        return []

    # 隣り合う列の間隔は様式ごとに違う。想定の列数になる刻みを選ぶ（頭数と対応の
    # ように 5pt しか離れていない列があり、粗い刻みだと 1 列に融合する）。
    tries = [_columns(body, g) for g in (6.0, 4.5, 3.5, 2.5)]
    if want:
        exact = [c for c in tries if len(c) == want]
        if exact:
            return exact[0]
        return min(tries, key=lambda c: abs(len(c) - want))
    return tries[0]


def parse_bbox_table(xml: str, columns: list[str]) -> list[dict]:
    """日付の語を起点に 1 件ずつ切り出し、列ごとに折り返しをつなぐ。

    列の位置は最初のページで一度だけ学び、以降のページでも同じ位置を使う。
    ページごとに作り直すと、値が欠けたページで 1 列ずれる（実際にずれた）。
    """
    rows, centers, date_col = [], None, 1
    for words in _pages(xml):
        anchors = sorted([w for w in words if DATE_WORD.match(w[4])], key=lambda w: w[1])
        if not anchors:
            continue
        if centers is None:
            centers = _learn_centers(words, anchors, len(columns))
            if not centers:
                continue
            # 日付は本文中にも出る（「R8.6.1LINE通報…」）。日付らしい語が最も多く
            # 集まる列を日付欄とみなし、そこにある語だけを 1 件の起点にする。
            # これをしないと本文の日付から幽霊行ができる（実測 114 件）。
            from collections import Counter
            date_col = Counter(_assign(w[0], centers) for w in words
                               if DATE_WORD.match(w[4])).most_common(1)[0][0]
        anchors = [a for a in anchors if _assign(a[0], centers) == date_col]
        if not anchors:
            continue
        body = [w for w in words if w[1] >= anchors[0][1] - 6]
        bounds = [(a[1], anchors[i + 1][1] if i + 1 < len(anchors) else 1e9)
                  for i, a in enumerate(anchors)]
        for (top, bottom), anchor in zip(bounds, anchors):
            cells = {}
            for w in body:
                if not (top - 5 <= w[1] < bottom - 5):
                    continue
                # 値は左揃えなので、中心の近さではなく左端で列を決める。
                cells.setdefault(_assign(w[0], centers), []).append(w)
            row = {}
            for idx, ws in sorted(cells.items()):
                ws.sort(key=lambda w: (w[1], w[0]))
                key = columns[idx] if idx < len(columns) else f"col{idx}"
                row[key] = row.get(key, "") + "".join(w[4] for w in ws).strip()
            if row:
                row["_date_word"] = anchor[4]
                rows.append(row)
    return rows


# 山梨県の様式。列は左から順にこの見出しで並ぶ。
YAMANASHI_HEADERS = ["№", "目撃年月日", "時間", "目撃市町村", "場所", "天候",
                     "目撃時のクマ", "目撃時の目撃者の行動", "目撃した環境",
                     "人身被害の有無", "推定年齢", "目撃頭数", "その後の対応"]


def fetch_pdf_bbox(page_url: str, link_pattern: str, columns: list[str] | None = None,
                   **_) -> list[dict]:
    """ページから PDF を集め、座標つきで表を読む。"""
    import urllib.parse

    import requests

    sess = requests.Session()
    sess.headers["User-Agent"] = (
        "japan-wildlife-sightings/0.1 (+https://github.com/yasumorishima/japan-wildlife-sightings)")
    page = sess.get(page_url, timeout=60)
    page.raise_for_status()
    page.encoding = page.apparent_encoding or page.encoding
    links = sorted({urllib.parse.urljoin(page_url, h)
                    for h in re.findall(r'href="([^"]*\.pdf)"', page.text, re.I)
                    if re.search(link_pattern, urllib.parse.unquote(h))})
    cols = columns or YAMANASHI_HEADERS
    seen, out = set(), []
    for url in links:
        try:
            body = sess.get(url, timeout=120).content
            if not body.startswith(b"%PDF"):
                continue
            rows = parse_bbox_table(_bbox_xml(body), cols)
        except Exception:
            continue
        for row in rows:
            key = (row.get("目撃年月日") or row.get("_date_word"),
                   row.get("目撃市町村"), (row.get("場所") or "")[:20])
            if key in seen:
                continue
            seen.add(key)
            row["_source_pdf"] = url
            out.append(row)
    return out
