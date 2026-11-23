"""PDF の表読みと、その突き合わせ（pdf_check）のテスト。通信しない。地名・本文は架空。

突き合わせの仕組みそのものを、正解の分かっている変化（行を消す・本文に日付を足す・
様式を変える）を注入して確かめる。数えるべきものを、ちょうどその数だけ数えるか。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collectors import fetchlog, pdf_bbox, pdf_check, pdf_table  # noqa: E402

# 様式 A（日付が先頭）の 5 件
ROWS_A = [f"{i}      2026/5/{i} 架空村      林内      目撃       成獣      １頭   山へ移動"
          for i in range(1, 6)]
# 様式 B（地域・環境の後に日付）の 3 件
ROWS_B = [f"{i}    北部     里地   2025/06/0{i}    架空町    架空地区   架空峠付近 成獣{i}頭"
          for i in range(1, 4)]


class ExpectedRowsTest(unittest.TestCase):
    def test_counts_rows_exactly(self):
        self.assertEqual(pdf_check.expected_rows("\n".join(ROWS_A)), 5)
        self.assertEqual(pdf_check.expected_rows("\n".join(ROWS_B)), 3)

    def test_deleted_rows_are_counted(self):
        text = "\n".join(ROWS_A[:2] + ROWS_A[4:])
        self.assertEqual(pdf_check.expected_rows(text), 3)

    def test_body_dates_are_not_rows(self):
        noise = [
            " " * 50 + "れた。（令和７年９月８日 ６時３０分頃）",  # 全角の日付
            " " * 94 + "R8.6.1 LINE通報システム",                   # 右に寄った本文
            "見出し 注記 補足 説明 2026/5/1 までの集計",              # 日付の前にセルが多い
        ]
        text = "\n".join(ROWS_A[:2] + noise + ROWS_A[2:])
        self.assertEqual(pdf_check.expected_rows(text), 5)

    def test_judge(self):
        self.assertEqual(pdf_check.judge(0, 0), "no_table")
        self.assertEqual(pdf_check.judge(100, 100), "ok")
        self.assertEqual(pdf_check.judge(98, 100), "ok")       # 許し幅（2 件）
        self.assertEqual(pdf_check.judge(0, 46), "held")       # 様式を読めなかった
        self.assertEqual(pdf_check.judge(150, 100), "held")    # 幽霊行


class ParseRowsTest(unittest.TestCase):
    def test_both_layouts_match_expected(self):
        for rows in (ROWS_A, ROWS_B):
            text = "\n".join(rows)
            self.assertEqual(len(pdf_table.parse_rows(text)), pdf_check.expected_rows(text))

    def test_layout_b_fields(self):
        row = pdf_table.parse_rows(ROWS_B[1])[0]
        self.assertEqual((row["日付"], row["市町村"], row["環境"], row["頭数"]),
                         ("2025/06/02", "架空町", "里地", "2頭"))

    def test_single_space_joins(self):
        a = pdf_table.parse_rows("1      2026/5/1 架空村      林内      目撃       不明      １頭")[0]
        self.assertEqual((a["日付"], a["市町村"]), ("2026/5/1", "架空村"))
        b = pdf_table.parse_rows("3   北部 里地     2025/07/27   架空町    架空地区 クマ1頭の目撃")[0]
        self.assertEqual((b["日付"], b["市町村"], b["環境"]), ("2025/07/27", "架空町", "里地"))


class DropRepeatsTest(unittest.TestCase):
    def test_only_repeats_from_earlier_pdfs(self):
        fetchlog.reset()
        rows = [{"k": 1, "_source_pdf": "a"}, {"k": 1, "_source_pdf": "a"},  # 同じ PDF 内は残す
                {"k": 1, "_source_pdf": "b"}, {"k": 2, "_source_pdf": "b"}]
        out = pdf_table.drop_repeats(rows, lambda r: r["k"])
        self.assertEqual(len(out), 3)
        self.assertEqual(fetchlog.drops(), {"duplicate_across_pdfs": 1})


class _Resp:
    def __init__(self, content):
        self.content = content


class _Sess:
    def __init__(self, content):
        self._c = content

    def get(self, url, timeout=None):
        return _Resp(self._c)


class ReadPdfTest(unittest.TestCase):
    def setUp(self):
        fetchlog.reset()
        self._orig = pdf_check.layout_text
        pdf_check.layout_text = lambda body: body.decode("utf-8")[4:]

    def tearDown(self):
        pdf_check.layout_text = self._orig

    def test_ok_file_is_kept(self):
        body = ("%PDF" + "\n".join(ROWS_A)).encode()
        rows = pdf_table.read_pdf(_Sess(body), "u", lambda b: pdf_table.parse_rows(b.decode()[4:]))
        self.assertEqual(len(rows), 5)
        self.assertEqual(fetchlog.checks()[0]["status"], "ok")

    def test_mismatching_file_is_held_and_counted(self):
        body = ("%PDF" + "\n".join(ROWS_A)).encode()
        rows = pdf_table.read_pdf(_Sess(body), "u", lambda b: [{"x": 1}])  # 読み手が 1 件しか返さない
        self.assertEqual(rows, [])
        self.assertEqual(fetchlog.checks()[0], {"url": "u", "expected": 5, "rows": 1, "status": "held"})
        self.assertEqual(fetchlog.drops(), {"pdf_file_held": 1})

    def test_not_pdf_and_unreadable_are_recorded(self):
        pdf_table.read_pdf(_Sess(b"<html>"), "u1", lambda b: [])
        pdf_table.read_pdf(_Sess(b"%PDF"), "u2", lambda b: 1 / 0)
        self.assertEqual([c["status"] for c in fetchlog.checks()], ["not_pdf", "unreadable"])


def _word(x, y, text, w=None):
    w = w if w is not None else 4.0 * len(text)
    return f'<word xMin="{x}" yMin="{y}" xMax="{x + w}" yMax="{y + 8}">{text}</word>'


class BboxTest(unittest.TestCase):
    def test_centered_long_dates_do_not_merge_rows(self):
        cols = ["№", "目撃年月日", "時間", "目撃市町村"]
        page1 = [_word(60, 100, "1"), _word(89, 100, "R7.4.1", 24), _word(130, 100, "9:00"),
                 _word(170, 100, "架空市"),
                 _word(60, 120, "2"), _word(89, 120, "R7.4.2", 24), _word(130, 120, "10:00"),
                 _word(170, 120, "架空町")]
        # 2 ページ目は桁の多い日付で、左端が 1 ページ目で学んだ日付欄より左に出る
        page2 = [_word(60, 100, "3"), _word(85, 100, "R7.10.10", 32), _word(130, 100, "13:00~1"),
                 _word(88, 106, "5:00頃", 20), _word(170, 100, "架空村")]
        xml = "".join("<page width=\"600\">" + "".join(p) + "</page>" for p in (page1, page2))
        rows = pdf_bbox.parse_bbox_table(xml, cols)
        self.assertEqual([r["№"] for r in rows], ["1", "2", "3"])
        self.assertEqual(rows[2]["目撃年月日"], "R7.10.10")
        self.assertIn("13:00~1", rows[2]["時間"])

    def test_western_dates_are_anchors(self):
        self.assertTrue(pdf_bbox.DATE_WORD.match("2021/4/13"))


if __name__ == "__main__":
    unittest.main()
