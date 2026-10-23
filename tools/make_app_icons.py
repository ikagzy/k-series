"""Turn the KO / KS logo PNGs (one per theme) into .ico files for src/k_optimizer/assets/AppIcons/<app>/.

Usage: python tools/make_app_icons.py ko <folder with ko-<theme>.png> ; python tools/make_app_icons.py ks <folder>
Needs Pillow (a build-time tool only; the apps themselves do not use it). Themes without a logo reuse `aurora`.
"""
import shutil
import sys
from pathlib import Path

from PIL import Image

SIZES = (16, 24, 32, 48, 64, 128, 256)
OUT = Path(__file__).resolve().parent.parent / "src" / "k_optimizer" / "assets" / "AppIcons"
THEMES = ("amber-orange", "aurora", "blue-cyan", "emerald-cyan", "midnight", "minimal", "violet-pink")


def square(img: Image.Image) -> Image.Image:
    img = img.convert("RGBA")
    box = img.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
    img = img.crop(box)
    side = max(img.size)
    pad = round(side * 0.04)
    canvas = Image.new("RGBA", (side + 2 * pad,) * 2, (0, 0, 0, 0))
    canvas.paste(img, ((canvas.width - img.width) // 2, (canvas.height - img.height) // 2), img)
    return canvas


def main(app: str, src: Path) -> None:
    dest = OUT / app
    dest.mkdir(parents=True, exist_ok=True)
    for theme in THEMES:
        png = src / f"{app}-{theme}.png"
        if png.is_file():
            big = square(Image.open(png)).resize((256, 256), Image.LANCZOS)
            big.save(dest / f"{theme}.ico", sizes=[(s, s) for s in SIZES])
    for theme in THEMES:
        if not (dest / f"{theme}.ico").is_file():
            shutil.copyfile(dest / "aurora.ico", dest / f"{theme}.ico")


if __name__ == "__main__":
    main(sys.argv[1], Path(sys.argv[2]))
