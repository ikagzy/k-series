"""K-Launcher's design system, taken from its source (MainWindow.xaml.cs AccentPalettes + Themes/KTheme.xaml).

K-Optimizer follows the theme the user picked in K-Launcher (%APPDATA%/K-Launcher/theme.txt) and its
motion speed setting (motion.txt), so the two apps always look alike.
"""
import time
from dataclasses import dataclass
from pathlib import Path

from k_optimizer import klauncher


@dataclass(frozen=True)
class Palette:
    id: str
    name: str
    primary: str
    secondary: str
    background: str
    surface: str
    card: str
    control: str
    outline: str


def _hex(r: int, g: int, b: int) -> str:
    return f"#{r:02X}{g:02X}{b:02X}"


_NEUTRAL = ((16, 16, 20), (17, 17, 22), (19, 19, 25), (20, 25, 26), (27, 27, 36))


def _p(id_, name, primary, secondary, neutrals=_NEUTRAL) -> Palette:
    return Palette(id_, name, _hex(*primary), _hex(*secondary), *(_hex(*c) for c in neutrals))


PALETTES: dict[str, Palette] = {p.id: p for p in (
    _p("emerald-cyan", "Emerald + Cyan", (0, 255, 102), (0, 217, 255)),
    _p("violet-pink", "Violet + Pink", (177, 92, 255), (255, 85, 180)),
    _p("blue-cyan", "Blue + Cyan", (64, 132, 255), (0, 225, 230)),
    _p("amber-orange", "Amber + Orange", (255, 190, 64), (255, 105, 64)),
    _p("midnight", "Midnight", (112, 166, 255), (55, 93, 160),
       ((10, 15, 26), (14, 21, 36), (17, 26, 43), (22, 32, 52), (38, 54, 78))),
    _p("aurora", "Aurora", (77, 255, 190), (142, 91, 255),
       ((12, 17, 23), (16, 24, 32), (20, 30, 39), (25, 37, 44), (38, 56, 62))),
    _p("minimal", "Minimal", (235, 235, 240), (125, 132, 144),
       ((18, 19, 22), (24, 25, 29), (29, 30, 35), (37, 38, 43), (48, 49, 56))),
)}
DEFAULT_ID = "emerald-cyan"

# Neutrals shared by every theme (KTheme.xaml)
TEXT = "#ECECF1"
TEXT_MUTED = "#9A9AA6"
TEXT_FAINT = "#686874"
DANGER = "#FF5C6C"
ON_ACCENT = "#0A0D0B"
OUTLINE_STRONG = "#2A2A36"

# Type (KTheme.xaml): first family that is installed wins.
UI_FONTS = ("Segoe UI Variable Text", "Segoe UI")
DISPLAY_FONTS = ("Bahnschrift SemiCondensed", "Bahnschrift", "Segoe UI")
# Corner radii S / M / L / XL
RADIUS = (4, 8, 12, 16)

_MOTION = {"fast": 0.55, "normal": 1.0, "slow": 1.6, "off": 0.0}


_CACHE_SECONDS = 20.0
_hint: Path | None = None
_cache: tuple[float, Path | None] | None = None


def set_launcher_hint(path: Path | None) -> None:
    """A user-chosen K-Launcher location, tried right after a running copy."""
    global _hint
    _hint = path
    reset_launcher_cache()


def reset_launcher_cache() -> None:
    global _cache
    _cache = None


def launcher_exe() -> Path | None:
    """The K-Launcher whose settings we follow; cached because the theme is polled every couple of seconds."""
    global _cache
    now = time.monotonic()
    if _cache is None or now - _cache[0] > _CACHE_SECONDS:
        _cache = (now, klauncher.find_exe(saved=_hint, scan_roots=[]))
    return _cache[1]


def data_dirs() -> list[Path]:
    return klauncher.data_dirs(launcher_exe())


def _read_setting(name: str, dirs: list[Path] | None = None) -> str | None:
    for d in dirs if dirs is not None else data_dirs():
        try:
            return (d / name).read_text(encoding="utf-8").strip().lower()
        except (OSError, ValueError):
            continue
    return None


def load(theme_file: Path | None = None) -> Palette:
    """The palette selected in K-Launcher; the default when unset, unknown or unreadable."""
    if theme_file is not None:
        try:
            name = theme_file.read_text(encoding="utf-8").strip().lower()
        except (OSError, ValueError):
            name = None
    else:
        name = _read_setting("theme.txt")
    return PALETTES.get(name or "", PALETTES[DEFAULT_ID])


def motion_scale(dirs: list[Path] | None = None) -> float:
    """K-Launcher's animation speed setting as a duration multiplier (0 = animations off)."""
    word = _read_setting("motion.txt", dirs)
    return _MOTION.get(word or "", 1.0)


def _write_setting(name: str, value: str) -> bool:
    """Write where K-Launcher reads it: the folder that already has the file, else its current Data folder."""
    dirs = data_dirs()
    target = next((d for d in dirs if (d / name).is_file()), dirs[0])
    try:
        target.mkdir(parents=True, exist_ok=True)
        (target / name).write_text(value, encoding="utf-8")
        return True
    except OSError:
        return False


def save(palette_id: str) -> bool:
    """Select a theme for every K app. False when the id is unknown or the file cannot be written."""
    return palette_id in PALETTES and _write_setting("theme.txt", palette_id)


def save_motion(word: str) -> bool:
    return word.lower() in _MOTION and _write_setting("motion.txt", word.lower())


def _rgb(c: str) -> tuple[int, int, int]:
    return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)


def blend(a: str, b: str, t: float) -> str:
    """Colour at fraction t of the way from a to b (tk has no alpha, so soft tones are pre-blended)."""
    ra, rb = _rgb(a), _rgb(b)
    return _hex(*(round(x + (y - x) * t) for x, y in zip(ra, rb)))


def accent_soft(p: Palette) -> str:
    return blend(p.background, p.primary, 0.14)  # K.AccentSoft = accent at 0x24 alpha


def accent_line(p: Palette) -> str:
    return blend(p.background, p.primary, 0.40)  # K.AccentLine = accent at 0x66 alpha


def arc_colors(frac: float, p: Palette, segments: int = 54) -> list[str]:
    """Colours for the filled part of a dial: primary to secondary along the sweep, red when nearly full."""
    n = max(0, min(segments, round(frac * segments)))
    if frac >= 0.9:
        return [DANGER] * segments
    return [blend(p.primary, p.secondary, i / max(1, segments - 1)) for i in range(n)]
