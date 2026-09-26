"""Host the Free Food Map locally and keep it fresh.

    python serve.py                   # http://localhost:8765, rescans every 3 hours
    python serve.py --interval 1      # rescan every hour
    python serve.py --lan             # also reachable from other devices on your network
    python serve.py --no-scan         # just serve the current data/events.json

API used by the page: GET /events.json, GET /api/status, POST /api/scan,
GET /api/votes?device=ID, POST /api/vote {event_id, device, vote: going|skip|null, name?},
POST /api/name {device, name}.

The page is static (web/ + data/events.json), so the same files can later be
put on any static host with a scheduled `python scan.py`.
"""
import argparse
import os
import json
import sys
import threading
import time
import webbrowser
from datetime import datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from freefood.config import EVENTS_FILE, TZ, WEB_DIR
from freefood.pipeline import run_scan
from freefood.votes import VoteStore

STATE = {"scanning": False, "last_error": None, "last_scan": None}
VOTES = VoteStore()
LOCK = threading.Lock()


def scan_now():
    with LOCK:
        if STATE["scanning"]:
            return False
        STATE["scanning"] = True

    def work():
        print(f"[{datetime.now(TZ):%H:%M}] scanning sources…", flush=True)
        try:
            run_scan(log=lambda m: print(m, flush=True))
            STATE["last_error"] = None
        except Exception as ex:  # keep serving the previous data
            STATE["last_error"] = f"{type(ex).__name__}: {ex}"
            print("scan failed:", STATE["last_error"], flush=True)
        finally:
            STATE["last_scan"] = datetime.now(TZ).isoformat(timespec="seconds")
            STATE["scanning"] = False

    threading.Thread(target=work, daemon=True).start()
    return True


def data_is_stale(interval_h):
    if not EVENTS_FILE.exists():
        return True
    try:
        data = json.loads(EVENTS_FILE.read_text(encoding="utf-8"))
        generated = datetime.fromisoformat(data["generated_at"])
    except (ValueError, KeyError):
        return True
    today = datetime.now(TZ).date().isoformat()
    age_h = (datetime.now(TZ) - generated).total_seconds() / 3600
    return data["window"]["start"] != today or age_h >= interval_h


def scheduler(interval_h):
    while True:
        if data_is_stale(interval_h):
            scan_now()
        time.sleep(60)


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map,
                      ".webmanifest": "application/manifest+json", ".js": "text/javascript", ".svg": "image/svg+xml"}

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path == "/events.json":
            return self._file(EVENTS_FILE, "application/json")
        if url.path == "/api/status":
            return self._json(STATE)
        if url.path == "/api/votes":
            device = parse_qs(url.query).get("device", [""])[0]
            return self._json(VOTES.tally(device))
        return super().do_GET()

    def do_POST(self):
        path = urlsplit(self.path).path
        if path == "/api/scan":
            return self._json({"started": scan_now()})
        if path in ("/api/vote", "/api/name"):
            try:
                length = min(int(self.headers.get("Content-Length", 0)), 4096)
                body = json.loads(self.rfile.read(length) or b"{}")
                if path == "/api/vote":
                    return self._json(VOTES.vote(str(body.get("event_id", "")), str(body.get("device", "")),
                                                 body.get("vote"), body.get("name")))
                VOTES.set_name(str(body.get("device", "")), body.get("name", ""))
                return self._json({"ok": True})
            except KeyError as ex:
                return self.send_error(404, str(ex))
            except (ValueError, TypeError) as ex:
                return self.send_error(400, str(ex))
        self.send_error(404)

    def end_headers(self):
        # the service worker handles offline use; the network copy should always be revalidated
        if not any(h.lower().startswith(b"cache-control") for h in getattr(self, "_headers_buffer", [])):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def _file(self, path, ctype):
        if not path.exists():
            return self.send_error(404, "No data yet: the first scan is still running")
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):   # quiet: only log errors
        if args and str(args[1])[:1] in "45":
            super().log_message(fmt, *args)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8765)),
                    help="default 8765, or $PORT when a hosting service sets it")
    ap.add_argument("--interval", type=float, default=3, help="hours between automatic rescans (default 3)")
    ap.add_argument("--lan", action="store_true", help="listen on all interfaces, not just this computer")
    ap.add_argument("--no-scan", action="store_true", help="serve existing data without scanning")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    if not args.no_scan:
        threading.Thread(target=scheduler, args=(args.interval,), daemon=True).start()
    host = "0.0.0.0" if args.lan or "PORT" in os.environ else "127.0.0.1"   # hosted: listen publicly
    server = ThreadingHTTPServer((host, args.port), partial(Handler, directory=str(WEB_DIR)))
    url = f"http://localhost:{args.port}/"
    print(f"Free Food Map running at {url}  (Ctrl+C to stop)", flush=True)
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
