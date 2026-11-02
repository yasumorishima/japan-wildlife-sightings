"""公開形式ごとの取得アダプタ。返り値はどれも「列名 -> 値」の辞書の列。

座標を自前で持つ形式（ArcGIS / KML）は _lat / _lon キーを付けて返す。
"""
from __future__ import annotations

import csv
import io
import re
import ssl
import sys
import xml.etree.ElementTree as ET

import requests
from requests.adapters import HTTPAdapter

UA = "japan-wildlife-sightings/0.1 (+https://github.com/yasumorishima/japan-wildlife-sightings)"
TIMEOUT = 60


class _LegacyTLSAdapter(HTTPAdapter):
    """暗号の要求だけを緩めて繋ぐ。証明書の検証は既定のまま緩めない。"""

    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.set_ciphers("DEFAULT:@SECLEVEL=1")
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


_legacy_session = None


def _legacy() -> requests.Session:
    global _legacy_session
    if _legacy_session is None:
        _legacy_session = requests.Session()
        _legacy_session.mount("https://", _LegacyTLSAdapter())
    return _legacy_session


def _get(url: str, **kw) -> requests.Response:
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT, **kw)
    except requests.exceptions.SSLError:
        # 前方秘匿のある暗号を持たない公開元がある（山口県のカタログは
        # AES256-SHA256＝RSA 鍵交換しか受けない）。GitHub の runner の既定方針だと
        # サーバが insufficient security を返して繋がらないので、暗号の要求だけを
        # 緩めて 1 回やり直す。証明書の検証は緩めないので、なりすましは弾かれる。
        # 公開データを取得するだけで、こちらから送る秘密は無い。
        print(f"注意: 暗号方針を緩めて再取得します（公開元が旧式の TLS のみ）: {url[:60]}",
              file=sys.stderr)
        r = _legacy().get(url, headers={"User-Agent": UA}, timeout=TIMEOUT, **kw)
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


def _find_link(page: str, pattern: str) -> str:
    """公開ページから、pattern に合う最初のリンクの絶対 URL を返す。"""
    from urllib.parse import urljoin
    html = _decode(_get(page).content, None)
    for href in re.findall(r'href="([^"]+)"', html):
        if re.search(pattern, href):
            return urljoin(page, href)
    raise LookupError(f"{page} に {pattern} に合うリンクが無い")


def fetch_csv(url: str | None = None, encoding: str | None = None, link_from: str | None = None,
              link_pattern: str | None = None, urls: list[str] | None = None, **_) -> list[dict]:
    # 年度ごとに別ファイルの出典（仙台市）は urls に並べる。_dataset で id を分ける
    if urls:
        out = []
        for n, u in enumerate(urls):
            for row in fetch_csv(u, encoding=encoding):
                row["_dataset"] = str(n)
                out.append(row)
        return out
    # ファイル名に更新日が入り、更新のたびに URL が変わる出典（山形県・東京都）は、公開ページの
    # リンクから毎回たどる。固定 URL だと古いファイルが消えた日に 404 になる。
    if link_from:
        url = _find_link(link_from, link_pattern)
    text = _decode(_get(url).content, encoding)
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        clean = {(k or "").strip(): v for k, v in row.items()}
        # 末尾に空行が続く CSV がある（上砂川町の令和8年度は 82 行中 80 行が空）
        if not any((v or "").strip() for v in clean.values() if isinstance(v, str)):
            continue
        out.append(clean)
    return out


def fetch_xlsx(url: str | None = None, sheet: int = 0, header_row: int = 1, link_from: str | None = None,
               link_pattern: str | None = None, **_) -> list[dict]:
    import openpyxl

    if link_from:  # 宮城県はファイル名に更新日が入る
        url = _find_link(link_from, link_pattern)

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


def fetch_arcgis(layer_url: str | None = None, page: int = 1000, layer_urls: list[str] | None = None,
                 **_) -> list[dict]:
    """FeatureServer のレイヤを全件取得する。列名は alias（日本語）に置き換える。

    年度ごとに別レイヤで公開する出典（柏崎市など）は layer_urls に並べる。各行に
    _dataset（並べた順の番号）を付けるので、レイヤごとに 1 から振り直す番号でも id が重ならない。
    """
    if layer_urls:
        out = []
        for n, url in enumerate(layer_urls):
            for row in fetch_arcgis(url, page=page):
                row["_dataset"] = str(n)
                out.append(row)
        return out
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


from .pdf_bbox import fetch_pdf_bbox  # noqa: E402
from .pdf_table import fetch_pdf_table  # noqa: E402  (循環しないので末尾で読む)

ADAPTERS = {"csv": fetch_csv, "xlsx": fetch_xlsx, "arcgis": fetch_arcgis,
            "kml": fetch_kml, "pdf": fetch_pdf_table,
            "pdf_bbox": fetch_pdf_bbox}


def fetch_ckan(query: str | None = None, base: str = "https://data.bodik.jp",
               name: str | None = None, org: str | None = None,
               title_pattern: str | None = None, rows: int = 50,
               encoding: str | None = None, **_) -> list[dict]:
    """CKAN のカタログを検索して CSV を集める。

    年度ごとにデータセットが増える出典があるので、URL を書き並べずカタログを引く。
    次年度ぶんが公開されれば自動で入る。base は CKAN のルートで、BODIK
    （自治体共同）は https://data.bodik.jp、山口県は https://yamaguchi-opendata.jp/ckan。

    検索に `A OR B` は効かない（0 件になる）ので単語 1 つずつ引く。検索語はゆるく
    当たるので org と title_pattern で必ず絞る。
    """
    api = base.rstrip("/") + "/api/3/action/"
    if name:
        # データセット名が分かっているときは検索を介さない。日本語の全文検索が
        # 効かないカタログがある（北海道の共同ポータルは「ヒグマ」で 0 件を返す）。
        results = [_get(api + "package_show", params={"id": name}).json()["result"]]
    else:
        results = _get(api + "package_search",
                       params={"q": query, "rows": rows}).json()["result"].get("results", [])
    out = []
    for pkg in results:
        title = pkg.get("title", "")
        owner = (pkg.get("organization") or {}).get("title", "")
        if org and owner != org:
            continue
        if title_pattern and not re.search(title_pattern, title):
            continue
        for res in pkg.get("resources", []):
            if (res.get("format") or "").upper() != "CSV":
                continue
            try:
                for row in fetch_csv(res["url"], encoding=encoding):
                    row["_dataset"] = title
                    # id にはタイトルでなく CKAN のスラッグを使う。タイトルは
                    # 公開元が整えると変わる（山口県は年の表記が 2024 と ２０２６ で
                    # 不統一）＝混ぜると当該年度の id が丸ごと入れ替わる。
                    row["_dataset_id"] = pkg.get("name") or title
                    out.append(row)
            except Exception:
                continue
    return out


ADAPTERS["ckan"] = fetch_ckan
# BODIK は CKAN の既定の引き先。既存の出典設定をそのまま動かすため名前を残す。
ADAPTERS["bodik"] = fetch_ckan


def fetch_ckan_shp(base: str, name: str, plane_zone: int | None = None, encoding: str = "cp932",
                   csv_lat: str | None = None, csv_lon: str | None = None, **_) -> list[dict]:
    """CKAN のデータセットにある年度別の Shapefile（ZIP）と CSV を全部読む（岐阜県）。

    各行に _fiscal_year（リソース名の「令和７年度」等から）を付ける。表に年の列が無く、
    月と日しか無いため。.prj が無い Shapefile は平面直角座標（plane_zone 系）として変換する。
    """
    from . import normalize
    from .shapefile import plane_to_latlon, read_zip

    api = base.rstrip("/") + "/api/3/action/"
    pkg = _get(api + "package_show", params={"id": name}).json()["result"]
    out = []
    for res in pkg.get("resources", []):
        m = re.search(r"(令和|平成)\s*([0-9０-９元]+)\s*年度", res.get("name") or "")
        if not m:
            continue
        n = normalize._z2h(m.group(2))
        fy = {"令和": 2018, "平成": 1988}[m.group(1)] + (1 if n == "元" else int(n))
        fmt = (res.get("format") or "").upper()
        if fmt == "CSV":
            rows = fetch_csv(res["url"], encoding=None)
            for r in rows:
                try:
                    r["_lat"], r["_lon"] = float(r[csv_lat]), float(r[csv_lon])
                except (KeyError, TypeError, ValueError):
                    pass
        elif fmt == "ZIP":
            rows, prj = read_zip(_get(res["url"]).content, encoding)
            for r in rows:
                if "_x" not in r:
                    continue
                if prj and "GEOGCS" in prj:
                    r["_lon"], r["_lat"] = r.pop("_x"), r.pop("_y")
                elif plane_zone:
                    r["_lat"], r["_lon"] = plane_to_latlon(r.pop("_x"), r.pop("_y"), plane_zone)
        else:
            continue
        for i, r in enumerate(rows):
            r["_fiscal_year"] = fy
            r["_dataset"] = str(fy)
            r["_row"] = str(i + 1)
            out.append(r)
    return out


ADAPTERS["ckan_shp"] = fetch_ckan_shp
