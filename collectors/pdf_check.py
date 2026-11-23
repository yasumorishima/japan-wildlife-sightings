"""PDF の表読みを、別の手段で数えた件数と突き合わせる。

表の読み手（pdf_table の桁揃え読み、pdf_bbox の座標読み）とは別に、`pdftotext -layout` の
テキスト層から「行の頭のほうに日付がある行」を数え、これを 1 ファイルの正解の件数とみなす。
読み手の件数がこれと食い違うファイルは、どの行が正しいか分からないので推測で混ぜず、
ファイルごと保留する（document-extraction-lab の「読めないページは ? として保留し、数を出す」と同じ考え方）。
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile

# 西暦（2025/8/1、2025.8.1）、和暦の略記（R7.4.1、H28.4.20）、令和7年4月1日
# 数字は半角だけ見る。本文の「令和７年９月８日」（全角）を行の起点と数えないため
DATE = re.compile(r"(?<![0-9.])(?:[0-9]{4}[/.][0-9]{1,2}[/.][0-9]{1,2}|[RHS][0-9]{1,2}[.][0-9]{1,2}[.][0-9]{1,2}"
                  r"|令和[0-9]+年[0-9]+月[0-9]+日)(?![0-9])")
# 日付より前に来てよいセルの数（連番・地域・環境）。本文中の日付を行の起点と数えないため
LEAD_CELLS = 3
# 日付の書き出しがこの桁より右にある行は本文の折り返しとみなす（山梨県の「R8.6.1 LINE通報…」は 94 桁目）
LEAD_COLUMN = 40
# 食い違いの許し幅。本文の折り返しに日付が来る等で数件ずれることがある
TOLERANCE_ABS = 2
TOLERANCE_REL = 0.02


def layout_text(data: bytes) -> str:
    if not shutil.which("pdftotext"):
        raise RuntimeError("pdftotext が無い（poppler-utils を入れてください）")
    with tempfile.NamedTemporaryFile(suffix=".pdf") as fh:
        fh.write(data)
        fh.flush()
        out = subprocess.run(["pdftotext", "-layout", fh.name, "-"],
                             capture_output=True, timeout=300)
    return out.stdout.decode("utf-8", "replace")


def expected_rows(text: str) -> int:
    """日付が行の頭のほう（先頭から LEAD_CELLS セル以内、LEAD_COLUMN 桁以内）にある行を数える。"""
    n = 0
    for line in text.splitlines():
        m = DATE.search(line)
        if not m:
            continue
        before = line[:m.start()].split()
        if len(before) <= LEAD_CELLS and m.start() <= LEAD_COLUMN:
            n += 1
    return n


def judge(rows: int, expected: int) -> str:
    """ok: 件数が合う / no_table: 表が無い（地図だけの PDF 等）/ held: 食い違うので保留。"""
    if expected == 0 and rows == 0:
        return "no_table"
    if abs(rows - expected) <= max(TOLERANCE_ABS, expected * TOLERANCE_REL):
        return "ok"
    return "held"
