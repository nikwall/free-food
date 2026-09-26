"""Classifier checks on phrasings seen in real Harvard listings.  Run: python -m pytest tests  (or python tests/test_classify.py)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from freefood.classify import detect_food, detect_registration  # noqa: E402

FOOD_CASES = [
    # (title, text, expected status, expected first type or None)
    ("AIIB at 10", "The talk is based on her new book. A light lunch will be provided. Please register here.", "confirmed", "Lunch"),
    ("Power, Principles, and American Foreign Policy", "Join the IOP for our Food for Thought Lunch series. Lunch will be served.", "confirmed", "Lunch"),
    ("Book talk", "The conversation will be followed by a reception.", "confirmed", "Reception"),
    ("Welcome Party", "Join us for food, drinks, and music!", "confirmed", "Food"),
    ("Policy Analysis at Scale", "Refreshments will be served.", "confirmed", "Snacks"),
    ("Seminar", "Pizza provided!", "confirmed", "Pizza"),
    ("Alain Locke Gallery Opening Reception", "Celebrate the new gallery.", "likely", "Reception"),
    ("Coffee Chat with Caroline", "Meet the editor.", "likely", "Coffee"),
    ("Healthier Food for All: Closing the Affordability Gap", "A panel on food policy and food insecurity in America.", "none", None),
    ("Cooking Up Change", "An exhibition on women's agency and food history.", "none", None),
    ("Brown Bag Seminar", "Bring your own lunch; coffee is not provided.", "byo", None),
    ("Workshop", "Food will be available for purchase.", "byo", None),
    ("The Reception of Kant", "On the critical reception of Kant in the 19th century.", "none", None),
    ("Webinar", "Lunch will be served.", "none", None),  # online -> never food (checked below)
]


def test_food():
    for title, text, status, first in FOOD_CASES:
        online = title == "Webinar"
        got = detect_food(title, text, online=online)
        assert got["status"] == status, (title, got)
        if first:
            assert got["types"][0] == first, (title, got)


def test_registration():
    assert detect_registration("Registration is encouraged but not required.")["status"] == "recommended"
    assert detect_registration("No registration required. All are welcome.")["status"] == "none"
    assert detect_registration("A light lunch will be provided. Please register here.")["status"] == "required"
    assert detect_registration("RSVP required by Sept 28.")["status"] == "required"
    assert detect_registration("Talk.", hint="rsvp", link="https://x")["status"] == "required"
    assert detect_registration("A talk about things.")["status"] == "unknown"
    got = detect_registration("Details.", html='<a href="https://forms.gle/abc">Sign up</a>')
    assert got["link"] == "https://forms.gle/abc"


if __name__ == "__main__":
    test_food(); test_registration()
    print("all classifier checks passed")
