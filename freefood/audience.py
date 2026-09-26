"""Who may attend? Flags events limited to one school, a class year, a House, members, or invitees.

Plain-language version: Nieman Fellows hold Harvard IDs, so "open to Harvard ID
holders" or "Harvard community" events are fine for them. They are not students
of a particular school, not undergraduates, not House residents and not members
of student groups, so events limited to those groups are flagged.

Each event gets one level, from most to least open:
    public      open to everyone
    harvard     Harvard ID holders / Harvard community: fellows qualify
    unknown     the listing does not say
    likely      probably limited, inferred from context ("Sophomore Advising", a House event, a GBM)
    restricted  the listing or its text limits it to a group fellows are not part of

Rigorous version, in order of authority (the first rule that fires decides):
    1. listing fields: HLS "Audiences", College class-year tags, Gazette "Harvard Key Required"
    2. strong clues: 1L/2L/LLM or class-year titles, House hosts, club meetings (GBM, subcite,
       new members), advising/info sessions/recruiting, HLS student groups and student-services offices
    3. explicit sentences: "open to HLS students only", "by invitation", "HUID holders only"
       (sentences about the livestream/Zoom part are ignored)
    4. calendar defaults: College calendar -> undergraduates; HLS calendar -> probably HLS only
       (except talks by HLS research programs)
The site hides both "restricted" and "likely" by default.
"""
import re

from .text import one_line, sentences

SCHOOLS = (r"hls|harvard law(?: school)?|law school|hks|kennedy school|hbs|business school|gsd|design school|"
           r"hgse|gse|education school|hds|divinity(?: school)?|seas|fas|gsas|hms|medical school|hsph|chan school|"
           r"harvard college|the college|extension school|radcliffe|dental school")
GROUP_NOUN = (r"students?|undergrad\w*|residents?|members?|affiliates?|holders?|faculty|staff|fellows?|alumni|"
              r"concentrators?|attendees|participants|admits|1ls?|2ls?|3ls?|ll\.?ms?|j\.?d\.?s?|sjds?|first[- ]years?|"
              r"sophomores?|juniors?|seniors?|women|community|employees|scholars|invitees|mbas?|mpps?|mpas?|"
              r"ph\.?d\.? (?:students|candidates)|cohort|tutors")

HARVARD_WIDE = re.compile(
    r"\b(?:harvard (?:university )?id|huid|harvard key|harvard community|harvard (?:university )?affiliates?|"
    r"university affiliates?|all harvard|members of the harvard|harvard university community|id holders?|"
    r"harvard faculty,? (?:and )?staff|fellows)\b", re.I)
PUBLIC_WIDE = re.compile(r"\b(?:the (?:general )?public|everyone|anyone|all(?: are)? welcome|all interested|"
                         r"a wide audience|open to all)\b", re.I)
NARROW = re.compile(
    rf"\b(?:{SCHOOLS})\b|undergrad|\bhouse\b|residents?|members?|\b[123]ls?\b|ll\.?ms?\b|\bj\.?d\.?s?\b|sjd|"
    rf"first[- ]years?|sophomores?|juniors?|seniors?|concentrators?|invit|admitted|admits|\bfaculty\b|\bstaff\b|"
    rf"alumni|employees|\bmbas?\b|\bmpps?\b|\bmpas?\b|ph\.?d|doctoral|cohort|participants|enrolled|registered",
    re.I)

INVITE = re.compile(r"\b(?:by invitation(?: only)?|invitation[- ]only|invite[- ]only|private (?:event|dinner|lunch|reception)|"
                    r"closed (?:event|meeting|session|door))\b", re.I)
NOT_PUBLIC = re.compile(r"\bnot open to the (?:general )?public\b", re.I)
OPEN_TO = re.compile(
    r"\b(?:is |are |be |remains )?(?:only |exclusively )?(?:open|available|limited|restricted|exclusive|reserved)"
    r"\s+(?:only\s+|exclusively\s+)?(?:to|for)\s+(?P<g>[^.;:!?()]{2,100})", re.I)
ONLY_AFTER = re.compile(rf"(?P<g>(?:\b[\w’'&./-]+\s+){{0,5}}\b(?:{GROUP_NOUN}))\s+only\b", re.I)
ONLY_BEFORE = re.compile(rf"\bonly (?:for |to )?(?P<g>(?:current |registered |enrolled |admitted )?(?:\b[\w’'&./-]+\s+){{0,3}}"
                         rf"(?:{GROUP_NOUN}))\s+(?:may|can|are|will|should)\b", re.I)
PUBLIC_SENT = re.compile(r"\b(?:(?:free and )?open to the (?:general )?public|all are welcome|everyone is welcome|"
                         r"the public is (?:welcome|invited)|open to all)\b", re.I)
REMOTE = re.compile(r"\b(?:virtual|zoom|livestream|live stream|online|webinar|recording|remote(?:ly)?)\b", re.I)

# --- inference from context -------------------------------------------------------------
LAW_YEAR = re.compile(r"\b(?:1ls?|2ls?|3ls?|ll\.?ms?|sjds?)\b", re.I)
UNDERGRAD = re.compile(
    r"\b(?:first[- ]years?|freshm[ae]n|sophomores?|juniors?(?! (?:faculty|fellows?|scholars?|researchers?))|"
    r"seniors?(?! (?:common room|fellows?|lecturer|advisor|adviser|editor|counsel|scholars?|research|citizens|leaders?|officials?))|"
    r"prospective concentrators?|concentrators?|concentration (?:fair|declaration|info)|undergrad(?:uate)?s?|pre-?meds?|"
    r"declaration|house (?:residents|community|dhall|d-hall))\b", re.I)
MEMBERS = re.compile(r"\b(?:general body meeting|gbm|new members?|member(?:s|ship)? (?:meeting|training|social|dinner)|"
                     r"board meeting|subcite|tryouts?|auditions?|staff meeting|retreat|initiation|team meeting)\b", re.I)
CAREER = re.compile(r"\b(?:coffee chat|market lunch|recruiting|firm (?:kickoff|reception)|law firm|big ?law|"
                    r"interview program|\boci\b|summer internship|clerkship|career (?:fair|panel))\b", re.I)
STUDENT_SERVICE = re.compile(r"\b(?:advising|office hours|orientation|info(?:rmation)? session|drop-ins?|study (?:group|session|tips)|"
                             r"outlining|exam prep|section meeting|class meeting|language class|tutoring)\b", re.I)
HOUSES = re.compile(r"\b(adams|lowell|quincy|leverett|winthrop|eliot|kirkland|dunster|mather|cabot|currier|pforzheimer)"
                    r" house\b", re.I)


def _clean_group(g):
    g = one_line(g)
    g = re.sub(r"^(?:the|all|current|interested|only)\s+", "", g, flags=re.I)
    g = re.sub(r"\s+(?:only|who|that|and registration|and the|with|in person|in-person).*$", "", g, flags=re.I)
    return g.strip(" ,.-")[:70]


def judge(group):
    """Level implied by a stated group of people."""
    g = group.lower()
    if HARVARD_WIDE.search(g):
        return "harvard"
    if PUBLIC_WIDE.search(g) and not NARROW.search(g):
        return "public"
    if NARROW.search(g):
        return "restricted"
    if re.search(r"\bstudents?\b", g):      # "open to Harvard students": fellows are not students
        return "likely"
    return None


def _result(level, group="", evidence="", basis="none"):
    return {"level": level, "group": group, "evidence": one_line(evidence)[:200], "basis": basis}


def from_listing(extra):
    """Structured audience fields published by the calendars themselves."""
    hls = [v for v in extra.get("hls_audiences", []) if v]
    if hls:
        text = " | ".join(hls)
        if re.search(r"all harvard|harvard community|public", text, re.I):
            return _result("harvard", "", f"HLS listing audience: {text}", "listing")
        groups = []
        for v in hls:
            v = re.sub(r"\b(?:all|only)\b", "", v, flags=re.I)
            v = re.sub(r"\b([123]L|LLM)\b(?!s)", r"\1s", v)          # 1L -> 1Ls
            v = one_line(v).replace("HLS HLS", "HLS")
            if v and v not in groups:
                groups.append(v)
        label = ", ".join(groups)
        if label.upper() == "HLS":
            label = "HLS community"
        elif not re.search(r"hls", label, re.I):
            label = "HLS " + label
        return _result("restricted", label, f"HLS listing audience: {text}", "listing")
    years = extra.get("class_years") or []
    if years:
        return _result("restricted", "undergraduates (" + ", ".join(years) + ")",
                       "College calendar audience: " + ", ".join(years), "listing")
    if str(extra.get("harvard_key", "")).lower() == "yes":
        return _result("harvard", "", "Gazette listing: Harvard Key required", "listing")
    return None


def from_text(text):
    found = []                                      # (rank, result); higher rank = more restrictive
    rank = {"public": 0, "harvard": 1, "likely": 2, "restricted": 3}
    for s in sentences(text):
        remote_part = bool(REMOTE.search(s))
        if INVITE.search(s):
            found.append(_result("restricted", "invited guests", s, "text"))
            continue
        for rx in (OPEN_TO, ONLY_AFTER, ONLY_BEFORE):
            for m in rx.finditer(s):
                level = judge(m.group("g"))
                if level is None or (remote_part and level == "public"):
                    continue
                grp = _clean_group(m.group("g")) if level in ("restricted", "likely") else ""
                found.append(_result(level, grp, s, "text"))
        if NOT_PUBLIC.search(s) and not any(r["evidence"] == one_line(s)[:200] for r in found):
            found.append(_result("harvard" if HARVARD_WIDE.search(s) else "likely", "Harvard audience", s, "text"))
        elif PUBLIC_SENT.search(s) and not remote_part:
            found.append(_result("public", "", s, "text"))
    if not found:
        return None
    return max(found, key=lambda r: rank[r["level"]])


def strong_context(title, host, source_id, extra):
    """Clues that settle it even when the text says "all welcome": a 1L event, a House event,
    a club's own meeting, advising or recruiting, anything run by an HLS student group or office."""
    hosts = f"{host} {extra.get('group', '')}"
    school = {"hls": "HLS students", "college": "undergraduates", "hks": "HKS students"}.get(source_id, "students")
    if source_id == "hls" and LAW_YEAR.search(title):
        return _result("restricted", f"HLS {LAW_YEAR.search(title).group(0)} students", f"Title: {title}", "inferred")
    m = UNDERGRAD.search(title)
    if m:
        return _result("restricted", "undergraduates", f"Title mentions “{m.group(0)}”", "inferred")
    m = HOUSES.search(hosts) or HOUSES.search(title)
    if m or "house events" in " ".join(extra.get("event_types", [])).lower():
        name = m.group(0).title() if m else "House"
        return _result("restricted", f"{name} residents", f"Hosted by {name}", "inferred")
    if MEMBERS.search(title):
        return _result("restricted", "members of the organizing group", f"Title: {title}", "inferred")
    if CAREER.search(title):
        return _result("restricted", school + " (recruiting event)", f"Title: {title}", "inferred")
    if STUDENT_SERVICE.search(title):
        return _result("restricted", school, f"Title: {title}", "inferred")
    if source_id == "hls" and extra.get("student_org"):
        return _result("restricted", "HLS students", "Run by an HLS student organization", "inferred")
    if source_id == "hls" and extra.get("hls_office"):
        return _result("restricted", "HLS students", f"Run by an HLS student-services office ({extra['hls_office']})", "inferred")
    return None


def weak_context(title, host, source_id, extra):
    """Defaults for calendars that mostly serve one school, used when nothing else was said."""
    if source_id == "college":
        return _result("restricted", "Harvard College students",
                       "Harvard College calendar, no sign it is open to others", "default")
    if source_id == "hls" and not extra.get("research_program"):
        return _result("likely", "HLS community", "Harvard Law School calendar, audience not stated", "default")
    return None


def detect_audience(title, text, source_id="", host="", extra=None):
    """-> {"level", "group", "evidence", "basis"}"""
    extra = extra or {}
    return (from_listing(extra) or strong_context(title, host, source_id, extra) or from_text(text)
            or weak_context(title, host, source_id, extra) or _result("unknown"))
