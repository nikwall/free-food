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

Emails a fellow forwarded (sent by a person, not a mailing list, and marked as a forward)
feed the site's "Events" view: every dated item in them is kept, food or not, up to
FORWARD_DAYS ahead, tagged with the forwarder's first name.
"""
import email
import imaplib
import os
import re
from datetime import date, datetime, timedelta
from email import policy
from email.utils import parseaddr, parsedate_to_datetime

from dateutil import parser as dparser

from ..config import FORWARD_DAYS, FORWARD_LOOKBACK_DAYS, INBOX_DIR, TZ
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
FWD_SUBJECT = re.compile(r"^\s*(?:(?:re|aw)\s*:\s*)*(?:fwd?|wg|tr)\s*:", re.I)

# A newsletter as the list sent it carries list headers; a person's forward does not. Only a person's
# forward counts as "a fellow shared this" (a center admin mailing from Outlook has no forward marker).
BULK_HEADERS = ("list-id", "list-unsubscribe", "list-post")
BULK_PRECEDENCE = re.compile(r"bulk|list|junk", re.I)
NEWSLETTER_SINCE_DAYS = int(os.environ.get("FFM_IMAP_SINCE_DAYS", "14"))

# lines above a date line that are details, not the event's title
NOT_TITLE = re.compile(
    r"^(?:must|please|rsvp|register|registration|join|click|location|where|when|time|date|venue|room|address|"
    r"open to|space is|seating|this event|tickets?|cost|admission|hosted by|sponsored by|co-?sponsored|presented by|"
    r"moderated by|speakers?|featuring|learn more|read more|more info|details|view|watch|livestream|add to calendar|"
    r"in[- ]person|online|virtual|zoom|free and open|all are welcome|doors open|"
    # section headers of a digest, and lines that continue a sentence
    r"upcoming|later this|this week|next week|coming up|save the date|in case you missed|more events|featured|"
    r"plus|and|or|but|also|so|directed by|written by|starring|produced by|"
    # header lines of a forwarded email inside a forward
    r"(?:subject|from|sent|to|cc|betreff|von|an)(?=\s*:))\b", re.I)
# "Sanders Theatre, Memorial Hall": a place, written the way titles are
PLACE_LINE = re.compile(r"^[^:,]{2,50},[^:,]{2,50}$")
PLACE_WORD = re.compile(r"\b(?:theat(?:re|er)|hall|building|room|center|centre|auditorium|forum|library|museum|"
                        r"house|chapel|street|st\.|ave(?:nue)?|square|floor|lobby|lounge|penthouse)\b", re.I)
# a line that is cut off mid-sentence, a speaker bio ("X is the former ..."), or film data ("1997, DCP, 145 min.")
FRAGMENT_END = re.compile(r"\b(?:with|and|or|the|of|for|at|to|in|on|a|an|our|by|from|featuring)$", re.I)
NOT_TITLE_ANYWHERE = re.compile(r"\b\d{2,3}\s*min\b|\b(?:dcp|35\s?mm|16\s?mm)\b", re.I)
ABBREV_END = re.compile(r"\b(?:jr|sr|dr|st|amb|sen|rep|gov|prof|u\.s|d\.c)\.$", re.I)
MAX_ITEMS_PER_EMAIL = 25

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

# "Please confirm your subscription" mails: when the sender is a Harvard address, the scanner opens the
# confirm link itself, so a fellow can sign the inbox up to a list without anyone clicking anything.
CONFIRM_SUBJECT = re.compile(r"confirm|verif|activate|opt.?in|subscription request|subscribe request|welcome|bestätig", re.I)
CONFIRM_LINK = re.compile(r"confirm|verif|activate|yes,? (?:please )?(?:subscribe|sign me up|add me)|subscribe me|opt.?in|bestätig", re.I)
CONFIRMED_PAGE = re.compile(r"confirmed|thank|success|you(?:'|’)re (?:on the list|subscribed|in)|subscribed|welcome", re.I)
CONFIRM_MAX_AGE_DAYS = 3


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
    # escaped, so the HTML parser keeps "<url>" as text instead of reading it as a tag
    html = re.sub(r"<a\b[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>", r"\2 &lt;\1&gt;", html, flags=re.S | re.I)
    return html_to_text(html)


INLINE_URL = re.compile(r"\s*<https?://[^>\s]*>")


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


def _titleish(line):
    """The line as an event title, or "" when it reads like something else."""
    t = re.sub(URL_RE, "", INLINE_URL.sub("", line)).strip(" <>|–—-•*·:")
    if not (4 <= len(t) <= 140) or NOT_TITLE.match(t) or NOT_TITLE_ANYWHERE.search(t):
        return ""
    if t[0].islower() or FRAGMENT_END.search(t):
        return ""                         # continues or breaks off a sentence
    if t.endswith(".") and not ABBREV_END.search(t) and (len(t.split()) >= 4 or len(t) > 60):
        return ""                         # a sentence, e.g. a speaker's bio
    if len(t.split()) == 1 and t.endswith("."):
        return ""                         # "Amb." left over from a broken line
    if PLACE_LINE.match(t) and PLACE_WORD.search(t):
        return ""                         # the event's place
    if (TIME_RE.search(t) or DATE_RE.search(t)) and len(re.findall(r"[^\W\d_]{2,}", DATE_RE.sub(" ", TIME_RE.sub(" ", t)))) < 2:
        return ""                         # only a date or time ("6:00–9:00pm")
    return t


def _title_for(lines, i, floor):
    """Title for the date line lines[i] -> (title or "", index of the title line).

    The nearest title-like line among the three non-empty lines above it (never above `floor`, the line after
    the previous date line); else the date line itself minus date and time, when that leaves a short name
    ("Oct 13, 6 pm: Pathways to Public Service").
    """
    seen = 0
    for j in range(i - 1, floor - 1, -1):
        if not lines[j]:
            continue
        if _is_anchor(lines[j]) or seen == 3:
            break
        seen += 1
        t = _titleish(lines[j])
        if t:
            return t, j
    rest = DATE_RE.sub(" ", TIME_RE.sub(" ", re.sub(URL_RE, "", lines[i])))
    rest = re.sub(r"\s+", " ", re.sub(r"\b(?:at|from|to|on|until)\b|[,|–—-]", " ", rest, flags=re.I)).strip(" :.")
    rest = _titleish(rest) if len(rest.split()) >= 3 and len(rest) <= 100 else ""
    return rest, i


def extract_items(text, subject, start, end, today=None, origin="", keep_all=False):
    """Cut newsletter text into dated items; return Events for items within [start, end].

    `today` is the reference date for year-less and relative dates: the email's send date. An item is kept when
    the food rules fire on it; with keep_all (an email a fellow forwarded) every item is kept.
    """
    from ..classify import detect_food  # local import: classify is independent of sources

    today = today or datetime.now(TZ).date()
    raw = [ln.strip() for ln in text.split("\n")]
    # dates, times and titles are read without the inline link targets ("/2026/10/13/" is not a date)
    lines = [INLINE_URL.sub("", ln).strip() for ln in raw]
    anchors = [i for i, ln in enumerate(lines) if _is_anchor(ln)]
    # each date line gets a title line; an item runs from its title line to just before the next item's
    heads, floor = [], 0
    for i in anchors:
        title, top = _title_for(lines, i, floor)
        heads.append((i, title, top))
        floor = i + 1
    events, seen = [], set()
    for n, (i, title, top) in enumerate(heads):
        stop = heads[n + 1][2] if n + 1 < len(heads) else min(len(lines), i + 15)
        block = [ln for ln in lines[top:max(stop, i + 1)] if ln]
        raw_block = "\n".join(raw[top:max(stop, i + 1)])
        if not block:
            continue
        m = DATE_RE.search(lines[i])
        day = _parse_day(m.group(0), today) if m else _relative_day(lines[i], today)
        if not day or not (start <= day <= end):
            continue
        if not title:
            if keep_all and len(anchors) > 1:
                continue          # a dated line in a digest with nothing that names it: skip rather than guess
            title = re.sub(URL_RE, "", subject).strip()
        body = "\n".join(block)
        if not keep_all and detect_food(title, body)["status"] not in ("confirmed", "likely"):
            continue
        if (day, title.lower()) in seen:
            continue
        seen.add((day, title.lower()))
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
        url = (URL_RE.findall(raw_block) or [""])[0]
        events.append(Event(
            source_id="newsletter", source_name=f"Newsletter: {one_line(subject)[:80]}",
            title=one_line(title)[:200] or one_line(subject), url=url.rstrip(".,>"),
            start=start_dt, all_day=hm is None, location=one_line(re.sub(URL_RE, "", loc)).strip(" <>"),
            description=re.sub(r"\s*<https?://[^>]+>", "", body),
            extra={"origin": origin, "newsletter_subject": one_line(subject)},
        ))
        if len(events) >= MAX_ITEMS_PER_EMAIL:
            break
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


def first_name(display):
    """'Nakashima, Ellen' -> 'Ellen'; 'Ellen Nakashima' -> 'Ellen'; '' when there is no usable name."""
    display = re.sub(r"\(.*?\)|\[.*?\]|[\"']", "", display or "").strip()
    if "@" in display:
        return ""
    if "," in display:
        display = display.split(",", 1)[1]
    parts = [w for w in display.split() if re.match(r"^[^\W\d_][\w.\-’]*$", w)]
    name = parts[0][:24] if parts else ""
    return name[:1].upper() + name[1:] if name.islower() else name


def forwarded_by(msg, text):
    """For an email a fellow forwarded: their first name ('' if the mail gives none). None otherwise.

    "Forwarded by a fellow" = sent by a person (no mailing-list headers, not an auto-reply) and marked as a
    forward, by the subject (Fwd:, FW:, WG:) or a forwarded-message block in the text.
    """
    if any(msg.get(h) for h in BULK_HEADERS) or BULK_PRECEDENCE.search(str(msg.get("precedence", ""))):
        return None
    if str(msg.get("auto-submitted", "no")).lower() not in ("", "no"):
        return None
    if not (FWD_SUBJECT.match(str(msg.get("subject", ""))) or FWD_MARK.search(text or "")):
        return None
    return first_name(one_line(parseaddr(str(msg.get("from", "")))[0]))


def confirm_subscription(msg, html, plain, subject, sent, http):
    """For a recent 'please confirm' mail from a Harvard sender, open its confirm link.

    -> None (not a confirmation mail), "confirmed", or "needs_click" (a person has to confirm in Gmail).
    """
    from ..suggestions import accepted   # local import: suggestions imports this module

    if not CONFIRM_SUBJECT.search(subject or ""):
        return None
    candidates = links(html) if html else [("", u) for u in URL_RE.findall(plain or "")]
    confirm = [href for text, href in candidates
               if href.startswith("http") and not SKIP_LINK.search(f"{text} {href}")
               and (CONFIRM_LINK.search(text) or CONFIRM_LINK.search(href))]
    if not confirm:
        return None                      # a "welcome" mail without anything to confirm
    sender = parseaddr(str(msg.get("from", "")))[1].lower()
    harvard_sender = bool(sender) and accepted({"url": "https://" + sender.split("@")[-1] + "/"})
    too_old = sent and (datetime.now(TZ).date() - sent).days > CONFIRM_MAX_AGE_DAYS
    if not harvard_sender or too_old:
        return "needs_click"
    try:
        r = http.s.get(confirm[0], timeout=20)
        if r.ok and CONFIRMED_PAGE.search(html_to_text(r.text)[:4000]):
            return "confirmed"
    except Exception:
        pass
    return "needs_click"


def _prefer_pages(text_items, page_items):
    """Drop text items at the same day and time (within 15 minutes) as an event page the email links to:
    the page has the real title, place and link."""
    def clash(a, b):
        same_day = a.start.astimezone(TZ).date() == b.start.astimezone(TZ).date()
        return same_day and (a.all_day or b.all_day or abs((a.start - b.start).total_seconds()) <= 900)
    kept = []
    for t in text_items:
        pages = [p for p in page_items if clash(t, p) and (not t.all_day or p.all_day)]
        if not pages:
            kept.append(t)
            continue
        for p in pages:                   # a page that gives only the date takes the email's time
            if p.all_day and not t.all_day and len(pages) == 1:
                p.start, p.all_day = t.start, False
    return kept + page_items


class NewsletterSource:
    id, name = "newsletter", "Newsletters (forwarded to the project inbox)"
    homepage = ""

    def __init__(self):
        self.report = []      # one line per email for the Suggest page: subject, date, events found

    def fetch(self, start, end, http):
        from ..suggestions import accepted   # local import: suggestions imports this module

        out, self.report = [], []
        budget = [MAX_LINKS_PER_RUN]
        fwd_end = start + timedelta(days=FORWARD_DAYS - 1)
        news_since = start - timedelta(days=NEWSLETTER_SINCE_DAYS)
        rows, skipped = [], 0
        for msg, origin in list(self._files()) + list(self._imap()):
            sender = parseaddr(str(msg.get("from", "")))[1].lower()
            if sender and (SYSTEM_SENDER.search(sender.split("@")[-1]) or SYSTEM_SENDER.search(sender)):
                skipped += 1
                continue
            html, plain = _message_parts(msg)
            raw_text = _html_with_links(html) if html else plain
            rows.append((msg, origin, sender, html, plain, raw_text, forwarded_by(msg, raw_text)))
        # fellows' forwards first, so they always get their share of the link budget
        rows.sort(key=lambda r: r[6] is None)
        n_read = n_fwd = 0
        for msg, origin, sender, html, plain, raw_text, by in rows:
            sent_outer = _sent_date(msg)
            if by is None and sent_outer and sent_outer < news_since:
                continue          # the mailbox is read further back for forwards; ordinary newsletters: 2 weeks
            n_read += 1
            text, subject, sent = unwrap_forward(raw_text, str(msg.get("subject", "")) or origin, sent_outer)
            # a center's own newsletter is named in the public report; a person's mail never is
            harvard = bool(sender) and accepted({"url": "https://" + sender.split("@")[-1] + "/"})
            who = (one_line(parseaddr(str(msg.get("from", "")))[0]) or sender.split("@")[-1])[:60] \
                if harvard and by is None else None
            if by is not None:
                n_fwd += 1
                found = extract_items(text, subject, start, fwd_end, today=sent, origin=origin, keep_all=True)
                if html:
                    found = _prefer_pages(found, linked_events(html, subject, start, fwd_end, http, budget))
                tag = {"by": by or None, "subject": one_line(subject)[:120]}
                for ev in found:
                    ev.extra["forwarded"] = tag
                    ev.source_name = f"Forwarded: {one_line(subject)[:80]}"
                out += found
                self.report.append({"subject": one_line(subject)[:100] if found else None,
                                    "sent": sent.isoformat() if sent else None, "items": len(found),
                                    "sender": None, "forwarded_by": by or "a fellow"})
                continue
            confirm = confirm_subscription(msg, html, plain, subject, sent, http)
            if confirm:
                # list name is shown only for Harvard senders (those are the ones confirmed automatically)
                self.report.append({"subject": one_line(subject)[:100] if confirm == "confirmed" else None,
                                    "sent": sent.isoformat() if sent else None, "items": 0, "confirm": confirm,
                                    "sender": who})
                continue
            found = extract_items(text, subject, start, end, today=sent, origin=origin)
            if html:
                found = _prefer_pages(found, linked_events(html, subject, start, end, http, budget))
            out += found
            # the subject is published only when the email held events or came from a Harvard sender,
            # so a mis-forwarded personal mail stays private
            self.report.append({"subject": one_line(subject)[:100] if (found or harvard) else None,
                                "sent": sent.isoformat() if sent else None, "items": len(found), "sender": who})
        print(f"  newsletter   {n_read} emails read ({n_fwd} forwarded by fellows, {skipped} account emails "
              f"skipped), {len(out)} items before food/audience checks", flush=True)
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
        # forwards are read further back than newsletters (fetch() drops newsletters older than 14 days)
        since = (datetime.now() - timedelta(days=max(NEWSLETTER_SINCE_DAYS, FORWARD_LOOKBACK_DAYS))).strftime("%d-%b-%Y")
        senders = [s.strip() for s in os.environ.get("FFM_IMAP_FROM", "").split(",") if s.strip()]
        from ..suggestions import accepted   # local import: suggestions imports this module

        with imaplib.IMAP4_SSL(host) as box:
            box.login(user, pw.replace(" ", ""))
            # Gmail files new senders' newsletters under Spam fairly often; read that folder too, but only
            # for mail from Harvard senders. The folder is found by its \Junk flag (its name is localized).
            folders = [(os.environ.get("FFM_IMAP_FOLDER", "INBOX"), False)]
            _typ, listing = box.list()
            for raw in listing or []:
                line = raw.decode(errors="replace") if isinstance(raw, bytes) else str(raw)
                if "\\Junk" in line:
                    folders.append((line.rsplit(' "/" ', 1)[-1].strip(), True))
            queries = [f'(SINCE {since} FROM "{s}")' for s in senders] or [f"(SINCE {since})"]
            for folder, harvard_only in folders:
                if box.select(folder, readonly=True)[0] != "OK":
                    continue
                ids = set()
                for q in queries:
                    _typ, data = box.search(None, q)
                    ids.update(data[0].split())
                for num in sorted(ids, key=int):
                    _typ, data = box.fetch(num, "(BODY.PEEK[])")
                    if not (data and isinstance(data[0], tuple)):
                        continue
                    msg = email.message_from_bytes(data[0][1], policy=policy.default)
                    if harvard_only:
                        sender = parseaddr(str(msg.get("from", "")))[1].lower()
                        if not (sender and accepted({"url": "https://" + sender.split("@")[-1] + "/"})):
                            continue
                    yield msg, f"imap:{'spam:' if harvard_only else ''}{num.decode()}"
