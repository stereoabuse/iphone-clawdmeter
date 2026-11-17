"""Convert Clawdmeter's firmware animation data into web/clawd.json.

Usage: uv run python tools/convert_art.py [path/to/splash_animations.h]
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SRC = ROOT / "vendor/Clawdmeter/firmware/src/splash_animations.h"
OUT = ROOT / "web/clawd.json"

ARRAY_RE = re.compile(r"static const uint(?:8|16)_t (splash_\w+)\[\d+\] = \{(.*?)\};", re.S)
DEF_RE = re.compile(
    r'\{"([^"]+)", "(\w+)", (\d+), (\d+), (\d+), (\d+), (\d+), (\d+), (\d+), (\d+), '
    r"(splash_\w+), (splash_\w+), (splash_\w+)\}"
)


def rgb565_to_hex(v: int) -> str:
    r = (v >> 11) & 0x1F
    g = (v >> 5) & 0x3F
    b = v & 0x1F
    return f"#{r * 255 // 31:02x}{g * 255 // 63:02x}{b * 255 // 31:02x}"


def parse(src: str) -> list[dict]:
    arrays = {
        name: [int(x, 0) for x in body.replace("\n", " ").split(",") if x.strip()]
        for name, body in ARRAY_RE.findall(src)
    }
    anims = []
    for m in DEF_RE.finditer(src):
        name, cat, w, h, ox, oy, fc, ls, le, pc, pal, frames, holds = m.groups()
        w, h, ox, oy, fc, ls, le, pc = map(int, (w, h, ox, oy, fc, ls, le, pc))
        cells = arrays[frames]
        assert len(cells) == fc * w * h, name
        assert max(cells) < 16, name
        flat = "".join(f"{c:x}" for c in cells)
        anims.append({
            "name": name,
            "category": cat,
            "w": w, "h": h, "ox": ox, "oy": oy,
            "loop": [ls, le],
            "palette": [None] + [rgb565_to_hex(v) for v in arrays[pal][1:pc]],
            "holds": arrays[holds][:fc],
            "frames": [flat[i * w * h:(i + 1) * w * h] for i in range(fc)],
        })
    return anims


def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SRC
    anims = parse(src.read_text(encoding="utf-8"))
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"stage": [55, 37], "anims": anims}, separators=(",", ":")), encoding="utf-8")
    print(f"{len(anims)} animations -> {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
