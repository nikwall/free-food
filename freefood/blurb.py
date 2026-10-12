"""A short description for an event card: what the event is about, in two or three sentences.

Event pages and emails mix the description with labels ("Time:", "Where:"), dates, schedules,
registration boilerplate and headings. blurb() keeps only full sentences about the event itself
and returns "" when nothing like that is left, so the Events view can leave such an event out.
"""
import re

from .sources.newsletters import DATE_RE, TIME_RE
from .text import html_to_text, one_line

LABEL = re.compile(r"^(?:time|date|dates|when|where|location|venue|room|meeting method|format|cost|price|admission|"
                   r"registration|rsvp|host|hosted by|sponsors?|co-?sponsors?|contact|speakers?|moderator|audience|"
                   r"open to|tags?|categor(?:y|ies)|share|livestream)\b\s*:", re.I)
BOILER = re.compile(
    r"add to (?:google |outlook |apple |i)?calendar|must rsvp|\brsvp\b|register (?:here|now|today|at|by|for)|"
    r"registration (?:is )?(?:required|open|closes)|harvard id|livestream|live stream|in-person seat|"
    r"free and open to|open to the public|click here|learn more|read more|more info|view (?:in|on|related)|"
    r"watch (?:live|on|the)|is happening on|takes place on|will take place|doors open|seating is|space is limited|"
    r"accessib|accommodation|unsubscribe|this email|newsletter|follow us|copyright|all rights reserved|"
    r"explore more|our archive|sign up for|subscribe to|support (?:us|our)|donate",
    re.I)
WEEKDAY = re.compile(r"\b(?:mon|tues|wednes|thurs|fri|satur|sun)day\b|\b(?:today|tonight|tomorrow)\b", re.I)
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[\"“‘(A-Z0-9])")


def _is_schedule(sentence):
    """True for lines that are mostly a date or time ("6:00–7:00 pm, Film Screening + Q & A, Theater")."""
    if re.match(r"^\s*\d{1,2}(?::\d{2})?\s*(?:[ap]\.?m\.?)?\s*[-–—]", sentence, re.I):
        return True
    rest = WEEKDAY.sub(" ", DATE_RE.sub(" ", TIME_RE.sub(" ", sentence)))
    return len(re.findall(r"[^\W\d_]{3,}", rest)) < 4


def blurb(title, text, limit=260):
    """Two or three sentences describing the event, at most `limit` characters; "" if there are none."""
    if not text:
        return ""
    if "<" in text:
        text = html_to_text(text)
    title_key = re.sub(r"\W+", " ", (title or "").lower()).strip()
    out, size = [], 0
    for line in text.split("\n"):
        line = one_line(line)
        if not line or LABEL.match(line):
            continue
        if re.sub(r"\W+", " ", line.lower()).strip() == title_key:
            continue
        # headings and list items: no sentence punctuation and short
        if not re.search(r"[.!?…]$", line) and len(line.split()) <= 12:
            continue
        for sentence in SENTENCE_SPLIT.split(line):
            sentence = sentence.strip()
            if len(sentence.split()) < 6 or BOILER.search(sentence) or _is_schedule(sentence):
                continue
            out.append(sentence)
            size += len(sentence) + 1
            if size >= limit:
                break
        if size >= limit:
            break
    s = " ".join(out)
    if len(s) > limit:
        s = s[:limit].rsplit(" ", 1)[0].rstrip(",;:–—-") + "…"
    return s if len(s) >= 60 and len(s.split()) >= 10 else ""
