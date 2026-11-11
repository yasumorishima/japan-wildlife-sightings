"""正規化と個人情報の伏せ方のテスト。通信しない。氏名はすべて架空。

    python3 -m unittest discover -s tests
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collectors.normalize import mask_person, occurred_at  # noqa: E402


class MaskPersonTest(unittest.TestCase):
    masked = {
        "山田太郎氏が目撃": "（個人名）氏が目撃",
        "山田宅の裏山": "（個人名）宅の裏山",
        "山田さん宅の柿の木": "（個人名）さん宅の柿の木",
        "ヤマダさん宅の裏": "（個人名）さん宅の裏",
        "山田さんが目撃した": "（個人名）さんが目撃した",
        "小野寺さんが通報": "（個人名）さんが通報",
        "二宮様方の畑": "（個人名）様方の畑",
        "猟友会山田氏": "猟友会（個人名）氏",
        "「たろう99」さんという方が目撃": "「（個人名）」さんという方が目撃",
        "連絡先 090-1234-5678": "連絡先 （電話番号）",
        "連絡先０９０－１２３４－５６７８": "連絡先（電話番号）",
        "０９０１２３４５６７８": "（電話番号）",
        "taro@example.com まで": "（メールアドレス） まで",
    }
    kept = [
        "目撃者宅の前", "地元住民宅付近", "帰宅途中に目撃", "大工さんが目撃", "床屋さんの敷地内",
        "運転手さんが現地を確認", "お客さんが目撃", "ご近所さんの家庭菜園", "皆さんが気をつけて",
        "パン屋さん方面に歩いていた", "藩主佐竹氏の居城跡", "０５-１１ 105", "様子を見ていた模様。",
    ]

    def test_masked(self):
        for text, want in self.masked.items():
            with self.subTest(text=text):
                self.assertEqual(mask_person(text), want)

    def test_kept(self):
        for text in self.kept:
            with self.subTest(text=text):
                self.assertEqual(mask_person(text), text)

    def test_idempotent(self):
        for text in list(self.masked) + self.kept:
            once = mask_person(text)
            self.assertEqual(mask_person(once), once)


class OccurredAtTest(unittest.TestCase):
    def test_formats(self):
        cases = {
            ("2026/10/31 14:05", None): "2026-10-31T14:05:00+09:00",
            ("2026-10-31", None): "2026-10-31",
            ("2026-10-31", "午後3時30分"): "2026-10-31T15:30:00+09:00",
            ("令和7年4月6日", None): "2025-04-06",
            ("2026-10-31T14:05:00+09:00", None): "2026-10-31T14:05:00+09:00",
        }
        for (raw, hint), want in cases.items():
            with self.subTest(raw=raw, hint=hint):
                self.assertEqual(occurred_at(raw, hint), want)

    def test_time_has_offset(self):
        # 時刻つきで返す値は、必ず日本時間の時差を持つ
        for raw in ("2026/10/31 14:05", "2026/10/31 14:05:09", 1761886800000):
            with self.subTest(raw=raw):
                self.assertTrue(occurred_at(raw).endswith("+09:00"))


if __name__ == "__main__":
    unittest.main()
