"""Harvard Kennedy School events (www.hks.harvard.edu/more/events).

Covers HKS centers too: IOP, Belfer, Ash, Shorenstein, CPL, Carr-Ryan, M-RCBG...
The listing gives title/date/time; location and description need the detail page.
"""
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import lxml.html
from dateutil import parser as dparser

from ..config import TZ
from ..models import Event
from ..text import html_to_text, one_line

BASE = "https://www.hks.harvard.edu"


def parse_times(day, time_text):
    """'12:00 PM - 1:00 PM ET' on a date -> (start, end) aware datetimes."""
    parts = re.findall(r"\d{1,2}(?::\d{2})?\s*[ap]\.?m\.?", time_text or "", re.I)
    if not parts:
        return datetime(day.year, day.month, day.day, tzinfo=TZ), None, True
    ts = [dparser.parse(p.replace(".", "")).time() for p in parts[:2]]
    start = datetime.combine(day, ts[0], tzinfo=TZ)
    end = datetime.combine(day, ts[1], tzinfo=TZ) if len(ts) > 1 else None
    return start, end, False


class HksSource:
    id, name, homepage = "hks", "Harvard Kennedy School", BASE + "/more/events"

    def fetch(self, start, end, http):
        listing = []
        for page in range(20):
            doc = lxml.html.fromstring(http.get_text(f"{BASE}/more/events?page={page}"))
            rows = doc.xpath('//article[contains(@class,"content-type--event")]')
            if not rows:
                break
            past_end = True
            for art in rows:
                a = art.xpath('.//h2[contains(@class,"node-title")]//a')
                date_el = art.xpath('.//div[contains(@class,"field--name-field-event-date")]')
                if not a or not date_el:
                    continue
                date_txt = re.sub(r"(\d)(st|nd|rd|th)", r"\1", one_line(date_el[0].text_content()))
                try:
                    day = dparser.parse(date_txt).date()
                except (ValueError, OverflowError):
                    continue
                if day <= end:
                    past_end = False
                if start <= day <= end:
                    time_el = art.xpath('.//div[contains(@class,"field--name-field-event-end-date")]')
                    listing.append({"url": BASE + a[0].get("href"), "title": one_line(a[0].text_content()),
                                    "day": day, "time": one_line(time_el[0].text_content()) if time_el else ""})
            if past_end:
                break
        with ThreadPoolExecutor(max_workers=4) as pool:
            return [ev for ev in pool.map(lambda it: self._detail(it, http), listing) if ev]

    def _detail(self, item, http):
        s, e, all_day = parse_times(item["day"], item["time"])
        location = desc_html = host = rsvp = ""
        try:
            doc = lxml.html.fromstring(http.get_text(item["url"], cache=True))
            loc = doc.xpath('//div[contains(@class,"event-location")]')
            location = one_line(loc[0].text_content()) if loc else ""
            body = doc.xpath('//div[contains(@class,"field--name-body")]')
            desc_html = lxml.html.tostring(body[0], encoding="unicode") if body else ""
            org = doc.xpath('//div[contains(@class,"event-organizer__item")]')
            host = "; ".join(one_line(o.text_content()) for o in org)
            btn = doc.xpath('//div[contains(@class,"event-rsvp-button")]//a/@href')
            rsvp = btn[0] if btn else ""
        except Exception:  # keep the listing entry even if the detail page fails
            pass
        return Event(
            source_id=self.id, source_name=self.name, title=item["title"], url=item["url"],
            start=s, end=e, all_day=all_day, location=location,
            description=html_to_text(desc_html), host=host,
            online=bool(re.search(r"^(online|virtual|zoom|webinar)", location, re.I)),
            registration_link=rsvp, registration_hint="rsvp" if rsvp else "",
            extra={"html": desc_html},
        )
