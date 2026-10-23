"""Write a PyInstaller --version-file for an exe, taking the number from the package's __version__.

PyInstaller embeds no version resource by itself; K-Series reads it to tell which version of K-Optimizer is
installed. Usage: python tools/make_version.py <package> <product name> <exe name> <output file>"""
import importlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def version_tuple(text: str) -> tuple[int, int, int, int]:
    nums = [int(n) for n in re.findall(r"\d+", text)][:4]
    if not nums:
        raise ValueError(f"not a version number: {text!r}")
    return tuple(nums + [0] * (4 - len(nums)))  # type: ignore[return-value]


def render(product: str, description: str, version: str, exe_name: str) -> str:
    v = version_tuple(version)
    dotted = ".".join(map(str, v))
    return f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={v}, prodvers={v}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'itzkagzy'),
      StringStruct('FileDescription', '{description}'),
      StringStruct('FileVersion', '{dotted}'),
      StringStruct('InternalName', '{product}'),
      StringStruct('OriginalFilename', '{exe_name}'),
      StringStruct('ProductName', '{product}'),
      StringStruct('ProductVersion', '{dotted}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def main(argv: list[str]) -> None:
    package, product, exe_name, out = argv
    version = importlib.import_module(package).__version__
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(render(product, product, version, exe_name), encoding="utf-8")
    print(f"{product} {version} -> {out}")


if __name__ == "__main__":
    main(sys.argv[1:])
