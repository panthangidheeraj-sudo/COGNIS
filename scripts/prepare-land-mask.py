"""Build the land mask used by the monochrome "intelligence" globe (src/components/globe/assets/land-mask-2k.png).

Run once; the output is committed, so the app never runs this.

    pip install pillow numpy
    npm install            # world-atlas ships Natural Earth land polygons (public domain)
    python scripts/prepare-land-mask.py

What it makes
  A 2048x1024 equirectangular greyscale map: 255 = land, 0 = water, anti-aliased along the coast
  (drawn at 4x and averaged down). Column 0 is longitude -180, the top row is latitude +90.
  The shader reads it for the coastline, the faint land tone and the inland contour; the ivory dots
  themselves come from landDots.ts. No satellite imagery is involved.
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "node_modules" / "world-atlas" / "land-50m.json"
OUT = ROOT / "src" / "components" / "globe" / "assets" / "land-mask-2k.png"

W, H = 2048, 1024
SS = 4  # supersampling


def decode_arcs(topo: dict) -> list[list[tuple[float, float]]]:
    sx, sy = topo["transform"]["scale"]
    tx, ty = topo["transform"]["translate"]
    arcs = []
    for arc in topo["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in arc:
            x += dx
            y += dy
            pts.append((x * sx + tx, y * sy + ty))
        arcs.append(pts)
    return arcs


def ring_points(ring: list[int], arcs: list[list[tuple[float, float]]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for idx in ring:
        pts = arcs[idx] if idx >= 0 else arcs[~idx][::-1]
        out.extend(pts if not out else pts[1:])
    return out


def unwrap(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Make longitudes continuous along a ring (no +-180 jumps) so it can be filled on a flat map.

    A ring that circles a pole (Antarctica) ends 360 degrees away from where it started; it is closed
    through the pole so the fill reaches the map's edge.
    """
    out = [pts[0]]
    offset = 0.0
    for (lon0, _), (lon1, lat1) in zip(pts, pts[1:]):
        d = lon1 - lon0
        if d > 180:
            offset -= 360
        elif d < -180:
            offset += 360
        out.append((lon1 + offset, lat1))
    if abs(out[-1][0] - out[0][0]) > 180:  # encircles a pole
        pole = -90.0 if sum(p[1] for p in out) < 0 else 90.0
        out += [(out[-1][0], pole), (out[0][0], pole)]
    return out


def main() -> None:
    topo = json.loads(SRC.read_text())
    arcs = decode_arcs(topo)
    polys = []
    for geom in topo["objects"]["land"]["geometries"]:
        if geom["type"] == "MultiPolygon":
            polys.extend(geom["arcs"])
        elif geom["type"] == "Polygon":
            polys.append(geom["arcs"])

    w, h = W * SS, H * SS
    im = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(im)

    def px(p: tuple[float, float]) -> tuple[float, float]:
        return ((p[0] + 180.0) / 360.0 * w, (90.0 - p[1]) / 180.0 * h)

    for poly in polys:
        for i, ring in enumerate(poly):
            flat = unwrap(ring_points(ring, arcs))
            if len(flat) < 3:
                continue
            for shift in (-360.0, 0.0, 360.0):  # the part that crosses the antimeridian appears on both edges
                pts = [px((lon + shift, lat)) for lon, lat in flat]
                draw.polygon(pts, fill=255 if i == 0 else 0)  # exterior filled, holes (lakes) carved out

    out = im.resize((W, H), Image.BOX)
    out.save(OUT, "PNG", optimize=True)
    print(f"{OUT.relative_to(ROOT)}  {OUT.stat().st_size / 1024:.0f} KB  ({len(polys)} polygons)")


if __name__ == "__main__":
    main()
