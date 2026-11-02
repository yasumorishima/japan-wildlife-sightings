"""Shapefile（点）を読む小さな読み手と、平面直角座標から緯度経度への変換。

依存を増やさないために自前で読む。対応するのは点（shape type 1）と、文字・数値の DBF 列だけ。
"""
from __future__ import annotations

import io
import math
import struct
import zipfile

# 平面直角座標系の原点（国土交通省告示）。岐阜県は第 VII 系
ZONE_ORIGIN = {
    7: (36.0, 137 + 10 / 60),
}


def plane_to_latlon(x_east: float, y_north: float, zone: int) -> tuple[float, float]:
    """平面直角座標（m）を JGD2011 の緯度経度（度）にする。

    国土地理院の計算式（河瀬 2011, ガウス・クリューゲル図法の逆計算）。GRS80, m0 = 0.9999。
    引数は shapefile の並び（X＝東向き, Y＝北向き）で受ける。
    """
    lat0, lon0 = (math.radians(v) for v in ZONE_ORIGIN[zone])
    a, F, m0 = 6378137.0, 298.257222101, 0.9999
    n = 1 / (2 * F - 1)
    A = [1 + n**2 / 4 + n**4 / 64,
         -1.5 * (n - n**3 / 8 - n**5 / 64),
         15 / 16 * (n**2 - n**4 / 4),
         -35 / 48 * (n**3 - 5 / 16 * n**5),
         315 / 512 * n**4,
         -693 / 1280 * n**5]
    beta = [0, n / 2 - 2 * n**2 / 3 + 37 * n**3 / 96, n**2 / 48 + n**3 / 15, 17 * n**3 / 480]
    delta = [0, 2 * n - 2 * n**2 / 3 - 2 * n**3, 7 * n**2 / 3 - 8 * n**3 / 5, 56 * n**3 / 15]
    k = m0 * a / (1 + n)
    abar = k * A[0]
    s0 = k * (A[0] * lat0 + sum(A[j] * math.sin(2 * j * lat0) for j in range(1, 6)))
    xi, eta = (y_north + s0) / abar, x_east / abar
    xi2 = xi - sum(beta[j] * math.sin(2 * j * xi) * math.cosh(2 * j * eta) for j in range(1, 4))
    eta2 = eta - sum(beta[j] * math.cos(2 * j * xi) * math.sinh(2 * j * eta) for j in range(1, 4))
    chi = math.asin(math.sin(xi2) / math.cosh(eta2))
    lat = chi + sum(delta[j] * math.sin(2 * j * chi) for j in range(1, 4))
    lon = lon0 + math.atan(math.sinh(eta2) / math.cos(xi2))
    return math.degrees(lat), math.degrees(lon)


def _dbf(raw: bytes, encoding: str) -> list[dict]:
    nrec, hlen, rlen = struct.unpack("<IHH", raw[4:12])
    fields, p = [], 32
    while raw[p] != 0x0D:
        name = raw[p:p + 11].split(b"\0")[0].decode(encoding, errors="replace").strip()
        fields.append((name, chr(raw[p + 11]), raw[p + 16]))
        p += 32
    out = []
    for i in range(nrec):
        rec = raw[hlen + i * rlen: hlen + (i + 1) * rlen]
        if rec[:1] == b"*":  # 削除済みの行
            out.append(None)
            continue
        row, q = {}, 1
        for name, _, size in fields:
            row[name] = rec[q:q + size].decode(encoding, errors="replace").strip().strip("\0")
            q += size
        out.append(row)
    return out


def _points(raw: bytes) -> list[tuple[float, float] | None]:
    pts, p = [], 100
    while p + 12 <= len(raw):
        clen = struct.unpack(">i", raw[p + 4:p + 8])[0] * 2
        stype = struct.unpack("<i", raw[p + 8:p + 12])[0]
        pts.append(struct.unpack("<2d", raw[p + 12:p + 28]) if stype == 1 else None)
        p += 8 + clen
    return pts


def read_zip(blob: bytes, encoding: str = "cp932") -> tuple[list[dict], str | None]:
    """ZIP の中の最初の .shp/.dbf を読み、属性に _x/_y を足した行と .prj の中身を返す。"""
    z = zipfile.ZipFile(io.BytesIO(blob))
    names = {n.lower(): n for n in z.namelist()}
    shp = next(n for low, n in names.items() if low.endswith(".shp"))
    base = shp[:-4]
    pick = lambda ext: names.get((base + ext).lower())  # noqa: E731
    rows = _dbf(z.read(pick(".dbf")), encoding)
    pts = _points(z.read(shp))
    prj = z.read(pick(".prj")).decode("ascii", errors="replace") if pick(".prj") else None
    out = []
    for row, pt in zip(rows, pts):
        if row is None:
            continue
        if pt:
            row["_x"], row["_y"] = pt
        out.append(row)
    return out, prj
