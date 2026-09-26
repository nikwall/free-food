"""Newsletter extraction on a synthetic digest (made-up items, typical layout).  Run: python tests/test_newsletter.py"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from freefood.sources.newsletters import extract_items  # noqa: E402

SAMPLE = """Weekly Digest

Example Lecture on Local Journalism
Tuesday, Sept. 29, 12:15-1:30 p.m. | Littauer 166
A conversation about newsroom economics. Lunch will be served. RSVP here <https://example.org/rsvp>

Example Reading Group
Wednesday, Sept. 30, 4 p.m.
Location: Barker Center, Thompson Room
We will discuss chapter 3. No food this week.

Example Book Launch
Thursday, Oct. 1, 6 pm
Location: Harvard Book Store
Reading and signing, followed by a wine reception.

Example Talk Next Month
Monday, Oct. 26, noon
Pizza provided.
"""


def test_extract():
    evs = extract_items(SAMPLE, "Weekly Digest", date(2026, 9, 25), date(2026, 10, 2), today=date(2026, 9, 25))
    titles = [e.title for e in evs]
    assert titles == ["Example Lecture on Local Journalism", "Example Book Launch"], titles
    lecture, launch = evs
    assert lecture.start.hour == 12 and lecture.start.minute == 15, lecture.start
    assert lecture.location == "Littauer 166", lecture.location
    assert lecture.url == "https://example.org/rsvp", lecture.url
    assert launch.start.hour == 18 and launch.location == "Harvard Book Store"


if __name__ == "__main__":
    test_extract()
    print("newsletter extraction checks passed")
