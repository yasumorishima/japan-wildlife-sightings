"""shadow.py の確かめ。通信しない（控えた応答だけを返す）。"""
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import shadow  # noqa: E402


def result(rows=3, recs=None, dropped=None, unparsed=None, fields=None, error=None):
    recs = rows if recs is None else recs
    return {"error": error, "fetched_rows": rows, "dropped": dropped or {}, "unparsed": unparsed or {},
            "records": recs, "fields": fields if fields is not None else
            {f"s:{i}": [{"id": f"h{i}", "place": "p"}] for i in range(recs)}}


class CompareTest(unittest.TestCase):
    def test_same_is_empty(self):
        self.assertEqual(shadow.compare({"s": result()}, {"s": result()}), [])
        self.assertIn("一致", shadow.report([]))

    def test_first_stage_is_marked(self):
        new = result(rows=4, recs=3, dropped={"duplicate": 1})
        diffs = shadow.compare({"s": result()}, {"s": new})
        firsts = [d["stage"] for d in diffs if d.get("first")]
        self.assertEqual(firsts, ["fetched_rows"])
        self.assertIn("dropped", [d["stage"] for d in diffs])

    def test_changed_field_is_counted_without_value(self):
        old = result(fields={"s:0": [{"id": "a", "place": "h1"}]}, recs=1, rows=1)
        new = result(fields={"s:0": [{"id": "a", "place": "h2"}]}, recs=1, rows=1)
        diffs = shadow.compare({"s": old}, {"s": new})
        self.assertEqual([(d["stage"], d["detail"]) for d in diffs], [("fields", "place: 1 行")])
        self.assertNotIn("h2", shadow.report(diffs))

    def test_ids_and_errors(self):
        old = result(fields={"s:0": [{"id": "a"}], "s:1": [{"id": "b"}]}, recs=2, rows=2)
        new = result(fields={"s:0": [{"id": "a"}], "s:2": [{"id": "c"}]}, recs=2, rows=2)
        details = [d["detail"] for d in shadow.compare({"s": old}, {"s": new})]
        self.assertIn("旧のみ 1 行 / 新のみ 1 行", details)
        diffs = shadow.compare({"s": result()}, {"s": {"error": "ValueError"}})
        self.assertEqual(diffs[0]["stage"], "error")
        self.assertEqual(shadow.compare({"s": result()}, {})[0]["detail"], "旧のみ")


class CacheTest(unittest.TestCase):
    def test_replays_in_order_without_network(self):
        import requests
        from requests.adapters import HTTPAdapter
        with tempfile.TemporaryDirectory() as d:
            cache = pathlib.Path(d)
            req = requests.Request("GET", "https://example.invalid/a.csv").prepare()
            import hashlib
            k = hashlib.sha256(f"GET {req.url}\n".encode()).hexdigest()[:32]
            (cache / f"{k}.0.json").write_text(json.dumps({"error": "SSLError"}))
            (cache / f"{k}.1.json").write_text(json.dumps(
                {"status": 200, "reason": "OK", "url": req.url,
                 "headers": {"Content-Type": "text/csv; charset=utf-8"}}))
            (cache / f"{k}.1.bin").write_bytes("a,b\n1,2\n".encode())
            original = shadow.install_cache(cache)
            try:
                with self.assertRaises(requests.exceptions.SSLError):
                    requests.get(req.url)
                r = requests.get(req.url, stream=True)
                self.assertEqual(r.status_code, 200)
                self.assertEqual(b"".join(r.iter_content(3)), b"a,b\n1,2\n")
                self.assertEqual(r.text, "a,b\n1,2\n")
            finally:
                HTTPAdapter.send = original


if __name__ == "__main__":
    unittest.main()
