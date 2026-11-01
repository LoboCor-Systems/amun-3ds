"""Generate AMUN platform metal-tier trophy sources (64x64 RGBA PNG).

Deterministic, original artwork drawn with Pillow; no external art is used.
Alpha is forced to 0 or 255 so the images convert to RGBA5551 without
losing their silhouette. See docs/metal-tiers.md for the point bands.

    python scripts/make_metal_tiers.py                 # writes assets/branding/metal-tiers/*.png
    python scripts/make_metal_tiers.py --preview p.png # also writes a 4x contact sheet

Also writes the small-size variants (16 and 24 px) Studio bundles under
studio/assets/metal-tiers/. Colours come from compiler/metal_tiers.py.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "assets" / "branding" / "metal-tiers"

SIZE = 64
SCALE = 4  # supersample factor
OBSIDIAN = (9, 11, 13, 255)  # brand.md Obsidian #090B0D
LAPIS = (10, 47, 120, 255)  # brand.md Deep lapis #0A2F78
PAPYRUS = (243, 232, 203, 255)  # brand.md Papyrus #F3E8CB

# Colours and bands come from the shared table so art, Studio and plugin agree.
sys.path.insert(0, str(ROOT))
from compiler.metal_tiers import PALETTE, MetalTier  # noqa: E402

# name, rank (1-7), highlight, mid, shadow
TIERS: list[tuple[str, int, tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]] = [
    (tier.slug, int(tier), PALETTE[tier].highlight, PALETTE[tier].mid, PALETTE[tier].shadow)
    for tier in MetalTier
    if tier is not MetalTier.NONE
]

# Small UI sizes (Studio rows, future plugin chrome). Drawn from the same trophy
# geometry with heavier strokes and no rank pips, instead of shrinking the 64 px art.
SMALL_SIZES = (16, 24)
STUDIO_OUT = ROOT / "studio" / "assets" / "metal-tiers"


def _box(x0: float, y0: float, x1: float, y1: float) -> tuple[int, int, int, int]:
    return (round(x0 * SCALE), round(y0 * SCALE), round(x1 * SCALE), round(y1 * SCALE))


def _pts(*coords: tuple[float, float]) -> list[tuple[int, int]]:
    return [(round(x * SCALE), round(y * SCALE)) for x, y in coords]


def _cup_mask(handle_width: float = 3.0) -> Image.Image:
    """Metal parts: handles, bowl, rim, stem, knot, base plate."""
    big = SIZE * SCALE
    mask = Image.new("L", (big, big), 0)
    d = ImageDraw.Draw(mask)
    # handles (rings behind the bowl)
    d.ellipse(_box(5, 15, 21, 31), outline=255, width=round(handle_width * SCALE))
    d.ellipse(_box(43, 15, 59, 31), outline=255, width=round(handle_width * SCALE))
    # bowl: lower half of an ellipse, plus rim
    d.pieslice(_box(14, -10, 50, 38), 0, 180, fill=255)
    d.ellipse(_box(13, 10, 51, 17), fill=255)
    # stem, knot, top plate of plinth
    d.rectangle(_box(29.5, 36, 34.5, 46), fill=255)
    d.ellipse(_box(26, 40, 38, 45), fill=255)
    d.rectangle(_box(23, 46, 41, 49), fill=255)
    return mask


def _plinth_mask() -> Image.Image:
    big = SIZE * SCALE
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).polygon(_pts((19, 49), (45, 49), (48, 59), (16, 59)), fill=255)
    return mask


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], k: float) -> tuple[int, int, int]:
    return tuple(round(a[i] + (b[i] - a[i]) * k) for i in range(3))  # type: ignore[return-value]


def _metal_fill(mid: tuple[int, int, int], hi: tuple[int, int, int], sh: tuple[int, int, int]) -> Image.Image:
    """Left-lit metal gradient with a reflected-light lift on the far edge.

    Stops (x as a fraction of the width): 0.00 mid-high, 0.28 highlight,
    0.50 mid, 0.86 shadow, 1.00 shadow lifted towards mid (bounce light).
    The bounce is what makes it read as polished metal rather than flat paint.
    """
    big = SIZE * SCALE
    stops = (
        (0.00, _lerp(mid, hi, 0.55)),
        (0.28, hi),
        (0.50, mid),
        (0.86, sh),
        (1.00, _lerp(sh, mid, 0.45)),
    )
    row = Image.new("RGBA", (big, 1))
    for x in range(big):
        t = x / (big - 1)
        for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
            if t <= t1:
                row.putpixel((x, 0), _lerp(c0, c1, (t - t0) / (t1 - t0)) + (255,))
                break
    return row.resize((big, big), Image.Resampling.NEAREST)


def _glint(d: ImageDraw.ImageDraw, cx: float, cy: float, r: float, waist: float) -> None:
    d.polygon(_pts((cx, cy - r), (cx + waist, cy - waist), (cx + r, cy), (cx + waist, cy + waist),
                   (cx, cy + r), (cx - waist, cy + waist), (cx - r, cy), (cx - waist, cy - waist)), fill=PAPYRUS)


def render(rank: int, hi: tuple[int, int, int], mid: tuple[int, int, int], sh: tuple[int, int, int],
           size: int = SIZE) -> Image.Image:
    """Render one trophy at ``size`` px. Sizes below 32 use the small-size variant:
    heavier handles and outline, no rank pips (colour + glint carry the tier)."""
    small = size < 32
    big = SIZE * SCALE
    cup = _cup_mask(handle_width=5.0 if small else 3.0)
    plinth = _plinth_mask()

    art = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    art.paste(_metal_fill(mid, hi, sh), (0, 0), cup)

    d = ImageDraw.Draw(art)
    # rim opening (dark inside of the cup) and specular streaks on the bowl
    d.ellipse(_box(16, 11.5, 48, 15.5), fill=sh + (255,))
    d.ellipse(_box(18, 12, 46, 14.5), fill=_lerp(mid, sh, 0.5) + (255,))
    if small:
        d.rounded_rectangle(_box(18, 18, 24, 31), radius=2 * SCALE, fill=hi + (255,))
    else:
        d.rounded_rectangle(_box(19, 18, 22, 30), radius=SCALE, fill=hi + (255,))
        d.ellipse(_box(23, 32, 25, 34), fill=hi + (255,))
        # thin rim light along the top of the rim
        d.arc(_box(13, 10, 51, 17), 190, 300, fill=hi + (255,), width=SCALE)
        # knot highlight
        d.ellipse(_box(28, 41, 31, 43), fill=hi + (255,))

    # plinth in brand lapis with rank pips in papyrus
    art.paste(Image.new("RGBA", (big, big), LAPIS), (0, 0), plinth)
    if not small:
        pip, gap = 2.5, 1.5
        width = rank * pip + (rank - 1) * gap
        x = 32 - width / 2
        for _ in range(rank):
            d.ellipse(_box(x, 52.75, x + pip, 55.25), fill=PAPYRUS)
            x += pip + gap

    # top tiers: four-point glint (platinum one, rhodium two)
    if rank >= 6:
        if small:
            _glint(d, 54.0, 8.0, 9.0 if rank == 7 else 7.5, 2.0)
        else:
            _glint(d, 53.0, 8.0, 6.0 if rank == 7 else 4.5, 1.0)
            if rank == 7:
                _glint(d, 10.0, 40.0, 3.5, 0.8)

    # obsidian outline around everything (thicker when small so it survives downsampling)
    outline = 3.5 if small else 1.25
    silhouette = art.getchannel("A").point(lambda v: 255 if v else 0)
    grow = silhouette.filter(ImageFilter.MaxFilter(2 * round(outline * SCALE) + 1))
    out = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    out.paste(Image.new("RGBA", (big, big), OBSIDIAN), (0, 0), grow)
    out.alpha_composite(art)

    reduced = out.resize((size, size), Image.Resampling.LANCZOS)
    # binary alpha for RGBA5551; colour channels are already un-premultiplied by Pillow
    alpha = reduced.getchannel("A").point(lambda v: 255 if v >= 128 else 0)
    rgb = reduced.convert("RGB")
    result = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    result.paste(rgb, (0, 0), alpha)
    return result


def contact_sheet(images: list[Image.Image], zoom: int = 4) -> Image.Image:
    cell = SIZE * zoom
    sheet = Image.new("RGBA", (cell * len(images), cell * 2), (0, 0, 0, 255))
    for i, img in enumerate(images):
        up = img.resize((cell, cell), Image.Resampling.NEAREST)
        for row, bg in enumerate(((7, 26, 54, 255), (243, 232, 203, 255))):  # Midnight, Papyrus
            tile = Image.new("RGBA", (cell, cell), bg)
            tile.alpha_composite(up)
            sheet.paste(tile, (i * cell, row * cell))
    return sheet


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--studio-out", type=Path, default=STUDIO_OUT,
                        help="small 16/24 px variants bundled with Studio")
    parser.add_argument("--preview", type=Path, help="optional contact-sheet PNG (not part of the asset set)")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    args.studio_out.mkdir(parents=True, exist_ok=True)
    images = []
    for name, rank, hi, mid, sh in TIERS:
        img = render(rank, hi, mid, sh)
        img.save(args.out / f"{name}.png", optimize=True)
        images.append(img)
        print(f"wrote {args.out / (name + '.png')}")
        for size in SMALL_SIZES:
            target = args.studio_out / f"{name}-{size}.png"
            render(rank, hi, mid, sh, size).save(target, optimize=True)
            print(f"wrote {target}")
    if args.preview:
        contact_sheet(images).save(args.preview)
        print(f"wrote {args.preview}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
