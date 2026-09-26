"""Reading suggested event pages, on made-up pages shaped like real ones.  Run: python tests/test_suggestions.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from freefood.config import TZ  # noqa: E402
from freefood.suggestions import accepted, events_from_page, norm_url  # noqa: E402

JSONLD_CDATA = """<html><head><script type="application/ld+json">/*<![CDATA[*/ {
  "@context": "http://schema.org/", "@type": "Event", "name": "Example Talk &amp; Reception",
  "startDate": "2026-09-29T21:30:00+00:00", "endDate": "2026-09-29T23:00:00+00:00",
  "location": {"@type": "Place", "name": "Barker Center", "address": {"streetAddress": "12 Quincy St"}},
  "description": "<p>Wine and cheese reception to follow.</p>", "url": "https://example.harvard.edu/e/1"
} /*]]>*/</script></head><body></body></html>"""

ICS_LINK = """<html><body><h1>Example Seminar</h1>
<a href="data:text/calendar;charset=utf8,BEGIN:VCALENDAR%0ABEGIN:VEVENT%0ADTSTART:20260928T120000%0ADTEND:20260928T130000%0ASUMMARY:Example Seminar%0ALOCATION:L-166%0AEND:VEVENT%0AEND:VCALENDAR">iCalendar</a>
</body></html>"""

PLAIN = """<html><head><meta property="og:title" content="Example Book Talk | Example Center"></head><body>
<nav>Home Events About</nav><main><h1>Example Book Talk</h1>
<p><span>Tuesday, September 29, 2026, 5</span></p><p><span>&ndash;7pm EDT</span></p>
<p>Location: CGIS South, S354</p><p>A small reception will follow.</p></main></body></html>"""

NO_DATE = "<html><body><main><h1>Example Program</h1><p>Lunch is always provided.</p></main></body></html>"


class NoHttp:
    def get_text(self, *a, **k):
        raise AssertionError("no network in tests")


def test_jsonld_in_cdata():
    ev = events_from_page("https://example.harvard.edu/e/1", JSONLD_CDATA, NoHttp())[0]
    assert ev["title"] == "Example Talk & Reception", ev["title"]
    assert ev["start"].astimezone(TZ).hour == 17                         # 21:30 UTC = 5:30 PM Boston
    assert ev["location"] == "Barker Center, 12 Quincy St", ev["location"]
    assert "reception to follow" in ev["description"]


def test_inline_ics():
    ev = events_from_page("https://example.harvard.edu/e/2", ICS_LINK, NoHttp())[0]
    assert (ev["title"], ev["location"], ev["start"].hour) == ("Example Seminar", "L-166", 12), ev


def test_plain_page_split_time():
    ev = events_from_page("https://example.harvard.edu/e/3", PLAIN, NoHttp())[0]
    assert ev["title"] == "Example Book Talk", ev["title"]               # " | Example Center" removed
    assert (ev["start"].month, ev["start"].day, ev["start"].hour) == (9, 29, 17), ev["start"]
    assert ev["location"] == "CGIS South, S354", ev["location"]


def test_no_date():
    assert events_from_page("https://example.harvard.edu/e/4", NO_DATE, NoHttp()) == []


def test_review_rules():
    assert accepted({"url": "https://hls.harvard.edu/events/x/"})
    assert accepted({"url": "https://www.eventbrite.com/e/123"})
    assert not accepted({"url": "https://example.com/party"})
    assert accepted({"url": "https://example.com/party", "approved": True})
    assert norm_url("https://www.HKS.harvard.edu/events/a/?utm=1#x") == "hks.harvard.edu/events/a"


if __name__ == "__main__":
    test_jsonld_in_cdata(); test_inline_ics(); test_plain_page_split_time(); test_no_date(); test_review_rules()
    print("suggestion reader checks passed")
