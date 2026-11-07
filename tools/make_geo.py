"""把內政部縣市界線（SHP）轉成地圖用的SVG路徑：data/geo/counties.json。

只有原始界線或投影設定改變時才需要重跑：python3 tools/make_geo.py
"""
from __future__ import annotations

import io
import json
import struct
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import atlas  # noqa: E402

ZIP = atlas.ROOT / "data" / "raw" / "county-boundary-1140318.zip"
EPS = 0.35      # 簡化容許誤差（像素）
MIN_SIZE = 1.0  # 外框小於這個像素的小島不畫


def read_dbf(data: bytes, encoding: str):
    n = struct.unpack("<I", data[4:8])[0]
    header_len, rec_len = struct.unpack("<HH", data[8:12])
    fields, pos = [], 32
    while data[pos] != 0x0D:
        name = data[pos:pos + 11].split(b"\0")[0].decode("ascii")
        fields.append((name, data[pos + 16]))
        pos += 32
    rows = []
    for r in range(n):
        off = header_len + r * rec_len + 1
        row = {}
        for name, length in fields:
            row[name] = data[off:off + length].decode(encoding, "replace").strip()
            off += length
        rows.append(row)
    return rows


def read_shp(data: bytes):
    pos, shapes = 100, []
    while pos < len(data):
        _, length = struct.unpack(">ii", data[pos:pos + 8])
        content = data[pos + 8:pos + 8 + length * 2]
        pos += 8 + length * 2
        if struct.unpack("<i", content[:4])[0] == 0:
            shapes.append([])
            continue
        n_parts, n_points = struct.unpack("<ii", content[36:44])
        parts = list(struct.unpack(f"<{n_parts}i", content[44:44 + 4 * n_parts]))
        pts = struct.unpack(f"<{2 * n_points}d", content[44 + 4 * n_parts:44 + 4 * n_parts + 16 * n_points])
        xy = list(zip(pts[0::2], pts[1::2]))
        parts.append(n_points)
        shapes.append([xy[parts[k]:parts[k + 1]] for k in range(n_parts)])
    return shapes


def simplify(points, eps):
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        (x1, y1), (x2, y2) = points[a], points[b]
        dx, dy = x2 - x1, y2 - y1
        norm = (dx * dx + dy * dy) ** 0.5
        best, idx = -1.0, -1
        for i in range(a + 1, b):
            x0, y0 = points[i]
            d = abs(dy * x0 - dx * y0 + x2 * y1 - y2 * x1) / norm if norm else ((x0 - x1) ** 2 + (y0 - y1) ** 2) ** 0.5
            if d > best:
                best, idx = d, i
        if best > eps:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(points, keep) if k]


def main():
    z = zipfile.ZipFile(ZIP)
    names = {n.rsplit(".", 1)[-1].lower(): n for n in z.namelist() if n.startswith("COUNTY_MOI")}
    enc = z.read(names["cpg"]).decode().strip() or "utf-8"
    rows = read_dbf(z.read(names["dbf"]), enc)
    shapes = read_shp(z.read(names["shp"]))
    out = {}
    for row, rings in zip(rows, shapes):
        county = row.get("COUNTYNAME")
        if county not in atlas.COUNTIES:
            print("略過", county, file=sys.stderr)
            continue
        path = []
        for ring in rings:
            view = atlas.view_for(county, ring[0][0])
            pts = [view.project(lon, lat) for lon, lat in ring]
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            if max(xs) - min(xs) < MIN_SIZE and max(ys) - min(ys) < MIN_SIZE:
                continue
            pts = simplify(pts, EPS)
            if len(pts) < 3:
                continue
            path.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + "Z")
        out[county] = "".join(path)
    geo = {
        "source": "內政部「直轄市、縣市界線(TWD97經緯度)」1140318版，政府資料開放授權條款第1版",
        "width": atlas.MAP_W, "height": atlas.MAP_H,
        "insets": [dict(name=c, x=v.x0, y=v.y0, w=round(v.w, 1), h=round(v.h, 1), label=v.label)
                   for c, v in atlas.INSET_VIEWS.items()],
        "counties": {c: out.get(c, "") for c in atlas.COUNTIES},
    }
    atlas.GEO_JSON.parent.mkdir(parents=True, exist_ok=True)
    atlas.GEO_JSON.write_text(json.dumps(geo, ensure_ascii=False, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    print("寫入", atlas.GEO_JSON.relative_to(atlas.ROOT), f"{atlas.GEO_JSON.stat().st_size:,} bytes")
    # 檢查聚落點是否都落在對應的框內
    groups = {}
    for p in atlas.load_places():
        if p.has_xy:
            groups.setdefault(atlas.view_for(p.county, p.lon), []).append(atlas.project_place(p))
    for v, pts in groups.items():
        bad = [q for q in pts if not (v.x0 - 1 <= q[0] <= v.x0 + v.w + 1 and v.y0 - 1 <= q[1] <= v.y0 + v.h + 1)]
        print(v.label or "本島與澎湖", "點數", len(pts), "超出框", len(bad))


if __name__ == "__main__":
    main()
