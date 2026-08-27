"""PDF の表を読む。点データを PDF でしか出していない県のためのアダプタ。

`pdftotext -layout` の出力を、桁揃えされた「1 行 1 件」として読む。
セルが複数行に折り返す様式（山梨など）はこの方法では読めない。読めなかった
PDF は 0 件を返すだけで、他の PDF の取得は続ける。
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import urllib.parse

import requests

UA = "japan-wildlife-sightings/0.1 (+https://github.com/yasumorishima/japan-wildlife-sightings)"
DATE = re.compile(r"^(?:\d{4}[/.]\d{1,2}[/.]\d{1,2}|[RHS]\d{1,2}[.]\d{1,2}[.]\d{1,2}|令和\d+年\d+月\d+日)$")
COUNT = re.compile(r"[0-9０-９一二三四五六七八九十]+\s*頭")
CATEGORY = re.compile(r"目撃|痕跡|被害|捕獲|出没")


def _pdftotext(data: bytes) -> str:
    if not shutil.which("pdftotext"):
        raise RuntimeError("pdftotext が無い（poppler-utils を入れてください）")
    with tempfile.NamedTemporaryFile(suffix=".pdf") as fh:
        fh.write(data)
        fh.flush()
        out = subprocess.run(["pdftotext", "-layout", fh.name, "-"],
                             capture_output=True, timeout=120)
    return out.stdout.decode("utf-8", "replace")


def parse_rows(text: str) -> list[dict]:
    """桁揃えの行から (日付, 市町村, 区分, 頭数, 状況) を拾う。"""
    rows = []
    for line in text.splitlines():
        cells = [c.strip() for c in re.split(r"\s{2,}", line.strip()) if c.strip()]
        if len(cells) < 3:
            continue
        # 先頭が連番なら落とす
        if cells and re.fullmatch(r"\d{1,4}", cells[0]):
            cells = cells[1:]
        if not cells or not DATE.match(cells[0]):
            continue
        row = {"日付": cells[0], "市町村": cells[1] if len(cells) > 1 else None}
        rest = cells[2:]
        row["区分"] = next((c for c in rest if CATEGORY.search(c) and len(c) <= 6), None)
        row["頭数"] = next((c for c in rest if COUNT.search(c)), None)
        # 状況は残りのうち最も長いもの（自由記述）
        row["環境"] = rest[0] if rest and rest[0] not in (row["区分"], row["頭数"]) else None
        # 状況は残りのうち最も長い自由記述。環境や区分と同じ語しか残らない場合は空。
        others = [c for c in rest
                  if c not in (row["区分"], row["頭数"], row["環境"])]
        row["状況"] = max(others, key=len) if others else None
        rows.append(row)
    return rows


def fetch_pdf_table(page_url: str, link_pattern: str = r"\.pdf$", **_) -> list[dict]:
    """ページから PDF を集めて表を読む。同じ出没が複数の月次 PDF に載るので重複を除く。"""
    sess = requests.Session()
    sess.headers["User-Agent"] = UA
    page = sess.get(page_url, timeout=60)
    page.raise_for_status()
    page.encoding = page.apparent_encoding or page.encoding
    links = sorted({urllib.parse.urljoin(page_url, h)
                    for h in re.findall(r'href="([^"]*\.pdf)"', page.text, re.I)
                    if re.search(link_pattern, urllib.parse.unquote(h))})
    seen, out = set(), []
    for url in links:
        try:
            body = sess.get(url, timeout=90).content
            if not body.startswith(b"%PDF"):
                continue
            rows = parse_rows(_pdftotext(body))
        except Exception:
            continue
        for row in rows:
            key = (row["日付"], row["市町村"], (row["状況"] or "")[:40])
            if key in seen:
                continue
            seen.add(key)
            row["_source_pdf"] = url
            out.append(row)
    return out
