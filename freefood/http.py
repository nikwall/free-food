"""Polite HTTP client: browser UA, retries, and an on-disk page cache."""
import hashlib
import json
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import BROWSER_UA, CACHE_DIR, PAGE_CACHE_HOURS


class Http:
    def __init__(self, cache_hours=PAGE_CACHE_HOURS):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": BROWSER_UA, "Accept-Language": "en-US,en;q=0.9"})
        retry = Retry(total=2, backoff_factor=1.0, status_forcelist=(429, 500, 502, 503, 504))
        self.s.mount("https://", HTTPAdapter(max_retries=retry, pool_maxsize=8))
        self.s.mount("http://", HTTPAdapter(max_retries=retry, pool_maxsize=8))
        self.cache_hours = cache_hours
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, url):
        return CACHE_DIR / (hashlib.sha1(url.encode()).hexdigest() + ".txt")

    def get_text(self, url, cache=False, timeout=30):
        """GET a URL as text. With cache=True, reuse a copy younger than cache_hours."""
        path = self._cache_path(url)
        if cache and path.exists() and (time.time() - path.stat().st_mtime) < self.cache_hours * 3600:
            return path.read_text(encoding="utf-8")
        r = self.s.get(url, timeout=timeout)
        r.raise_for_status()
        r.encoding = r.encoding or "utf-8"
        text = r.text
        if cache:
            path.write_text(text, encoding="utf-8")
        return text

    def get_json(self, url, params=None, timeout=45):
        r = self.s.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        return json.loads(r.content.decode("utf-8-sig"))
