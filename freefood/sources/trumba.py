"""Harvard Gazette events calendar (Trumba). University-wide: every school can post here."""
import re
from datetime import datetime, timedelta, timezone

from ..models import Event
from ..text import html_to_text, links, one_line


class TrumbaSource:
    def __init__(self, id="gazette", name="Harvard Gazette calendar", web_name="gazette",
                 homepage="https://news.harvard.edu/gazette/harvard-events/events-calendar/"):
        self.id, self.name, self.web_name, self.homepage = id, name, web_name, homepage

    def fetch(self, start, end, http):
        days = (end - start).days + 1
        url = f"https://www.trumba.com/calendars/{self.web_name}.json"
        data = http.get_json(url, params={"startdate": start.strftime("%Y%m%d"), "days": days})
        out = []
        for e in data:
            ev = self._event(e)
            if ev:
                out.append(ev)
        return out

    def _event(self, e):
        def dt(value, offset):
            if not value:
                return None
            sign = -1 if offset.startswith("-") else 1
            tz = timezone(sign * timedelta(hours=int(offset[1:3]), minutes=int(offset[3:5])))
            return datetime.fromisoformat(value).replace(tzinfo=tz)

        start = dt(e.get("startDateTime"), e.get("startTimeZoneOffset") or "-0400")
        end = dt(e.get("endDateTime"), e.get("endTimeZoneOffset") or "-0400")
        custom = {c.get("label"): c.get("value", "") for c in e.get("customFields", [])}
        web = links(e.get("webLink", ""))
        url = web[0][1] if web else e.get("permaLinkUrl", "")
        ticket = links(custom.get("Ticket Web Link", ""))
        location = html_to_text(e.get("location", "")).replace("\n", ", ")
        loc_type = (e.get("locationType") or "").lower()
        desc_html = e.get("description", "")
        extra_bits = [f"Cost: {one_line(custom['Cost'])}" if custom.get("Cost") else "",
                      f"Harvard Key required: {custom['Harvard Key Required']}" if custom.get("Harvard Key Required") else ""]
        return Event(
            source_id=self.id, source_name=self.name,
            title=one_line(e.get("title", "")), url=url or e.get("permaLinkUrl", ""),
            start=start, end=end, all_day=bool(e.get("allDay")),
            location=location,
            description=html_to_text(desc_html),
            host=one_line(re.sub(r"<[^>]+>", " ", custom.get("Organization/Sponsor", "") or custom.get("Sponsor", ""))),
            online=(loc_type == "online") or (not location and bool(custom.get("Online Location"))),
            canceled=bool(e.get("canceled")),
            registration_link=ticket[0][1] if ticket else "",
            registration_hint="required" if e.get("openSignUp") else "",
            extra={"html": desc_html, "notes": " | ".join(b for b in extra_bits if b),
                   "calendar_link": e.get("permaLinkUrl", ""),
                   "harvard_key": one_line(custom.get("Harvard Key Required", ""))},
        )
