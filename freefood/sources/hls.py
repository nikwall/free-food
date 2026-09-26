"""Harvard Law School calendar (hls.harvard.edu/calendar/?start=YYYY-MM-DD, one page per day).

HLS talks very often say "Lunch will be provided", so this source is high-yield.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import lxml.html

from ..models import Event
from ..text import html_to_text, one_line
from .hks import parse_times

BASE = "https://hls.harvard.edu"


class HlsSource:
    id, name, homepage = "hls", "Harvard Law School", BASE + "/calendar/"

    def fetch(self, start, end, http):
        listing, seen = [], set()
        day = start
        while day <= end:
            doc = lxml.html.fromstring(http.get_text(f"{BASE}/calendar/?start={day.isoformat()}"))
            for group in doc.xpath('//div[contains(@class,"events-feed__group")]'):
                for li in group.xpath('.//li[contains(@class,"events-feed__item")]'):
                    a = li.xpath('.//a[contains(@class,"events-feed__item-title-link")]')
                    if not a:
                        continue
                    url = a[0].get("href")
                    if url in seen:
                        continue
                    seen.add(url)
                    t = li.xpath('.//p[contains(@class,"events-feed__item-time")]')
                    listing.append({"url": url, "title": one_line(a[0].text_content()), "day": day,
                                    "time": one_line(t[0].text_content()) if t else ""})
            day += timedelta(days=1)
        with ThreadPoolExecutor(max_workers=4) as pool:
            return [ev for ev in pool.map(lambda it: self._detail(it, http), listing) if ev]

    def _detail(self, item, http):
        location = desc_html = host = website = ""
        audiences, student_org, research_program, hls_office = [], False, False, ""
        day, time_text = item["day"], item["time"]
        try:
            doc = lxml.html.fromstring(http.get_text(item["url"], cache=True))
            venue = doc.xpath('//p[contains(@class,"event-page__venue-name")]')
            location = one_line(venue[0].text_content()).replace("; ", ", ") if venue else ""
            t = doc.xpath('//p[contains(@class,"event-page__time")]')
            time_text = one_line(t[0].text_content()) if t else time_text
            body = doc.xpath('//div[contains(@class,"data-page__detail-main")]')
            desc_html = lxml.html.tostring(body[0], encoding="unicode") if body else ""
            hosts = []
            for dt in doc.xpath('//aside[contains(@class,"data-page__detail-aside")]//dt'):
                label = one_line(dt.text_content())
                dd = dt.getnext()
                if dd is None:
                    continue
                if label == "Website":
                    href = dd.xpath(".//a/@href")
                    website = href[0] if href else ""
                elif label == "Audiences":
                    audiences = [one_line(x.text_content()) for x in dd.xpath(".//li")] or [one_line(dd.text_content())]
                elif label in ("Student Organizations", "Clinics / SPOs", "Research Programs", "Offices", "Departments"):
                    names = [one_line(x.text_content()) for x in dd.xpath(".//li")
                             if "not applicable" not in x.text_content().lower()]
                    hosts += names
                    student_org = student_org or (label == "Student Organizations" and bool(names))
                    research_program = research_program or (label == "Research Programs" and bool(names))
                    if label in ("Departments", "Offices") and names and not hls_office:
                        hls_office = ", ".join(names)
            host = "; ".join(hosts)
        except Exception:
            pass
        s, e, all_day = parse_times(day, time_text)
        return Event(
            source_id=self.id, source_name=self.name, title=item["title"], url=item["url"],
            start=s, end=e, all_day=all_day, location=location + (", Harvard Law School" if location else ""),
            description=html_to_text(desc_html), host=host or "Harvard Law School",
            extra={"html": desc_html, "website": website, "hls_audiences": audiences, "student_org": student_org,
                   "research_program": research_program, "hls_office": hls_office},
        )
