"""WordPress-based center sites.

- WpAcfSource: sites with an `event` post type whose details live in ACF
  fields (Ash Center, Shorenstein Center). The REST API lists events by
  publish date, so we page through recent posts and keep those in range.
- TribeSource: sites running The Events Calendar plugin (Fairbank Center
  and many other FAS centers) -- /wp-json/tribe/events/v1/events.
"""
import re
from datetime import datetime, timedelta

from ..config import TZ
from ..models import Event
from ..text import html_to_text, one_line

ONLINE = re.compile(r"^\s*(zoom|online|virtual|webinar)", re.I)


def _local(value):
    """'2026-10-09 12:00:00' (site-local, Eastern) -> aware datetime."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.strip()).replace(tzinfo=TZ)
    except ValueError:
        return None


class WpAcfSource:
    def __init__(self, id, name, base, host):
        self.id, self.name, self.base, self.host = id, name, base.rstrip("/"), host
        self.homepage = self.base + "/events/"

    def fetch(self, start, end, http):
        out = []
        for page in range(1, 5):
            try:
                posts = http.get_json(f"{self.base}/wp-json/wp/v2/event",
                                      params={"per_page": 50, "page": page, "_fields": "link,title,acf"})
            except Exception:
                break
            if not posts:
                break
            for p in posts:
                ev = self._event(p)
                if ev and start <= ev.start.date() <= end:
                    out.append(ev)
        return out

    def _event(self, p):
        acf = p.get("acf") or {}
        d = acf.get("details") or {}
        s = e = None
        if d.get("start_date_time"):                       # Ash Center layout
            s, e = _local(d.get("start_date_time")), _local(d.get("end_date_time"))
        elif d.get("dates"):                                # Shorenstein layout
            first = d["dates"][0]
            s = _local(first.get("start_date_and_time"))
            if s and first.get("end_time"):
                e = _local(f"{s.date().isoformat()} {first['end_time']}")
        if not s:
            return None
        html = (d.get("description") or "") + "\n"
        for block in acf.get("page_layout") or []:
            w = block.get("component_wysiwyg") if isinstance(block, dict) else None
            if isinstance(w, dict) and w.get("content"):
                html += w["content"].replace("\r\n", "\n").replace("\n\n", "<br><br>") + "\n"
        cta = d.get("registration_cta") or {}
        location = one_line(d.get("location") or "")
        title = (p.get("title") or {}).get("rendered", "")
        return Event(
            source_id=self.id, source_name=self.name, title=one_line(title), url=p.get("link", ""),
            start=s, end=e, location=location, description=html_to_text(html), host=self.host,
            online=bool(ONLINE.search(location)),
            registration_link=(cta.get("url") or "") if isinstance(cta, dict) else "",
            extra={"html": html},
        )


class TribeSource:
    def __init__(self, id, name, base, host):
        self.id, self.name, self.base, self.host = id, name, base.rstrip("/"), host
        self.homepage = self.base + "/events/"

    def fetch(self, start, end, http):
        url = f"{self.base}/wp-json/tribe/events/v1/events"
        params = {"start_date": start.isoformat(), "end_date": (end + timedelta(days=1)).isoformat(), "per_page": 50}
        out = []
        for _page in range(5):
            data = http.get_json(url, params=params)
            out += [self._event(e) for e in data.get("events", [])]
            url, params = data.get("next_rest_url"), None
            if not url:
                break
        return [e for e in out if e and start <= e.start.date() <= end]

    def _event(self, e):
        s, en = _local(e.get("start_date")), _local(e.get("end_date"))
        if not s:
            return None
        venue = e.get("venue") or {}
        if isinstance(venue, list):
            venue = venue[0] if venue else {}
        loc = ", ".join(x for x in (venue.get("venue"), venue.get("address"), venue.get("city")) if x)
        orgs = e.get("organizer") or []
        host = "; ".join(one_line(o.get("organizer", "")) for o in orgs if isinstance(o, dict)) or self.host
        html = e.get("description") or ""
        return Event(
            source_id=self.id, source_name=self.name, title=one_line(e.get("title", "")), url=e.get("url", ""),
            start=s, end=en, all_day=bool(e.get("all_day")), location=one_line(loc),
            description=html_to_text(html), host=host,
            online=bool(ONLINE.search(loc)),
            lat=float(venue["geo_lat"]) if venue.get("geo_lat") else None,
            lon=float(venue["geo_lng"]) if venue.get("geo_lng") else None,
            extra={"html": html},
        )
