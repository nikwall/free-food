"""LiveWhale calendars (Harvard College events: events.college.harvard.edu)."""
from datetime import datetime

from ..models import Event
from ..text import html_to_text, one_line


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


FIELDS = ("location,description,summary,registration,group_title,tags,event_types,event_types_audience,"
          "custom_sponsor,status")


class LiveWhaleSource:
    def __init__(self, id="college", name="Harvard College events", base="https://events.college.harvard.edu"):
        self.id, self.name, self.base, self.homepage = id, name, base, base + "/"

    def fetch(self, start, end, http):
        url = (f"{self.base}/live/json/events/start_date/{start.isoformat()}/end_date/{end.isoformat()}"
               f"/response_fields/{FIELDS}/")
        out = []
        for _page in range(10):
            data = http.get_json(url)
            out += [ev for ev in (self._event(e) for e in data.get("data", [])) if ev]
            url = (data.get("links") or {}).get("next")
            if not url:
                break
        return out

    def _event(self, e):
        if not e.get("date_iso"):
            return None
        start = datetime.fromisoformat(e["date_iso"])
        end = datetime.fromisoformat(e["date2_iso"]) if e.get("date2_iso") else None
        desc_html = (e.get("description") or "") + "\n" + (e.get("summary") or "")
        location = html_to_text(e.get("location") or "")
        if "log in to view" in location.lower():   # HarvardKey-restricted listing
            location = ""
        location = one_line(location)
        lat, lon = _num(e.get("location_latitude")), _num(e.get("location_longitude"))
        return Event(
            source_id=self.id, source_name=self.name,
            title=one_line(e.get("title", "")), url=e.get("url", ""),
            start=start, end=end, all_day=bool(e.get("is_all_day")),
            location=location, description=html_to_text(desc_html),
            host=one_line(e.get("custom_sponsor") or e.get("group_title") or ""),
            online=bool(e.get("is_online")) and not location,
            canceled=bool(e.get("is_canceled")),
            registration_hint="required" if e.get("has_registration") else "",
            registration_link=e.get("url", "") if e.get("has_registration") else "",
            lat=lat, lon=lon,
            extra={"html": desc_html,
                   "class_years": [one_line(x) for x in e.get("event_types_audience") or []],   # Sophomore, Junior...
                   "event_types": [one_line(x) for x in e.get("event_types") or []],
                   "group": one_line(e.get("group_title") or "")},
        )
