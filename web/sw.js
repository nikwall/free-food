/* Service worker: makes the site installable and usable offline.
   - app shell (page, script, styles, icons, Leaflet, fonts): cache first, refreshed in the background
   - events.json: network first, falls back to the last copy when offline
   - the basemap is drawn from basemap.json (part of the shell), so no map tiles are fetched
   - /api/* (votes, scans): always network, never cached */
const VERSION = "ffm-v11";
const SHELL = ["./", "index.html", "app.js?v=11", "style.css?v=11", "config.js?v=11", "manifest.webmanifest", "basemap.json", "vendor/leaflet.css",
  "icons/icon-192.png", "icons/icon-512.png", "icons/apple-touch-icon.png", "icons/favicon-64.png"];
const MAX_TILES = 400;

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => !k.startsWith(VERSION)).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

async function networkFirst(req) {
  const cache = await caches.open(VERSION);
  try {
    const res = await fetch(req);
    if (res.ok) cache.put(req, res.clone());
    return res;
  } catch (err) {
    const hit = await cache.match(req, { ignoreSearch: true });
    if (hit) return hit;
    throw err;
  }
}

async function staleWhileRevalidate(req, cacheName = VERSION) {
  const cache = await caches.open(cacheName);
  const hit = await cache.match(req);
  const fresh = fetch(req).then((res) => {
    if (res.ok || res.type === "opaque") cache.put(req, res.clone());
    return res;
  }).catch(() => hit);
  return hit || fresh;
}

async function tile(req) {
  const cache = await caches.open(VERSION + "-tiles");
  const hit = await cache.match(req);
  if (hit) return hit;
  const res = await fetch(req);
  if (res.ok || res.type === "opaque") {
    await cache.put(req, res.clone());
    const keys = await cache.keys();
    for (const k of keys.slice(0, Math.max(0, keys.length - MAX_TILES))) await cache.delete(k);
  }
  return res;
}

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin === location.origin) {
    if (url.pathname.includes("/api/")) return;                    // live data only
    if (url.pathname.endsWith("events.json")) return e.respondWith(networkFirst(req));
    if (req.mode === "navigate") return e.respondWith(networkFirst(req));
    return e.respondWith(staleWhileRevalidate(req));
  }
  if (url.hostname.endsWith("tile.openstreetmap.org")) return e.respondWith(tile(req));
  if (/cdnjs\.cloudflare\.com|fonts\.(googleapis|gstatic)\.com/.test(url.hostname)) {
    return e.respondWith(staleWhileRevalidate(req, VERSION + "-libs"));
  }
});
