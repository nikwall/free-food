"""Email newsletters (school digests, center mailing lists, Nieman announcements).

Two ways in:
  1. Drop files into inbox/  (.eml saved from your mail client, or .txt/.html)
  2. Set FFM_IMAP_HOST / FFM_IMAP_USER / FFM_IMAP_PASSWORD (an app password for a
     mailbox that receives the newsletters). Optional: FFM_IMAP_FOLDER (INBOX),
     FFM_IMAP_SINCE_DAYS (14), FFM_IMAP_FROM (comma-separated sender filters).
     Messages are read with BODY.PEEK, so nothing is marked read, moved or deleted.

Newsletters have no fixed structure, so extraction is heuristic: the text is cut
into items at lines that contain a date ("Monday, Sept. 28", "9/28"); an item is
kept only if it falls in the scan window and the food rules fire on it. Items
are labeled "Newsletter" in the UI so readers know to double-check them.
"""
import email
import imaplib
import os
import re
from datetime import date, datetime, timedelta
from email import policy

from dateutil import parser as dparser

from ..config import INBOX_DIR, TZ
from ..models import Event
from ..text import html_to_text, one_line

MONTHS = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
DATE_RE = re.compile(
    rf"\b(?:(?:mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)[a-z]*\.?,?\s+)?{MONTHS}\s+\d{{1,2}}(?:st|nd|rd|th)?\b"
    r"|\b(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?,?\s+\d{1,2}/\d{1,2}\b|\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b",
    re.I)
TIME_RE = re.compile(r"\b(\d{1,2}(?::\d{2})?)\s*(?:[-–—]\s*\d{1,2}(?::\d{2})?\s*)?([ap])\.?\s*m\b\.?|\bnoon\b", re.I)
URL_RE = re.compile(r"https?://[^\s<>\")\]]+")
LOC_RE = re.compile(r"(?:location|where|venue|place)\s*[:\-]\s*(.+)", re.I)


def _message_text(msg):
    """Plain text of an email with each link kept inline as 'text <url>'."""
    html = plain = ""
    for part in msg.walk():
        ctype = part.get_content_type()
        if part.get_content_maintype() == "multipart" or part.get_filename():
            continue
        try:
            payload = part.get_content()
        except (LookupError, KeyError):
            continue
        if ctype == "text/html" and not html:
            html = payload
        elif ctype == "text/plain" and not plain:
            plain = payload
    if html:
        return _html_with_links(html)
    return plain


def _html_with_links(html):
    html = re.sub(r"<a\b[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>", r"\2 <\1>", html, flags=re.S | re.I)
    return html_to_text(html)


def _year_for(month, day, today):
    """Pick the year that puts month/day closest to today (newsletters omit years)."""
    best = None
    for y in (today.year - 1, today.year, today.year + 1):
        try:
            d = date(y, month, day)
        except ValueError:
            continue
        if best is None or abs((d - today).days) < abs((best - today).days):
            best = d
    return best


def _parse_day(text, today):
    try:
        d = dparser.parse(text, default=datetime(today.year, 1, 1), fuzzy=True)
    except (ValueError, OverflowError):
        return None
    return _year_for(d.month, d.day, today)


def _parse_time(line):
    m = TIME_RE.search(line)
    if not m:
        return None
    if m.group(0).lower() == "noon":
        return 12, 0
    hm = m.group(1).split(":")
    h, mi = int(hm[0]), int(hm[1]) if len(hm) > 1 else 0
    if m.group(2).lower() == "p" and h < 12:
        h += 12
    return (h, mi) if h < 24 and mi < 60 else None


def extract_items(text, subject, start, end, today=None, origin=""):
    """Cut newsletter text into dated items; return Events for items within [start, end]."""
    from ..classify import detect_food  # local import: classify is independent of sources

    today = today or datetime.now(TZ).date()
    lines = [ln.strip() for ln in text.split("\n")]
    anchors = [i for i, ln in enumerate(lines) if DATE_RE.search(ln) and len(ln) < 200]
    events = []
    for n, i in enumerate(anchors):
        # the item starts at the title line just above the date line, ends before the next item's title
        begin = i - 1 if i > 0 and lines[i - 1] and not DATE_RE.search(lines[i - 1]) else i
        stop = (anchors[n + 1] - 1) if n + 1 < len(anchors) else min(len(lines), i + 15)
        block = [ln for ln in lines[begin:max(stop, i + 1)] if ln]
        if not block:
            continue
        day = _parse_day(DATE_RE.search(lines[i]).group(0), today)
        if not day or not (start <= day <= end):
            continue
        body = "\n".join(block)
        title = re.sub(URL_RE, "", block[0]).strip(" <>|–-") if begin < i else re.sub(URL_RE, "", subject)
        food = detect_food(title, body)
        if food["status"] not in ("confirmed", "likely"):
            continue
        hm = _parse_time(lines[i]) or _parse_time(body)
        start_dt = datetime(day.year, day.month, day.day, *(hm or (0, 0)), tzinfo=TZ)
        loc = ""
        for ln in block:
            m = LOC_RE.match(ln)
            if m:
                loc = m.group(1)
                break
        if not loc and "|" in lines[i]:
            loc = lines[i].split("|", 1)[1]
        url = (URL_RE.findall(body) or [""])[0]
        events.append(Event(
            source_id="newsletter", source_name=f"Newsletter: {one_line(subject)[:80]}",
            title=one_line(title)[:200] or one_line(subject), url=url.rstrip(".,>"),
            start=start_dt, all_day=hm is None, location=one_line(re.sub(URL_RE, "", loc)).strip(" <>"),
            description=re.sub(r"\s*<https?://[^>]+>", "", body),
            extra={"origin": origin, "newsletter_subject": one_line(subject)},
        ))
    return events


class NewsletterSource:
    id, name = "newsletter", "Newsletters (inbox/ and IMAP)"
    homepage = ""

    def fetch(self, start, end, http):
        out = []
        for msg, origin in list(self._files()) + list(self._imap()):
            subject = str(msg.get("subject", "")) or origin
            out += extract_items(_message_text(msg), subject, start, end, origin=origin)
        return out

    def _files(self):
        if not INBOX_DIR.exists():
            return
        for path in sorted(INBOX_DIR.rglob("*")):
            suffix = path.suffix.lower()
            if path.stem.lower() == "readme":
                continue
            if suffix == ".eml":
                yield email.message_from_bytes(path.read_bytes(), policy=policy.default), path.name
            elif suffix in (".txt", ".md", ".html", ".htm"):
                raw = path.read_text(encoding="utf-8", errors="replace")
                msg = email.message.EmailMessage()
                msg["Subject"] = path.stem
                msg.set_content(raw, subtype="html" if suffix in (".html", ".htm") else "plain")
                yield msg, path.name

    def _imap(self):
        host, user, pw = (os.environ.get(k) for k in ("FFM_IMAP_HOST", "FFM_IMAP_USER", "FFM_IMAP_PASSWORD"))
        if not (host and user and pw):
            return
        since = (datetime.now() - timedelta(days=int(os.environ.get("FFM_IMAP_SINCE_DAYS", "14")))).strftime("%d-%b-%Y")
        senders = [s.strip() for s in os.environ.get("FFM_IMAP_FROM", "").split(",") if s.strip()]
        with imaplib.IMAP4_SSL(host) as box:
            box.login(user, pw)
            box.select(os.environ.get("FFM_IMAP_FOLDER", "INBOX"), readonly=True)
            queries = [f'(SINCE {since} FROM "{s}")' for s in senders] or [f"(SINCE {since})"]
            ids = set()
            for q in queries:
                _typ, data = box.search(None, q)
                ids.update(data[0].split())
            for num in sorted(ids):
                _typ, data = box.fetch(num, "(BODY.PEEK[])")
                if data and isinstance(data[0], tuple):
                    yield email.message_from_bytes(data[0][1], policy=policy.default), f"imap:{num.decode()}"
