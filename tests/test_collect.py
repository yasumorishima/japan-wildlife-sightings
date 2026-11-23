"""collect.build が取り込まなかった行と読めなかった値を数えるかのテスト。通信しない。"""
import sys
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import collect  # noqa: E402
from collectors import fetchlog  # noqa: E402

SRC = {
    "id": "test", "pref_code": "00", "pref": "テスト県", "species_default": "bear",
    "map": {"occurred_at": ["日付"], "lat": "緯度", "lon": "経度", "place": "場所"},
    "license": {"id": "CC-BY-4.0"},
}


class BuildStatsTest(unittest.TestCase):
    def test_counts_unparsed_and_out_of_range(self):
        rows = [
            {"日付": "2026/5/1", "緯度": "35.0", "経度": "135.0", "場所": "A"},
            {"日付": "不明", "緯度": "0", "経度": "0", "場所": "B"},
            {"日付": "", "緯度": "", "経度": "", "場所": "C"},
        ]
        stats = Counter()
        recs = collect.build(rows, SRC, stats)
        self.assertEqual(len(recs), 3)
        self.assertEqual(stats["unparsed:date"], 1)
        self.assertEqual(stats["unparsed:coords_out_of_range"], 1)

    def test_counts_required_and_duplicates(self):
        src = dict(SRC, require=["occurred_at"], dedupe_by=["occurred_at", "place"])
        rows = [
            {"日付": "2026/5/1", "場所": "A"},
            {"日付": "2026/5/1", "場所": "A"},
            {"日付": "", "場所": "B"},
            {"日付": "不明", "場所": "C"},
        ]
        stats = Counter()
        recs = collect.build(rows, src, stats)
        self.assertEqual(len(recs), 1)
        self.assertEqual(stats["dropped:missing_occurred_at"], 2)
        self.assertEqual(stats["dropped:duplicate"], 1)
        # 落とした行は「読めず」に二重に数えない
        self.assertEqual(stats["unparsed:date"], 0)

    def test_record_fetch(self):
        fetchlog.reset()
        fetchlog.record("https://example.org/a.csv")
        fetchlog.record("https://example.org/a.csv")
        fetchlog.drop("hidden_by_config", 2)
        entry = {}
        collect.record_fetch(entry, Counter({"dropped:duplicate": 1, "unparsed:date": 3}))
        self.assertEqual(entry["fetched_urls"], [{"url": "https://example.org/a.csv"}])
        self.assertEqual(entry["dropped"], {"duplicate": 1, "hidden_by_config": 2})
        self.assertEqual(entry["unparsed"], {"date": 3})


if __name__ == "__main__":
    unittest.main()
