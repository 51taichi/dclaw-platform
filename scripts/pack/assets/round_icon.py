#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate rounded desktop icons from one square source image.

The app icon source can be a JPG/PNG.  This script crops it to a square,
applies an anti-aliased transparent rounded-rectangle mask, then writes the
macOS/Windows/Tauri icon files used by the desktop packages.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw


REPO_ROOT = Path(__file__).resolve().parents[3]
PACK_ASSETS = REPO_ROOT / "scripts" / "pack" / "assets"
TAURI_ICONS = REPO_ROOT / "console" / "src-tauri" / "icons"

MAC_ICONSET_SIZES = (
    (16, "icon_16x16.png"),
    (32, "icon_16x16@2x.png"),
    (32, "icon_32x32.png"),
    (64, "icon_32x32@2x.png"),
    (128, "icon_128x128.png"),
    (256, "icon_128x128@2x.png"),
    (256, "icon_256x256.png"),
    (512, "icon_256x256@2x.png"),
    (512, "icon_512x512.png"),
    (1024, "icon_512x512@2x.png"),
)

PNG_TARGETS = {
    "32x32.png": 32,
    "64x64.png": 64,
    "128x128.png": 128,
    "128x128@2x.png": 256,
    "Square30x30Logo.png": 30,
    "Square44x44Logo.png": 44,
    "Square71x71Logo.png": 71,
    "Square89x89Logo.png": 89,
    "Square107x107Logo.png": 107,
    "Square142x142Logo.png": 142,
    "Square150x150Logo.png": 150,
    "Square284x284Logo.png": 284,
    "Square310x310Logo.png": 310,
    "StoreLogo.png": 50,
    "icon.png": 512,
    "app-icon.png": 1024,
    "app-icon-d1.png": 1024,
    "app-icon-v2.png": 1024,
    "app-icon-v3.png": 1024,
}

ANDROID_TARGETS = {
    "mipmap-mdpi": 48,
    "mipmap-hdpi": 72,
    "mipmap-xhdpi": 96,
    "mipmap-xxhdpi": 144,
    "mipmap-xxxhdpi": 192,
}

IOS_TARGETS = {
    "AppIcon-20x20@1x.png": 20,
    "AppIcon-20x20@2x.png": 40,
    "AppIcon-20x20@2x-1.png": 40,
    "AppIcon-20x20@3x.png": 60,
    "AppIcon-29x29@1x.png": 29,
    "AppIcon-29x29@2x.png": 58,
    "AppIcon-29x29@2x-1.png": 58,
    "AppIcon-29x29@3x.png": 87,
    "AppIcon-40x40@1x.png": 40,
    "AppIcon-40x40@2x.png": 80,
    "AppIcon-40x40@2x-1.png": 80,
    "AppIcon-40x40@3x.png": 120,
    "AppIcon-60x60@2x.png": 120,
    "AppIcon-60x60@3x.png": 180,
    "AppIcon-76x76@1x.png": 76,
    "AppIcon-76x76@2x.png": 152,
    "AppIcon-83.5x83.5@2x.png": 167,
    "AppIcon-512@2x.png": 1024,
}


def center_crop_square(image: Image.Image) -> Image.Image:
    width, height = image.size
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    return image.crop((left, top, left + side, top + side))


def rounded_icon(source: Path, size: int, radius_ratio: float) -> Image.Image:
    image = Image.open(source).convert("RGBA")
    image = center_crop_square(image).resize((size, size), Image.Resampling.LANCZOS)

    scale = 4
    mask_size = size * scale
    radius = int(size * radius_ratio * scale)
    mask = Image.new("L", (mask_size, mask_size), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle(
        (0, 0, mask_size - 1, mask_size - 1),
        radius=radius,
        fill=255,
    )
    mask = mask.resize((size, size), Image.Resampling.LANCZOS)
    image.putalpha(mask)
    return image


def save_resized(master: Image.Image, path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    master.resize((size, size), Image.Resampling.LANCZOS).save(path)


def save_icns(master: Image.Image, output: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "DClaw.iconset"
        iconset.mkdir()
        for size, name in MAC_ICONSET_SIZES:
            save_resized(master, iconset / name, size)

        iconutil = shutil.which("iconutil")
        if iconutil:
            subprocess.run(
                [iconutil, "-c", "icns", str(iconset), "-o", str(output)],
                check=True,
            )
            return

    master.save(output, format="ICNS")


def generate(source: Path, radius_ratio: float) -> None:
    master = rounded_icon(source, 1024, radius_ratio)

    PACK_ASSETS.mkdir(parents=True, exist_ok=True)
    TAURI_ICONS.mkdir(parents=True, exist_ok=True)

    for name in ("icon.png", "icon_rounded.png"):
        master.save(PACK_ASSETS / name)

    save_icns(master, PACK_ASSETS / "icon.icns")
    master.save(
        PACK_ASSETS / "icon.ico",
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )

    for filename, size in PNG_TARGETS.items():
        save_resized(master, TAURI_ICONS / filename, size)

    shutil.copy2(PACK_ASSETS / "icon.icns", TAURI_ICONS / "icon.icns")
    shutil.copy2(PACK_ASSETS / "icon.ico", TAURI_ICONS / "icon.ico")

    for dirname, size in ANDROID_TARGETS.items():
        folder = TAURI_ICONS / "android" / dirname
        for filename in (
            "ic_launcher.png",
            "ic_launcher_foreground.png",
            "ic_launcher_round.png",
        ):
            save_resized(master, folder / filename, size)

    ios_dir = TAURI_ICONS / "ios"
    for filename, size in IOS_TARGETS.items():
        save_resized(master, ios_dir / filename, size)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate rounded DClaw icons.")
    parser.add_argument(
        "source",
        nargs="?",
        default=str(PACK_ASSETS / "icon.png"),
        help="Source image path. Defaults to scripts/pack/assets/icon.png.",
    )
    parser.add_argument(
        "--radius-ratio",
        type=float,
        default=0.2237,
        help="Corner radius divided by icon size.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    generate(Path(args.source).expanduser().resolve(), args.radius_ratio)


if __name__ == "__main__":
    main()
