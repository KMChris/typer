"""Renders the MSIX package assets and the Store listing images from the Typer icon design.

Pure Python like make_icon.py, whose renderer it reuses: no image library needed.

  python tools\\make_store_assets.py [--assets DIR] [--listing DIR]

Package assets (every scale and target size Windows asks for) go to --assets, the images
uploaded by hand in Partner Center (1:1 app tile icon, 16:9 hero art) go to --listing.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from make_icon import GRADIENT, coverage, png, rounded_box  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SCALES = {100: 1.0, 125: 1.25, 150: 1.5, 200: 2.0, 400: 4.0}
TARGET_SIZES = (16, 20, 24, 30, 32, 36, 40, 48, 60, 64, 72, 80, 96, 256)
# Windows composites tile images over the BackgroundColor from the manifest, so tiles keep a
# transparent background and the icon sits in the middle at this fraction of the shorter side.
TILE_ICON_FRACTION = 0.6
SPLASH_ICON_FRACTION = 0.5
HERO_BACKGROUND = (0x0E, 0x10, 0x16)  # --bg of the dark theme in ui/app.css
HERO_GLOWS = (((0x7C, 0x6C, 0xFF), -0.1, -0.2, 0.55, 0.32), ((0x2E, 0xC4, 0xE6), 1.1, 1.1, 0.5, 0.22))


def icon_pixel(x: float, y: float, size: float):
    """Colour and coverage of the icon (gradient tile with the T and caret) drawn at origin 0,0."""
    s = size / 32.0
    tile = coverage(rounded_box(x, y, 16 * s, 16 * s, 16 * s, 16 * s, 9 * s))
    if tile <= 0:
        return None
    t = (x + y) / (2 * size)
    base = [GRADIENT[0][i] + (GRADIENT[1][i] - GRADIENT[0][i]) * t for i in range(3)]
    glyph = max(
        coverage(rounded_box(x, y, 15.5 * s, 10 * s, 8 * s, 1.7 * s, 1.6 * s)),
        coverage(rounded_box(x, y, 15.5 * s, 16 * s, 1.7 * s, 7.5 * s, 1.6 * s)),
        coverage(rounded_box(x, y, 22.3 * s, 20 * s, 1.3 * s, 3.2 * s, 1.2 * s)),
    )
    return [base[i] + (255 - base[i]) * glyph for i in range(3)], tile


def hero_background(x: float, y: float, width: int, height: int) -> list[float]:
    """The dark app background with the two soft glows from the CSS."""
    color = list(HERO_BACKGROUND)
    for (r, g, b), cx, cy, radius, strength in HERO_GLOWS:
        dx = (x / width - cx) / radius
        dy = (y / height - cy) / radius
        falloff = max(0.0, 1.0 - math.sqrt(dx * dx + dy * dy)) ** 2 * strength
        color = [color[0] + (r - color[0]) * falloff, color[1] + (g - color[1]) * falloff, color[2] + (b - color[2]) * falloff]
    return color


def render(width: int, height: int, icon_size: float, background=None) -> bytes:
    """PNG of the icon centred on a canvas; `background` is None (transparent) or a callable."""
    ox, oy = (width - icon_size) / 2, (height - icon_size) / 2
    x0, x1 = max(0, math.floor(ox) - 1), min(width, math.ceil(ox + icon_size) + 1)
    y0, y1 = max(0, math.floor(oy) - 1), min(height, math.ceil(oy + icon_size) + 1)
    rows = []
    for y in range(height):
        row = bytearray()
        for x in range(width):
            px, py = x + 0.5, y + 0.5
            icon = icon_pixel(px - ox, py - oy, icon_size) if x0 <= x < x1 and y0 <= y < y1 else None
            if background is None:
                if icon is None:
                    row += b"\x00\x00\x00\x00"
                else:
                    color, alpha = icon
                    row += bytes(round(c) for c in color) + bytes([round(255 * alpha)])
                continue
            color = background(px, py, width, height)
            if icon is not None:
                over, alpha = icon
                color = [color[i] + (over[i] - color[i]) * alpha for i in range(3)]
            row += bytes(round(c) for c in color) + b"\xff"
        rows.append(b"\x00" + bytes(row))
    return png(width, height, b"".join(rows))


def package_assets() -> dict[str, tuple[int, int, float, bool]]:
    """name -> (width, height, icon size, full bleed). Unqualified base files have exactly the base size,
    which the App Certification Kit checks."""
    assets: dict[str, tuple[int, int, float, bool]] = {}

    def add(name: str, width: int, height: int, fraction: float | None) -> None:
        full_bleed = fraction is None
        assets[name] = (width, height, width if full_bleed else min(width, height) * fraction, full_bleed)

    for scale, factor in SCALES.items():
        add(f"Square44x44Logo.scale-{scale}.png", round(44 * factor), round(44 * factor), None)
        add(f"StoreLogo.scale-{scale}.png", round(50 * factor), round(50 * factor), None)
        add(f"Square150x150Logo.scale-{scale}.png", round(150 * factor), round(150 * factor), TILE_ICON_FRACTION)
        add(f"Square71x71Logo.scale-{scale}.png", round(71 * factor), round(71 * factor), TILE_ICON_FRACTION)
        add(f"Square310x310Logo.scale-{scale}.png", round(310 * factor), round(310 * factor), TILE_ICON_FRACTION)
        add(f"Wide310x150Logo.scale-{scale}.png", round(310 * factor), round(150 * factor), TILE_ICON_FRACTION)
        add(f"SplashScreen.scale-{scale}.png", round(620 * factor), round(300 * factor), SPLASH_ICON_FRACTION)
    for size in TARGET_SIZES:
        for suffix in ("", "_altform-unplated", "_altform-lightunplated"):
            add(f"Square44x44Logo.targetsize-{size}{suffix}.png", size, size, None)
    add("Square44x44Logo.png", 44, 44, None)
    add("StoreLogo.png", 50, 50, None)
    add("Square150x150Logo.png", 150, 150, TILE_ICON_FRACTION)
    add("Square71x71Logo.png", 71, 71, TILE_ICON_FRACTION)
    add("Square310x310Logo.png", 310, 310, TILE_ICON_FRACTION)
    add("Wide310x150Logo.png", 310, 150, TILE_ICON_FRACTION)
    add("SplashScreen.png", 620, 300, SPLASH_ICON_FRACTION)
    return assets


def write_package_assets(directory: Path) -> int:
    directory.mkdir(parents=True, exist_ok=True)
    cache: dict[tuple[int, int, float], bytes] = {}
    for name, (width, height, icon_size, _full_bleed) in package_assets().items():
        key = (width, height, icon_size)
        if key not in cache:
            cache[key] = render(width, height, icon_size)
        (directory / name).write_bytes(cache[key])
    return len(package_assets())


def write_listing_images(directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    tile = directory / "store-tile-icon-300x300.png"
    tile.write_bytes(render(300, 300, 300))
    written.append(tile)
    hero = directory / "store-hero-1920x1080.png"
    hero.write_bytes(render(1920, 1080, 360, background=hero_background))
    written.append(hero)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--assets", type=Path, default=ROOT / "build" / "msix" / "Assets")
    parser.add_argument("--listing", type=Path, default=ROOT / "dist" / "store" / "listing")
    args = parser.parse_args()
    count = write_package_assets(args.assets)
    print(f"wrote {count} package assets to {args.assets}")
    for path in write_listing_images(args.listing):
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
