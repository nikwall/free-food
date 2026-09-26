"""Prepare the claude.ai-hosted copy of the site in artifact/.

The hosted page gets its <html>/<head>/<body> skeleton from claude.ai, runs in a frame
without service workers, and keeps Going/Skip votes in its own shared database instead of
serve.py. This writes artifact/index.html from web/index.html; the other files are published
straight from web/ and data/ (see README, "Hosting on claude.ai").

    python tools/build_artifact.py
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC, OUT = ROOT / "web" / "index.html", ROOT / "artifact" / "index.html"

# published path -> source file, relative to the project folder
FILES = {
    "app.js": "web/app.js",
    "style.css": "web/style.css",
    "vendor/leaflet.css": "web/vendor/leaflet.css",
    "basemap.json": "web/basemap.json",
    "events.json": "data/events.json",
}

HOSTED_INSTALL = """<h3>On your phone</h3>
    <p>Open this page's link on your phone while signed in to Claude. This copy shows the latest scan
      that was published to it; the “Updated” time says when that was.</p>"""


def main():
    html = SRC.read_text(encoding="utf-8")
    html = re.sub(r"<!doctype html>\s*|</?html[^>]*>\s*|</?head>\s*|</?body>\s*", "", html, flags=re.I)
    drop = (r'<meta charset[^>]*>', r'<meta name="viewport"[^>]*>', r'<meta name="theme-color"[^>]*>',
            r'<meta name="(?:apple-)?mobile-web-app[^"]*"[^>]*>', r'<link rel="(?:manifest|icon|apple-touch-icon)"[^>]*>')
    for rx in drop:
        html = re.sub(rx + r"\s*", "", html)
    html = re.sub(r"\?v=\d+", "", html)                       # cache-busting is for the local server only
    html = re.sub(r'<script src="config\.js"></script>\s*', "", html)    # web-host voting config; not used here
    html = re.sub(r"<h3>Install on your phone</h3>\s*<p>.*?</p>", HOSTED_INSTALL, html, flags=re.S)
    html = html.replace("</title>\n", '</title>\n<script>document.documentElement.classList.add("in-artifact")</script>\n', 1)
    assert html.lstrip().startswith("<title>"), "the <title> must come first"
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    missing = [src for src in FILES.values() if not (ROOT / src).exists()]
    print(f"wrote {OUT.relative_to(ROOT)} ({len(html) // 1024} KB)" + (f"; MISSING: {missing}" if missing else ""))


if __name__ == "__main__":
    main()
