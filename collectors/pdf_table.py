"""PDF の表を読む。点データを PDF でしか出していない県のためのアダプタ。

`pdftotext -layout` の出力を、桁揃えされた「1 行 1 件」として読む。
セルが複数行に折り返す様式（山梨など）はこの方法では読めない（pdf_bbox を使う）。
PDF ごとにテキスト層の件数と突き合わせ（pdf_check）、食い違う PDF は保留して summary に残す。
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import urllib.parse

import requests

from . import fetchlog, pdf_check

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
    """桁揃えの行から (日付, 市町村, 区分, 頭数, 状況) を拾う。

    長野県は 2 つの様式がある。
    A: 連番・日付・市町村・環境・区分・年齢・頭数・状況（日付が先頭）
    B: 連番・地域・環境・日付・市町村・地区・場所と状況（令和7年度の前半。日付が 3 つ目）
    """
    rows = []
    for line in text.splitlines():
        cells = [c.strip() for c in re.split(r"\s{2,}", line.strip()) if c.strip()]
        if len(cells) < 3:
            continue
        # 先頭が連番なら落とす
        if cells and re.fullmatch(r"\d{1,4}", cells[0]):
            cells = cells[1:]
        # 日付と次のセルが空白 1 つでつながることがある（「2026/5/1 中川村」）
        for i, c in enumerate(cells[:3]):
            m = re.match(r"(\S+)\s+(\S.*)$", c)
            if m and DATE.match(m.group(1)):
                cells[i:i + 1] = [m.group(1), m.group(2)]
                break
        # 様式 B で地域と環境が空白 1 つでつながることがある（「北アルプス 里地」）
        if len(cells) > 2 and DATE.match(cells[1]) and len(cells[0].split()) == 2:
            cells[0:1] = cells[0].split()
        if not cells:
            continue
        if DATE.match(cells[0]):
            row = {"日付": cells[0], "市町村": cells[1] if len(cells) > 1 else None}
            rest = cells[2:]
            row["区分"] = next((c for c in rest if CATEGORY.search(c) and len(c) <= 6), None)
            row["頭数"] = next((c for c in rest if COUNT.search(c)), None)
            row["環境"] = rest[0] if rest and rest[0] not in (row["区分"], row["頭数"]) else None
        elif len(cells) > 3 and DATE.match(cells[2]):
            row = {"日付": cells[2], "市町村": cells[3], "環境": cells[1], "区分": None}
            rest = cells[4:]
            # この様式は頭数が自由記述に混ざる（「林内にて１頭出没」）。頭数の部分だけを採る
            m = next((COUNT.search(c) for c in rest if COUNT.search(c)), None)
            row["頭数"] = m.group(0) if m else None
        else:
            continue
        # 状況は残りのうち最も長い自由記述。環境や区分と同じ語しか残らない場合は空。
        others = [c for c in rest
                  if c not in (row["区分"], row["頭数"], row["環境"])]
        row["状況"] = max(others, key=len) if others else None
        rows.append(row)
    return rows


def fetch_pdf_table(page_url: str, link_pattern: str = r"\.pdf$", **_) -> list[dict]:
    """ページから PDF を集めて表を読む。同じ出没が複数の月次 PDF に載るので重複を除く。"""
    sess = requests.Session()
    sess.hooks["response"].append(fetchlog.hook)
    sess.headers["User-Agent"] = UA
    page = sess.get(page_url, timeout=60)
    page.raise_for_status()
    page.encoding = page.apparent_encoding or page.encoding
    links = sorted({urllib.parse.urljoin(page_url, h)
                    for h in re.findall(r'href="([^"]*\.pdf)"', page.text, re.I)
                    if re.search(link_pattern, urllib.parse.unquote(h))})
    out = []
    for url in links:
        rows = read_pdf(sess, url, lambda body: parse_rows(_pdftotext(body)))
        for row in rows:
            row["_source_pdf"] = url
        out.extend(rows)
    return drop_repeats(out, lambda r: (r["日付"], r["市町村"], (r["状況"] or "")[:40]))


def drop_repeats(rows: list[dict], key) -> list[dict]:
    """前の PDF に載っていた記録を落とす（月次の PDF が前月までの分を重ねて載せる長野県など）。

    同じ PDF の中では畳まない。同じ日・同じ市町村・同じ場所の別の目撃が実際にあり、
    畳むと山梨県では年度の件数が CSV 版より少なくなった（実測）。
    """
    earlier, out, current, url = set(), [], set(), None
    for row in rows:
        if row["_source_pdf"] != url:
            earlier |= current
            current, url = set(), row["_source_pdf"]
        k = key(row)
        current.add(k)
        if k in earlier:
            fetchlog.drop("duplicate_across_pdfs")
            continue
        out.append(row)
    return out


def read_pdf(sess, url: str, parse) -> list[dict]:
    """1 本の PDF を読み、テキスト層の件数と突き合わせる。食い違えば保留して 0 件を返す。

    読めなかった・PDF でなかった・保留した、はどれも黙って捨てず summary に残す。
    """
    check = {"url": url}
    try:
        body = sess.get(url, timeout=120).content
        if not body.startswith(b"%PDF"):
            check["status"] = "not_pdf"
            fetchlog.check(check)
            return []
        rows = parse(body)
        expected = pdf_check.expected_rows(pdf_check.layout_text(body))
    except Exception as exc:
        check.update(status="unreadable", error=f"{type(exc).__name__}: {exc}"[:200])
        fetchlog.check(check)
        return []
    check.update(expected=expected, rows=len(rows), status=pdf_check.judge(len(rows), expected))
    fetchlog.check(check)
    if check["status"] == "held":
        fetchlog.drop("pdf_file_held", len(rows))
        return []
    return rows
