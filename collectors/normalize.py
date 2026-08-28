"""出典ごとにバラバラな表記を、共通スキーマの値へそろえる。

ここに書く関数は「入力をそのまま捨てない」方針で、判定できなかったものは
None ではなく raw を残して後段で数えられるようにする。
"""
from __future__ import annotations

import datetime as _dt
import re

# --- 座標 -------------------------------------------------------------
# 日本の陸域を含む緩い外接矩形（与那国島 122.93E / 沖ノ鳥島 20.42N /
# 南鳥島 153.98E / 択捉島）。収録側（collect.py）と検証側（validate.py）で
# 別々に持つと片方だけ通る値ができるので、ここ 1 か所に置く。
JP_LAT = (20.0, 46.5)
JP_LON = (122.0, 154.0)


def in_japan(lat, lon):
    """日本の範囲に入っていればそのまま、外なら (None, None) を返す。

    行番号だけ先に振ってあって中身が入るまで緯度経度が 0.00000 の様式（山口県）を
    そのまま地図に出すとギニア湾に点が並ぶ。県境まで絞ると出典側の誤記を黙って
    捨てることになるので、判定は日本全体の範囲にとどめる。
    """
    if lat is None or lon is None:
        return None, None
    if JP_LAT[0] <= lat <= JP_LAT[1] and JP_LON[0] <= lon <= JP_LON[1]:
        return lat, lon
    return None, None


# --- 獣種 -------------------------------------------------------------
_SPECIES = [
    ("higuma", "ヒグマ", ("ヒグマ", "ひぐま", "羆")),
    ("tsukinowaguma", "ツキノワグマ", ("ツキノワグマ", "つきのわぐま", "月の輪熊")),
    ("bear", "クマ", ("クマ", "くま", "熊", "bear")),
    ("inoshishi", "イノシシ", ("イノシシ", "いのしし", "猪", "野生イノシシ")),
    ("shika", "ニホンジカ", ("ニホンジカ", "シカ", "しか", "鹿")),
    ("saru", "ニホンザル", ("ニホンザル", "サル", "猿")),
    ("kamoshika", "カモシカ", ("カモシカ", "羚羊")),
]

# 都道府県によっては「ヒグマ」しか扱わない等、既定値を持たせたい場合がある
def species(raw: str | None, default_key: str | None = None) -> tuple[str, str]:
    """(正規化キー, 表示名) を返す。判定できなければ ('unknown', raw)。"""
    text = (raw or "").strip()
    for key, label, needles in _SPECIES:
        if any(n in text for n in needles):
            return key, label
    if default_key:
        for key, label, _ in _SPECIES:
            if key == default_key:
                return key, label
    return "unknown", text


# --- 出没区分 ---------------------------------------------------------
_CATEGORY = [
    ("injury", ("人身", "負傷", "襲わ")),
    ("damage", ("被害", "食害", "農作物")),
    ("capture", ("捕獲", "駆除", "有害捕獲")),
    ("trace", ("痕跡", "足跡", "糞", "爪跡")),
    ("sighting", ("目撃", "出没", "発見", "確認")),
]


def category(raw: str | None) -> tuple[str, str]:
    text = (raw or "").strip()
    for key, needles in _CATEGORY:
        if any(n in text for n in needles):
            return key, text
    return "unknown", text


# --- 日時 -------------------------------------------------------------
_ERA_START = {"令和": 2018, "平成": 1988, "昭和": 1925}  # 元年 = start + 1
_ERA_RE = re.compile(r"(令和|平成|昭和)\s*([0-9０-９元]+)\s*年\s*([0-9０-９]+)\s*月\s*([0-9０-９]+)\s*日")
_ZEN = str.maketrans("０１２３４５６７８９：", "0123456789:")


def _z2h(s: str) -> str:
    return s.translate(_ZEN)


_ERA_SHORT = {"R": "令和", "H": "平成", "S": "昭和"}
_SHORT_RE = re.compile(r"^([RHS])\.?\s*(\d+)\.(\d+)\.(\d+)")


def wareki_to_date(text: str) -> _dt.date | None:
    """令和７年４月６日 → date(2025, 4, 6)。合わなければ None。"""
    sm = _SHORT_RE.match((text or "").strip())
    if sm:
        era, y, mo, d = _ERA_SHORT[sm.group(1)], sm.group(2), sm.group(3), sm.group(4)
        try:
            return _dt.date(_ERA_START[era] + int(y), int(mo), int(d))
        except ValueError:
            return None
    m = _ERA_RE.search(text or "")
    if not m:
        return None
    era, y, mo, d = m.groups()
    y = 1 if y == "元" else int(_z2h(y))
    try:
        return _dt.date(_ERA_START[era] + y, int(_z2h(mo)), int(_z2h(d)))
    except ValueError:
        return None


# 末尾の %m/%d/%Y は Google マイマップの書き出し（米国式）。日本の自治体データに
# 日/月/年 表記は観測されていないので月始まりで解釈する。
_DATE_PATTERNS = ("%Y/%m/%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S",
                  "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y年%m月%d日", "%Y.%m.%d", "%m/%d/%Y")


_MD_RE = re.compile(r"^\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")


def month_day_with_fiscal_year(text: str, fiscal_year: int) -> _dt.date | None:
    """「10月18日」のように年が無い表記を、年度（4月始まり）で補う。"""
    m = _MD_RE.match(_z2h(str(text or "")))
    if not m:
        return None
    mo, d = int(m.group(1)), int(m.group(2))
    try:
        return _dt.date(fiscal_year if mo >= 4 else fiscal_year + 1, mo, d)
    except ValueError:
        return None


def excel_serial(text: str) -> _dt.date | None:
    """Excel の日付シリアル値（"43575" のような 5 桁）を日付にする。

    表計算から書き出した CSV に生の数値が残っていることがある（石川県に 2 件）。
    基準は 1899-12-30（Excel の 1900 年うるう年バグを織り込んだ値）。
    範囲を 20000〜60000（1954〜2064）に限って、ただの番号を日付と読まないようにする。
    """
    if not re.fullmatch(r"\d{5}", text or ""):
        return None
    n = int(text)
    if not 20000 <= n <= 60000:
        return None
    return _dt.date(1899, 12, 30) + _dt.timedelta(days=n)


def occurred_at(raw, time_hint: str | None = None, fiscal_year: int | None = None) -> str | None:
    """ISO8601（日付のみなら YYYY-MM-DD）を返す。判定できなければ None。

    ArcGIS の日付は epoch ミリ秒で来るので数値も受ける。時刻が別列にある
    ソース（山形・群馬など）は time_hint に渡す。
    """
    if raw is None or raw == "":
        return None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        # ArcGIS FeatureServer の esriFieldTypeDate は UTC の epoch ms
        dt = _dt.datetime.fromtimestamp(raw / 1000, tz=_dt.timezone.utc)
        return dt.astimezone(_dt.timezone(_dt.timedelta(hours=9))).isoformat()
    text = _z2h(str(raw).strip())
    d = wareki_to_date(text) or excel_serial(text)
    if d:
        base = d.isoformat()
    else:
        base = None
        for fmt in _DATE_PATTERNS:
            try:
                parsed = _dt.datetime.strptime(text, fmt)
            except ValueError:
                continue
            # 書式に時刻が含まれない場合は日付のみを返し、time_hint を効かせる
            base = parsed.isoformat() if "%H" in fmt else parsed.date().isoformat()
            break
        if base is None and fiscal_year is not None:
            fd = month_day_with_fiscal_year(text, fiscal_year)
            if fd:
                base = fd.isoformat()
        if base is None:
            m = re.search(r"(\d{4})[/\-年](\d{1,2})[/\-月](\d{1,2})", text)
            if not m:
                return None
            base = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    if time_hint and len(base) == 10:
        t = re.search(r"(\d{1,2})[:：時](\d{1,2})?", _z2h(str(time_hint)))
        if t:
            hh = min(int(t.group(1)), 23)
            mm = min(int(t.group(2) or 0), 59)
            base = f"{base}T{hh:02d}:{mm:02d}:00+09:00"
    return base
