"""Newsletter extraction on a synthetic digest (made-up items, typical layout).  Run: python tests/test_newsletter.py"""
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from freefood.config import TZ  # noqa: E402
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




FORWARDED = """Hi all, this one looks good.

---------- Forwarded message ---------
From: Example Center <events@example.harvard.edu>
Date: Mon, Sep 28, 2026 at 9:00 AM
Subject: Example Center Weekly
To: Someone <someone@example.com>

This week at the Example Center

Example Panel on Local News
Thursday at 12:15 pm | CGIS South S020
Lunch will be served.

Example Film Night
Tomorrow, 7 pm
Location: Barker Center
Popcorn and drinks provided.
"""


def test_forwarded_and_relative_dates():
    from freefood.sources.newsletters import unwrap_forward
    text, subject, sent = unwrap_forward(FORWARDED, "Fwd: Example Center Weekly", date(2026, 9, 29))
    assert subject == "Example Center Weekly" and sent == date(2026, 9, 28), (subject, sent)
    evs = extract_items(text, subject, date(2026, 9, 28), date(2026, 10, 5), today=sent)
    got = [(e.title, e.start.day, e.start.hour, e.location) for e in evs]
    # "Thursday" after Mon Sep 28 is Oct 1; "Tomorrow" is Sep 29
    assert got == [("Example Panel on Local News", 1, 12, "CGIS South S020"),
                   ("Example Film Night", 29, 19, "Barker Center")], got




def test_confirmation_mail():
    from email.message import EmailMessage
    from freefood.sources.newsletters import confirm_subscription

    class Page:
        ok, text = True, "<h1>Subscription confirmed</h1><p>Thank you!</p>"

    class FakeHttp:
        class s:
            calls = []
            @staticmethod
            def get(url, timeout=20):
                FakeHttp.s.calls.append(url)
                return Page()

    html = '<p>Please confirm.</p><a href="https://example.us1.list-manage.com/subscribe/confirm?u=1">Yes, subscribe me to this list.</a>'
    today = datetime.now(TZ).date()
    msg = EmailMessage()
    msg["From"] = "Example Center <events@example.harvard.edu>"
    assert confirm_subscription(msg, html, "", "Example Center: Please Confirm Subscription", today, FakeHttp) == "confirmed"
    assert FakeHttp.s.calls == ["https://example.us1.list-manage.com/subscribe/confirm?u=1"]
    other = EmailMessage()
    other["From"] = "Random List <news@example.com>"            # not Harvard: a person confirms in Gmail
    assert confirm_subscription(other, html, "", "Please confirm your subscription", today, FakeHttp) == "needs_click"
    assert len(FakeHttp.s.calls) == 1
    assert confirm_subscription(msg, html, "", "This week at the Example Center", today, FakeHttp) is None


if __name__ == "__main__":
    test_extract()
    test_forwarded_and_relative_dates()
    test_confirmation_mail()
    print("newsletter extraction checks passed")
