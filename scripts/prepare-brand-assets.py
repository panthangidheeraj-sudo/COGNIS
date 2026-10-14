"""Build the COGNIS logo files in public/brand/ from the supplied Atlas artwork.

Run once; the outputs are committed, so the app never runs this.

    pip install pillow numpy
    python scripts/prepare-brand-assets.py

Source
  public/brand/cognis-atlas-reference.png (1254x1254, navy ink on an ivory ground). It is never modified.

What it makes (all in public/brand/)
  cognis-atlas-navy.png    transparent, original ink colour    -> light theme
  cognis-atlas-ivory.png   transparent, original paper colour  -> dark theme
  cognis-atlas-*-sm.png    the same two, pre-sized for the 24-64 px placements (rail, mobile header)
  favicon-16/32/48.png, favicon.ico, apple-touch-icon.png, icon-192.png, icon-512.png
                           the artwork as supplied (navy emblem on its own ivory ground) on a rounded tile

How the transparent versions are made (no crude background removal)
  The artwork is two inks: one dark colour on one ivory colour, with anti-aliased edges. Every pixel is
  therefore a mix of those two colours, and its mix ratio IS the opacity. We solve for that ratio
  (the pixel's position on the line between the paper colour and the ink colour), so an edge pixel that is
  30% ink becomes ink at 30% opacity. There is no colour threshold, no flood fill and no feathering, so
  the silhouette, the thin orbit line and the knocked-out orbit gap through the C are exactly the supplied
  artwork. Only the faint JPEG ringing around edges (under 4% opacity) is cleared.
  The ivory version has the same opacity map with the paper colour as ink: figure and ground swap, the
  shape does not change.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / "public" / "brand"
SRC = BRAND / "cognis-atlas-reference.png"

CLIP_LO, CLIP_HI = 0.04, 0.96  # opacity below/above these is JPEG ringing, not artwork
PAD = 0.025  # breathing room around the emblem in the cropped files, as a share of its height
SM_HEIGHT = 160  # px tall; shown at 24-64 css px, so this covers 2.5x displays
TILE_BG_PAD = 0.07  # empty margin inside favicon tiles, share of the tile side


def load_reference() -> np.ndarray:
    return np.asarray(Image.open(SRC).convert("RGB")).astype(np.float64)


def sample_inks(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Median colour of the clearly-dark pixels (ink) and the clearly-light ones (paper)."""
    lum = rgb @ np.array([0.2126, 0.7152, 0.0722])
    return np.median(rgb[lum < 60], axis=0), np.median(rgb[lum > 230], axis=0)


def opacity_map(rgb: np.ndarray, ink: np.ndarray, paper: np.ndarray) -> np.ndarray:
    """0..1 ink share of each pixel: its projection on the paper->ink line."""
    axis = ink - paper
    t = ((rgb - paper) @ axis) / float(axis @ axis)
    t = np.clip(t, 0.0, 1.0)
    return np.clip((t - CLIP_LO) / (CLIP_HI - CLIP_LO), 0.0, 1.0)


def emblem_box(alpha: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.where(alpha > 0.5)
    h = ys.max() - ys.min() + 1
    pad = int(round(h * PAD))
    h_img, w_img = alpha.shape
    return max(xs.min() - pad, 0), max(ys.min() - pad, 0), min(xs.max() + 1 + pad, w_img), min(ys.max() + 1 + pad, h_img)


def solid(alpha: np.ndarray, colour: np.ndarray) -> Image.Image:
    """RGBA with ONE colour everywhere and the opacity map as alpha (no dark/light fringe when a browser resamples it)."""
    h, w = alpha.shape
    out = np.empty((h, w, 4), dtype=np.uint8)
    out[..., :3] = np.round(colour).astype(np.uint8)
    out[..., 3] = np.round(alpha * 255).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def resize_height(img: Image.Image, height: int) -> Image.Image:
    w = round(img.width * height / img.height)
    return img.resize((w, height), Image.LANCZOS)


def tile(alpha_img_navy: Image.Image, paper: np.ndarray, size: int, *, radius: float, pad: float = TILE_BG_PAD, sharpen: bool = False) -> Image.Image:
    """The artwork as supplied (navy on ivory) on a square tile. Built at 8x and averaged down."""
    big = size * 8
    canvas = Image.new("RGBA", (big, big), tuple(int(round(c)) for c in paper) + (255,))
    inner = big * (1 - 2 * pad)
    em = alpha_img_navy
    scale = inner / em.height
    em = em.resize((max(1, round(em.width * scale)), round(inner)), Image.LANCZOS)
    canvas.alpha_composite(em, ((big - em.width) // 2, (big - em.height) // 2))
    if radius > 0:
        mask = Image.new("L", (big, big), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, big - 1, big - 1), radius=int(big * radius), fill=255)
        canvas.putalpha(mask)
    out = canvas.resize((size, size), Image.LANCZOS)
    if sharpen:
        from PIL import ImageFilter

        rgb = out.convert("RGB").filter(ImageFilter.UnsharpMask(radius=0.6, percent=60, threshold=0))
        rgb.putalpha(out.getchannel("A"))
        out = rgb
    return out


def main() -> None:
    rgb = load_reference()
    ink, paper = sample_inks(rgb)
    alpha = opacity_map(rgb, ink, paper)
    box = emblem_box(alpha)
    alpha = alpha[box[1] : box[3], box[0] : box[2]]
    print(f"ink {ink.round().astype(int).tolist()}  paper {paper.round().astype(int).tolist()}  crop {box}  -> {alpha.shape[1]}x{alpha.shape[0]}")

    navy, ivory = solid(alpha, ink), solid(alpha, paper)
    navy.save(BRAND / "cognis-atlas-navy.png", optimize=True)
    ivory.save(BRAND / "cognis-atlas-ivory.png", optimize=True)
    resize_height(navy, SM_HEIGHT).save(BRAND / "cognis-atlas-navy-sm.png", optimize=True)
    resize_height(ivory, SM_HEIGHT).save(BRAND / "cognis-atlas-ivory-sm.png", optimize=True)

    # favicons / app icons: small sizes use a tighter margin and a touch of sharpening so the silhouette survives
    icons = {
        "favicon-16.png": tile(navy, paper, 16, radius=0.2, pad=0.04, sharpen=True),
        "favicon-32.png": tile(navy, paper, 32, radius=0.2, pad=0.05, sharpen=True),
        "favicon-48.png": tile(navy, paper, 48, radius=0.2, pad=0.06),
        "apple-touch-icon.png": tile(navy, paper, 180, radius=0, pad=0.1),  # iOS rounds the corners itself
        "icon-192.png": tile(navy, paper, 192, radius=0.2, pad=0.08),
        "icon-512.png": tile(navy, paper, 512, radius=0.2, pad=0.08),
    }
    for name, im in icons.items():
        im.save(BRAND / name, optimize=True)
    icons["favicon-48.png"].save(BRAND / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)], append_images=[icons["favicon-32.png"], icons["favicon-16.png"]])


if __name__ == "__main__":
    main()
