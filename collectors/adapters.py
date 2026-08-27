"""公開形式ごとの取得アダプタ。返り値はどれも「列名 -> 値」の辞書の列。

座標を自前で持つ形式（ArcGIS / KML）は _lat / _lon キーを付けて返す。
"""
from __future__ import annotations

import csv
import io
import re
import xml.etree.ElementTree as ET

import requests

UA = "japan-wildlife-sightings/0.1 (+https://github.com/yasumorishima/japan-wildlife-sightings)"
TIMEOUT = 60


def _get(url: str, **kw) -> requests.Response:
    r = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT, **kw)
    r.raise_for_status()
    return r


def _decode(raw: bytes, encoding: str | None) -> str:
    if encoding:
        return raw.decode(encoding, errors="replace")
    for enc in ("utf-8-sig", "cp932", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def fetch_csv(url: str, encoding: str | None = None, **_) -> list[dict]:
    text = _decode(_get(url).content, encoding)
    rows = list(csv.DictReader(io.StringIO(text)))
    return [{(k or "").strip(): v for k, v in row.items()} for row in rows]


def fetch_xlsx(url: str, sheet: int = 0, header_row: int = 1, **_) -> list[dict]:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(_get(url).content), read_only=True, data_only=True)
    ws = wb.worksheets[sheet]
    head, out = None, []
    for i, row in enumerate(ws.iter_rows(values_only=True), start=1):
        if i < header_row:
            continue
        if head is None:
            head = [str(c).strip() if c is not None else f"col{j}" for j, c in enumerate(row)]
            continue
        if all(c is None for c in row):
            continue
        out.append({head[j]: row[j] for j in range(min(len(head), len(row)))})
    return out


def fetch_arcgis(layer_url: str, page: int = 1000, **_) -> list[dict]:
    """FeatureServer のレイヤを全件取得する。列名は alias（日本語）に置き換える。"""
    meta = _get(layer_url, params={"f": "json"}).json()
    alias = {f["name"]: (f.get("alias") or f["name"]) for f in meta.get("fields", [])}
    out, offset = [], 0
    while True:
        r = _get(layer_url + "/query", params={
            "where": "1=1", "outFields": "*", "returnGeometry": "true",
            "outSR": 4326, "f": "json", "resultOffset": offset, "resultRecordCount": page,
        }).json()
        feats = r.get("features", [])
        for ft in feats:
            row = {alias.get(k, k): v for k, v in (ft.get("attributes") or {}).items()}
            geom = ft.get("geometry") or {}
            if geom.get("x") is not None:
                row["_lon"], row["_lat"] = geom["x"], geom["y"]
            out.append(row)
        if len(feats) < page or not r.get("exceededTransferLimit"):
            break
        offset += page
    return out


_PM = re.compile(r"<Placemark>.*?</Placemark>", re.S)


def fetch_kml(mid: str = None, url: str = None, **_) -> list[dict]:
    """Google マイマップの KML 書き出しを読む。ExtendedData を列として扱う。"""
    url = url or f"https://www.google.com/maps/d/kml?mid={mid}&forcekml=1"
    text = _get(url).content.decode("utf-8", errors="replace")
    ns = {"k": "http://www.opengis.net/kml/2.2"}
    out = []
    for chunk in _PM.findall(text):
        try:
            pm = ET.fromstring(re.sub(r'\sxmlns="[^"]+"', "", chunk))
        except ET.ParseError:
            continue
        row = {}
        name = pm.findtext("name")
        if name:
            row["_name"] = name.strip()
        for data in pm.iter("Data"):
            key = (data.get("name") or "").strip()
            val = data.findtext("value")
            if key:
                row[key] = (val or "").strip()
        coords = pm.findtext("./Point/coordinates")
        if coords:
            parts = coords.strip().split(",")
            if len(parts) >= 2:
                row["_lon"], row["_lat"] = float(parts[0]), float(parts[1])
        out.append(row)
    return out


from .pdf_table import fetch_pdf_table  # noqa: E402  (循環しないので末尾で読む)

ADAPTERS = {"csv": fetch_csv, "xlsx": fetch_xlsx, "arcgis": fetch_arcgis,
            "kml": fetch_kml, "pdf": fetch_pdf_table}
