"""Draw the FFFFE crest and the app icons made from it.

    python tools/make_icons.py

The crest is our own, in the manner of Harvard's House arms (not Harvard's VERITAS shield, which is a
protected mark): a crimson shield; a gold chief with three crimson stars, the fantastic events; a fork and
a quill in saltire, free food and the fellows who write; and the motto PRANDIUM GRATIS, "free lunch".

Writes web/crest.svg (with motto, for the About tab), web/crest-shield.svg (shield only, for the header)
and the PNG icons in web/icons/. The PNGs are rendered by a headless Edge or Chrome; set FFM_BROWSER to the
browser's path if it is not found.
"""
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"
ICONS = WEB / "icons"

CRIMSON, CRIMSON_DARK = "#A51C30", "#6B1020"
GOLD, GOLD_DARK = "#CDA349", "#8E6A1F"
WHITE, CREAM, CREAM_DARK = "#FFFFFF", "#F6EEDC", "#DCCBA3"
TILE = "#F7F6F5"                         # the site's background, behind the icons

SHIELD = "M20,10 H180 V100 C180,158 142,190 100,208 C58,190 20,158 20,100 Z"


def star(cx, cy, r):
    pts = []
    for k in range(10):
        a = -math.pi / 2 + k * math.pi / 5
        rr = r if k % 2 == 0 else r * 0.42
        pts.append(f"{cx + rr * math.cos(a):.2f},{cy + rr * math.sin(a):.2f}")
    return f'<polygon points="{" ".join(pts)}" fill="{CRIMSON}"/>'


def fork():
    """Upright fork centred on 0,0, tines up."""
    tines = "".join(f'<rect x="{x:.2f}" y="-60" width="4.6" height="46" rx="2.3"/>' for x in (-15, -6.53, 1.93, 10.4))
    return (f'<g fill="{WHITE}" stroke="{CRIMSON}" stroke-width="2.4" paint-order="stroke">'
            f'{tines}<rect x="-15" y="-22" width="30" height="15" rx="6"/>'
            f'<path d="M-11,-9 L11,-9 L5,10 L-5,10 Z"/><rect x="-4.8" y="6" width="9.6" height="58" rx="4.8"/></g>')


def quill():
    """Upright quill centred on 0,0, nib down."""
    return (f'<g stroke-linecap="round">'
            f'<path d="M3,30 C-17,8 -21,-32 -2,-64 C13,-38 17,-6 7,28 Z" fill="{CREAM}" stroke="{CRIMSON_DARK}" stroke-width="2.4"/>'
            f'<path d="M1,-56 C2,-20 3,10 1.5,46" fill="none" stroke="{GOLD}" stroke-width="2.6"/>'
            + "".join(f'<path d="M1.6,{y} L{-9 + (y + 60) * 0.02:.1f},{y - 9}" stroke="{GOLD}" stroke-width="1.6"/>'
                      for y in (-36, -20, -4, 12))
            + f'<path d="M-2.2,40 L2.6,40 L0.6,66 Z" fill="{CRIMSON_DARK}"/></g>')


def shield_svg():
    return (f'<defs><clipPath id="sh"><path d="{SHIELD}"/></clipPath></defs>'
            f'<g clip-path="url(#sh)">'
            f'<rect x="0" y="0" width="200" height="220" fill="{CRIMSON}"/>'
            f'<rect x="0" y="0" width="200" height="60" fill="{GOLD}"/>'
            f'<path d="M20,60 H180" stroke="{CRIMSON_DARK}" stroke-width="2"/>'
            f'{star(56, 36, 14)}{star(100, 36, 14)}{star(144, 36, 14)}'
            f'<g transform="translate(100 133) rotate(-38) scale(1.02)">{quill()}</g>'
            f'<g transform="translate(100 133) rotate(38) scale(.92)">{fork()}</g>'
            f'</g><path d="{SHIELD}" fill="none" stroke="{CRIMSON_DARK}" stroke-width="4" stroke-linejoin="round"/>')


def motto_svg():
    tail = f'fill="{CREAM_DARK}" stroke="{GOLD_DARK}" stroke-width="1.5" stroke-linejoin="round"'
    return (f'<path d="M22,212 L2,218 L12,229 L2,244 L20,242 Z" {tail}/>'
            f'<path d="M178,212 L198,218 L188,229 L198,244 L180,242 Z" {tail}/>'
            f'<path d="M20,212 Q100,236 180,212 L183,242 Q100,266 17,242 Z" fill="{CREAM}" stroke="{GOLD_DARK}" '
            f'stroke-width="1.5" stroke-linejoin="round"/>'
            f'<path id="mottoLine" d="M24,232 Q100,256 176,232" fill="none"/>'
            f'<text font-family="Georgia, Times New Roman, serif" font-size="12.5" font-weight="700" '
            f'letter-spacing="1.3" fill="{CRIMSON_DARK}"><textPath href="#mottoLine" startOffset="50%" '
            f'text-anchor="middle">PRANDIUM GRATIS</textPath></text>')


def write_svgs():
    head = '<svg xmlns="http://www.w3.org/2000/svg" role="img" '
    (WEB / "crest.svg").write_text(
        head + 'viewBox="0 0 200 270"><title>FFFFE crest: Prandium gratis</title>'
        + shield_svg() + motto_svg() + "</svg>\n", encoding="utf-8")
    (WEB / "crest-shield.svg").write_text(
        head + 'viewBox="16 6 168 206"><title>FFFFE crest</title>' + shield_svg() + "</svg>\n", encoding="utf-8")


def browser():
    found = os.environ.get("FFM_BROWSER")
    for c in [found, r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              shutil.which("chromium"), shutil.which("google-chrome"), shutil.which("msedge")]:
        if c and Path(c).exists():
            return c
    raise SystemExit("No Edge or Chrome found for rendering; set FFM_BROWSER")


def render(name, size, shield_height, background):
    """Shield centred on a square tile; background None = transparent."""
    svg = (WEB / "crest-shield.svg").as_uri()
    bg = background or "transparent"
    html = (f'<!doctype html><html><body style="margin:0;width:{size}px;height:{size}px;background:{bg};'
            f'display:grid;place-items:center;overflow:hidden">'
            f'<img src="{svg}" style="height:{shield_height}px;display:block"></body></html>')
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "icon.html"
        page.write_text(html, encoding="utf-8")
        out = Path(tmp) / "out.png"
        subprocess.run([browser(), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                        "--default-background-color=00000000", f"--window-size={size},{size}",
                        f"--screenshot={out}", page.as_uri()], check=True, capture_output=True, timeout=60)
        shutil.copy(out, ICONS / name)


def main():
    write_svgs()
    ICONS.mkdir(exist_ok=True)
    render("icon-512.png", 512, 430, TILE)
    render("icon-192.png", 192, 160, TILE)
    render("icon-maskable-512.png", 512, 300, TILE)      # Android crops to a circle: keep inside the safe zone
    render("apple-touch-icon.png", 180, 146, TILE)
    render("favicon-64.png", 64, 62, None)
    print("wrote crest.svg, crest-shield.svg and icons/*.png")


if __name__ == "__main__":
    main()
