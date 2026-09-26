"""Draw the app icons (crimson tile, white map pin with fork and knife) into web/icons/.

    python tools/make_icons.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "web" / "icons"
CRIMSON, WHITE = (165, 28, 48), (255, 255, 255)


def draw(size, safe=1.0, rounded=False):
    """safe < 1 shrinks the glyph into the maskable-icon safe zone (Android crops to a circle)."""
    s = size * 4                                   # draw large, then downsample for smooth edges
    img = Image.new("RGBA", (s, s), CRIMSON + (255,))
    if rounded:
        mask = Image.new("L", (s, s), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=255)
        img.putalpha(mask)
    d = ImageDraw.Draw(img)
    g = s * 0.62 * safe                            # glyph height
    cx, top = s / 2, (s - g) / 2
    r = g * 0.36                                   # pin head radius
    cy = top + r
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=WHITE)
    d.polygon([(cx - r * 0.86, cy + r * 0.5), (cx + r * 0.86, cy + r * 0.5), (cx, top + g)], fill=WHITE)
    # fork (left) and knife (right) in crimson inside the pin head
    lw = max(2, int(r * 0.09))
    fx, kx = cx - r * 0.3, cx + r * 0.3
    y0, y1, y2 = cy - r * 0.62, cy - r * 0.08, cy + r * 0.62
    for dx in (-r * 0.14, 0, r * 0.14):
        d.line([(fx + dx, y0), (fx + dx, y1)], fill=CRIMSON, width=lw)
    d.rounded_rectangle([fx - r * 0.17, y1 - lw, fx + r * 0.17, y1 + r * 0.14], radius=lw, fill=CRIMSON)
    d.line([(fx, y1), (fx, y2)], fill=CRIMSON, width=int(lw * 1.4))
    d.pieslice([kx - r * 0.2, y0, kx + r * 0.2, y1 + r * 0.25], 180, 360, fill=CRIMSON)
    d.rectangle([kx - r * 0.2, (y0 + y1 + r * 0.25) / 2, kx + r * 0.02, y1 + r * 0.12], fill=CRIMSON)
    d.line([(kx - r * 0.05, y1), (kx - r * 0.05, y2)], fill=CRIMSON, width=int(lw * 1.4))
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    draw(192).save(OUT / "icon-192.png")
    draw(512).save(OUT / "icon-512.png")
    draw(512, safe=0.78).save(OUT / "icon-maskable-512.png")
    draw(180).convert("RGB").save(OUT / "apple-touch-icon.png")      # iOS wants no transparency
    draw(64, rounded=True).save(OUT / "favicon-64.png")
    print("icons written to", OUT)
