"""Events view: the short description and the listing rules.  Run: python tests/test_events_view.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from freefood.blurb import blurb  # noqa: E402
from freefood.pipeline import events_view_gaps  # noqa: E402
from freefood.sources.newsletters import _event_page_ok  # noqa: E402

# the layout of a real IOP event page: labels on their own lines, a calendar widget, raw HTML
IOP_PAGE = """Tuesday, October 13, 2026
Time:
5:00pm EST
Where:
L-280
Add to Calendar
2026-10-13 17:00:00
The Youth Vote and the Midterms
<p>Join the Institute of Politics for a candid conversation with <strong>Teddy Landis</strong> on the importance of the youth vote heading into the 2026 midterm elections.</p>
Register Here"""

# a real Carpenter Center program page: a date sentence, a schedule, boilerplate
CARPENTER_PAGE = """This program is happening on October 22, 2026 from 6:00pm-9:00pm.
Artist Talk and Opening Reception for Constitutive Outside
Join us for an artist conversation with two artists, moderated by the curator, followed by a reception on Level 1.
6:00-7:00 pm, Film Screening + Q & A, Theater, Lower Level
Free and open to the public.
Explore more of our rich history through our archive."""


def test_blurb():
    assert blurb("The Youth Vote and the Midterms", IOP_PAGE).startswith("Join the Institute of Politics for a candid")
    got = blurb("Artist Talk and Opening Reception for Constitutive Outside", CARPENTER_PAGE)
    assert got.startswith("Join us for an artist conversation") and "archive" not in got and "6:00" not in got, got
    # calendars run the heading into the first sentence; the heading is cut, real sentences are kept
    assert blurb("Study Group", "Study Group with Ambassador Chris Lu: When the Public Interest Is in Private Hands What "
                 "changes when public servants leave government service for the private sector?").startswith("What changes")
    assert blurb("Rudd", "Former Australian Prime Minister Kevin Rudd joins us for a timely discussion on the U.S. "
                 "and China.").startswith("Former Australian Prime Minister")
    # only a title and a date line: nothing to decide on
    assert blurb("Opening Reception", "Opening Reception\nOctober 28 | 12:00-1:00 pm") == ""


def test_event_page():
    assert _event_page_ok({"structured": True}, "https://example.harvard.edu/anything")
    assert _event_page_ok({"structured": False}, "https://iop.harvard.edu/events/youth-vote-and-midterms")
    assert _event_page_ok({"structured": False}, "https://carpenter.center/programs/artist-talk")
    assert not _event_page_ok({"structured": False}, "https://hutchinscenter.fas.harvard.edu/people/rita-freed")


def test_gaps():
    ok = {"all_day": False, "online": False, "lat": 42.37, "geo_method": "gazetteer", "location": "L-280",
          "event_page": True, "blurb": "A conversation about the youth vote and the midterm elections this fall."}
    assert events_view_gaps(ok) == []
    assert events_view_gaps({**ok, "all_day": True}) == ["time"]
    assert events_view_gaps({**ok, "lat": None}) == ["place"]
    assert events_view_gaps({**ok, "lat": None, "online": True}) == []            # clearly online: no map needed
    assert events_view_gaps({**ok, "geo_method": "host", "location": ""}) == ["place"]   # only the host's building
    assert events_view_gaps({**ok, "event_page": False, "blurb": ""}) == ["event page", "description"]


if __name__ == "__main__":
    test_blurb(); test_event_page(); test_gaps()
    print("events view checks passed")
