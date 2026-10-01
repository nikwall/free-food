"""Email newsletters (school digests, center mailing lists, Nieman announcements).

Two ways in:
  1. Drop files into inbox/  (.eml saved from your mail client, or .txt/.html)
  2. Set FFM_IMAP_HOST / FFM_IMAP_USER / FFM_IMAP_PASSWORD (an app password for a
     mailbox that receives the newsletters; on GitHub these are repository secrets).
     Optional: FFM_IMAP_FOLDER (INBOX), FFM_IMAP_SINCE_DAYS (14), FFM_IMAP_FROM
     (comma-separated sender filters). Messages are read with BODY.PEEK, so nothing
     is marked read, moved or deleted. Fellows forward newsletters to that mailbox.

Each email is read two ways, and the results are merged like any other source:
  - Links: links that look like event pages ("Register", "Details", /events/...) are
    followed, through newsletter click-tracking redirects, and read like a suggested
    link (freefood/suggestions.py) when they land on a Harvard site.
  - Text: the email is cut into items at date lines ("Tuesday, Sept. 29, 12:15 p.m.",
    "9/29", or "Thursday at noon" resolved against the send date). An item is kept
    when it falls in the scan window and the food rules fire on it.
Forwarded emails are unwrapped first, so the original subject and date are used.
"""
import email
import imaplib
import os
import re
from datetime import date, datetime, timedelta
from email import policy
from email.utils import parseaddr, parsedate_to_datetime

from dateutil import parser as dparser

from ..config import INBOX_DIR, TZ
from ..models import Event
from ..text import html_to_text, links, one_line

MONTHS = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
DATE_RE = re.compile(
    rf"\b(?:(?:mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)[a-z]*\.?,?\s+)?{MONTHS}\s+\d{{1,2}}(?:st|nd|rd|th)?\b"
    r"|\b(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?,?\s+\d{1,2}/\d{1,2}\b|\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b",
    re.I)
TIME_RE = re.compile(r"\b(\d{1,2}(?::\d{2})?)\s*(?:[-–—]\s*\d{1,2}(?::\d{2})?\s*)?([ap])\.?\s*m\b\.?|\bnoon\b", re.I)
URL_RE = re.compile(r"https?://[^\s<>\")\]]+")
LOC_RE = re.compile(r"(?:location|where|venue|place)\s*[:\-]\s*(.+)", re.I)

# "Thursday at noon", "this Friday, 12:15 pm", "tomorrow 5-7 pm": only counted when a time is on the line
WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
REL_RE = re.compile(r"\b(?P<wd>mon|tues?|wed(?:nes)?|thu(?:rs?)?|fri|sat(?:ur)?|sun)(?:day)?\b"
                    r"|\b(?P<rel>today|tonight|tomorrow)\b", re.I)

# forwarded emails: the original newsletter sits below a marker and a short header block
FWD_MARK = re.compile(r"^\s*-{2,}\s*(?:forwarded message|original message|weitergeleitete nachricht)\s*-{2,}\s*$"
                      r"|^\s*begin forwarded message:\s*$|^\s*_{10,}\s*$", re.I | re.M)
HEADER_LINE = re.compile(r"^(from|von|sent|date|datum|gesendet|subject|betreff|to|an|cc)\s*:\s*(.*)$", re.I)
SUBJECT_PREFIX = re.compile(r"^\s*(?:(?:fwd?|wg|aw|re)\s*:\s*)+", re.I)

# links worth following: event-ish wording, never unsubscribe/social/preferences links
SKIP_LINK = re.compile(r"unsubscribe|preferences|manage (?:your )?subscription|view (?:this )?(?:email|in (?:your )?browser)|"
                       r"forward to a friend|facebook|twitter|//x\.com|instagram|linkedin|youtube|tiktok|privacy|"
                       r"update (?:your )?profile|mailto:", re.I)
EVENTISH = re.compile(r"event|calendar|register|rsvp|details|learn more|more info|read more|sign up|join us|"
                      r"talk|seminar|lecture|lunch|reception|panel|forum", re.I)
MAX_LINKS_PER_EMAIL, MAX_LINKS_PER_RUN = 15, 80

# the mailbox's own account mail (Google security alerts, welcome mail) is never a newsletter and
# must not show up in the public "newsletters received" list
SYSTEM_SENDER = re.compile(r"(^|\.)(google\.com|googlemail\.com|youtube\.com)$|^mailer-daemon|^postmaster", re.I)


def _message_parts(msg):
    """(html, plain) bodies of an email."""
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
    return html, plain


def _message_text(msg):
    """Plain text of an email with each link kept inline as 'text <url>'."""
    html, plain = _message_parts(msg)
    return _html_with_links(html) if html else plain


def _html_with_links(html):
    html = re.sub(r"<a\b[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>", r"\2 <\1>", html, flags=re.S | re.I)
    return html_to_text(html)


def _sent_date(msg):
    try:
        return parsedate_to_datetime(str(msg.get("date"))).astimezone(TZ).date()
    except (TypeError, ValueError, IndexError):
        return None


def unwrap_forward(text, subject, sent):
    """For a forwarded email, return the original's text, subject and send date."""
    subject = SUBJECT_PREFIX.sub("", subject or "")
    m = FWD_MARK.search(text)
    if not m:
        return text, subject, sent
    lines = text[m.end():].lstrip("\n").split("\n")
    hdr, i = {}, 0
    while i < len(lines) and i < 14:
        line = lines[i].strip()
        hm = HEADER_LINE.match(line)
        if hm:
            hdr[hm.group(1).lower()] = hm.group(2)
        elif line and hdr:
            break
        i += 1
    orig_subject = SUBJECT_PREFIX.sub("", hdr.get("subject") or hdr.get("betreff") or "") or subject
    when = hdr.get("date") or hdr.get("sent") or hdr.get("datum") or hdr.get("gesendet")
    try:
        sent = dparser.parse(when.replace(" at ", " "), fuzzy=True).date() if when else sent
    except (ValueError, OverflowError):
        pass
    return "\n".join(lines[i:]), orig_subject, sent


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


def _relative_day(line, ref):
    """'Thursday' -> the next Thursday on or after the send date; 'tomorrow' -> send date + 1."""
    m = REL_RE.search(line)
    if not m:
        return None
    if m.group("rel"):
        return ref + timedelta(days=1 if m.group("rel").lower() == "tomorrow" else 0)
    return ref + timedelta(days=(WEEKDAYS[m.group("wd")[:3].lower()] - ref.weekday()) % 7)


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


def _is_anchor(line):
    if len(line) >= 200:
        return False
    return bool(DATE_RE.search(line) or (REL_RE.search(line) and TIME_RE.search(line)))


def extract_items(text, subject, start, end, today=None, origin=""):
    """Cut newsletter text into dated items; return Events for items within [start, end].

    `today` is the reference date for year-less and relative dates: the email's send date.
    """
    from ..classify import detect_food  # local import: classify is independent of sources

    today = today or datetime.now(TZ).date()
    lines = [ln.strip() for ln in text.split("\n")]
    anchors = [i for i, ln in enumerate(lines) if _is_anchor(ln)]
    events = []
    for n, i in enumerate(anchors):
        # the item starts at the title line just above the date line, ends before the next item's title
        begin = i - 1 if i > 0 and lines[i - 1] and not _is_anchor(lines[i - 1]) else i
        stop = (anchors[n + 1] - 1) if n + 1 < len(anchors) else min(len(lines), i + 15)
        block = [ln for ln in lines[begin:max(stop, i + 1)] if ln]
        if not block:
            continue
        m = DATE_RE.search(lines[i])
        day = _parse_day(m.group(0), today) if m else _relative_day(lines[i], today)
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
            lm = LOC_RE.match(ln)
            if lm:
                loc = lm.group(1)
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


def linked_events(html, subject, start, end, http, budget):
    """Follow event-looking links in the email and read the Harvard event pages they lead to."""
    from ..suggestions import accepted, events_from_page   # local import: suggestions imports this module

    out, seen, tried = [], set(), 0
    for text, href in links(html):
        if tried >= MAX_LINKS_PER_EMAIL or budget[0] <= 0:
            break
        if not href.startswith("http") or href in seen or SKIP_LINK.search(f"{text} {href}"):
            continue
        if not (EVENTISH.search(text) or EVENTISH.search(href)):
            continue
        seen.add(href)
        tried += 1
        budget[0] -= 1
        try:
            r = http.s.get(href, timeout=20)          # follows click-tracking redirects to the real page
            r.raise_for_status()
        except Exception:
            continue
        if not accepted({"url": r.url}):
            continue
        try:
            found = events_from_page(r.url, r.text, http)
        except Exception:
            continue
        for d in found[:5]:
            if d.get("start") and start <= d["start"].astimezone(TZ).date() <= end:
                out.append(Event(
                    source_id="newsletter", source_name=f"Newsletter: {one_line(subject)[:80]}",
                    title=d["title"], url=d["url"] or r.url, start=d["start"], end=d.get("end"),
                    all_day=d.get("all_day", False), location=d.get("location", ""), description=d["description"],
                    online=d.get("online", False), extra={"newsletter_subject": one_line(subject)}))
    return out


class NewsletterSource:
    id, name = "newsletter", "Newsletters (forwarded to the project inbox)"
    homepage = ""

    def __init__(self):
        self.report = []      # one line per email for the Suggest page: subject, date, events found

    def fetch(self, start, end, http):
        out, self.report = [], []
        budget = [MAX_LINKS_PER_RUN]
        messages = list(self._files()) + list(self._imap())
        skipped = 0
        for msg, origin in messages:
            sender = parseaddr(str(msg.get("from", "")))[1].lower()
            if sender and (SYSTEM_SENDER.search(sender.split("@")[-1]) or SYSTEM_SENDER.search(sender)):
                skipped += 1
                continue
            html, plain = _message_parts(msg)
            text = _html_with_links(html) if html else plain
            text, subject, sent = unwrap_forward(text, str(msg.get("subject", "")) or origin, _sent_date(msg))
            found = extract_items(text, subject, start, end, today=sent, origin=origin)
            if html:
                found += linked_events(html, subject, start, end, http, budget)
            out += found
            # the subject is published only when the email held events, so a mis-forwarded mail stays private
            self.report.append({"subject": one_line(subject)[:100] if found else None,
                                "sent": sent.isoformat() if sent else None, "items": len(found)})
        print(f"  newsletter   {len(messages) - skipped} emails read ({skipped} account emails skipped), "
              f"{len(out)} items before food/audience checks", flush=True)
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
            box.login(user, pw.replace(" ", ""))
            box.select(os.environ.get("FFM_IMAP_FOLDER", "INBOX"), readonly=True)
            queries = [f'(SINCE {since} FROM "{s}")' for s in senders] or [f"(SINCE {since})"]
            ids = set()
            for q in queries:
                _typ, data = box.search(None, q)
                ids.update(data[0].split())
            for num in sorted(ids, key=int):
                _typ, data = box.fetch(num, "(BODY.PEEK[])")
                if data and isinstance(data[0], tuple):
                    yield email.message_from_bytes(data[0][1], policy=policy.default), f"imap:{num.decode()}"
