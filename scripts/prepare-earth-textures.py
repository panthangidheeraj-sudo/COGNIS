"""Build the Earth textures used by the WebGL globe (src/components/globe/assets/).

Run once; the outputs are committed, so the app never runs this.

    pip install pillow numpy
    npm pack three-globe            # ships NASA's Blue Marble as example/img/earth-blue-marble.jpg
    tar xzf three-globe-*.tgz package/example/img/earth-blue-marble.jpg
    python scripts/prepare-earth-textures.py package/example/img/earth-blue-marble.jpg

Sources
  earth-day-*.jpg    NASA Visible Earth "Blue Marble" (public domain), resized. No colour edits:
                     the shader does the ocean grading so it can be tuned per theme.
  earth-clouds-1k.jpg  Procedural, generated here (no third-party imagery). Seamless around the
                     globe: noise is sampled on the unit sphere, not on the flat map.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

OUT = Path(__file__).resolve().parents[1] / "src" / "components" / "globe" / "assets"


def day_textures(src: Path) -> None:
    im = Image.open(src).convert("RGB")
    for w, q, name in ((2048, 84, "earth-day-2k.jpg"), (1024, 82, "earth-day-1k.jpg")):
        out = im.resize((w, w // 2), Image.LANCZOS)
        if w == 2048:
            out = out.filter(ImageFilter.UnsharpMask(radius=1.2, percent=40, threshold=2))
        out.save(OUT / name, "JPEG", quality=q, optimize=True, progressive=True)


# ---- 3D gradient noise on the sphere (vectorised) ----------------------------------------
rng = np.random.default_rng(20261007)
PERM = np.concatenate([rng.permutation(256)] * 2)
GRAD = np.array([[1, 1, 0], [-1, 1, 0], [1, -1, 0], [-1, -1, 0], [1, 0, 1], [-1, 0, 1], [1, 0, -1], [-1, 0, -1],
                 [0, 1, 1], [0, -1, 1], [0, 1, -1], [0, -1, -1]], dtype=np.float64)


def _fade(t: np.ndarray) -> np.ndarray:
    return t * t * t * (t * (t * 6 - 15) + 10)


def perlin3(x: np.ndarray, y: np.ndarray, z: np.ndarray) -> np.ndarray:
    xi, yi, zi = np.floor(x).astype(int), np.floor(y).astype(int), np.floor(z).astype(int)
    xf, yf, zf = x - xi, y - yi, z - zi
    xi, yi, zi = xi & 255, yi & 255, zi & 255
    u, v, w = _fade(xf), _fade(yf), _fade(zf)

    def g(ix, iy, iz, dx, dy, dz):  # noqa: ANN001, ANN202
        h = PERM[PERM[PERM[ix] + iy] + iz] % 12
        gr = GRAD[h]
        return gr[..., 0] * dx + gr[..., 1] * dy + gr[..., 2] * dz

    n000 = g(xi, yi, zi, xf, yf, zf)
    n100 = g(xi + 1, yi, zi, xf - 1, yf, zf)
    n010 = g(xi, yi + 1, zi, xf, yf - 1, zf)
    n110 = g(xi + 1, yi + 1, zi, xf - 1, yf - 1, zf)
    n001 = g(xi, yi, zi + 1, xf, yf, zf - 1)
    n101 = g(xi + 1, yi, zi + 1, xf - 1, yf, zf - 1)
    n011 = g(xi, yi + 1, zi + 1, xf, yf - 1, zf - 1)
    n111 = g(xi + 1, yi + 1, zi + 1, xf - 1, yf - 1, zf - 1)
    x00 = n000 + u * (n100 - n000)
    x10 = n010 + u * (n110 - n010)
    x01 = n001 + u * (n101 - n001)
    x11 = n011 + u * (n111 - n011)
    y0 = x00 + v * (x10 - x00)
    y1 = x01 + v * (x11 - x01)
    return y0 + w * (y1 - y0)


def fbm(p: np.ndarray, octaves: int, base: float) -> np.ndarray:
    total, amp, freq, norm = np.zeros(p.shape[:-1]), 1.0, base, 0.0
    for o in range(octaves):
        off = 17.3 * o
        total += amp * perlin3(p[..., 0] * freq + off, p[..., 1] * freq - off, p[..., 2] * freq + 2 * off)
        norm += amp
        amp *= 0.52
        freq *= 2.03
    return total / norm


def cloud_texture(w: int = 1024) -> None:
    h = w // 2
    lon = (np.arange(w) + 0.5) / w * 2 * np.pi - np.pi
    lat = np.pi / 2 - (np.arange(h) + 0.5) / h * np.pi
    lon, lat = np.meshgrid(lon, lat)
    p = np.stack([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)], axis=-1)
    # stretch east–west so cloud systems read as bands, then domain-warp for soft swirls
    p_s = p * np.array([1.0, 1.0, 1.9])
    warp = np.stack([fbm(p_s + 3.1, 3, 1.6), fbm(p_s - 7.7, 3, 1.6), fbm(p_s + 11.3, 3, 1.6)], axis=-1)
    n = fbm(p_s + 0.5 * warp, 7, 3.1)
    n = (n - n.min()) / (n.max() - n.min())
    deg = np.degrees(np.abs(lat))
    # where clouds live: ITCZ, mid-latitude storm tracks; fewer over the subtropical highs
    band = (0.55 + 0.30 * np.exp(-(deg / 9.0) ** 2) + 0.38 * np.exp(-((deg - 55) / 13.0) ** 2) - 0.30 * np.exp(-((deg - 24) / 8.0) ** 2))
    v = n * band
    lo, hi = np.quantile(v, 0.6), np.quantile(v, 0.995)
    c = np.clip((v - lo) / (hi - lo), 0, 1)
    c = c ** 1.35  # wispy edges, few solid decks
    img = Image.fromarray((c * 255).astype(np.uint8), "L").filter(ImageFilter.GaussianBlur(0.6))
    img.save(OUT / f"earth-clouds-{w // 1024}k.jpg", "JPEG", quality=80, optimize=True)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    if len(sys.argv) > 1:
        day_textures(Path(sys.argv[1]))
    cloud_texture(1024)
    for f in sorted(OUT.glob("*.jpg")):
        print(f.name, f.stat().st_size // 1024, "KB")
