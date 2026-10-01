"""Rule-based reading of event text: is there food, what kind, and do I need to register?

Plain-language version: an event counts as a food event when one sentence
names a food ("lunch", "reception", "pizza", ...) AND says it is being given
out ("will be served", "provided", "to follow", "join us for"...). That is a
*confirmed* food event, and the sentence is kept as evidence so a reader can
check it. Food words in the title alone ("Lunch Seminar", "Opening
Reception") make an event *likely*. Sentences about food as a topic ("food
insecurity") or food you must bring or buy ("brown-bag", "for purchase")
never count. A plausibility check also drops food that is not for the people
attending ("cat and dog treats"), figures of speech ("food for thought") and
excluded food ("non-pizza lunch").

Rigorous version: per sentence s, after deleting topical and implausible phrases T(s):
    food(s)    = any FOOD_TYPES regex matches T(s)
    provide(s) = STRONG matches s, or WEAK matches T(s) within WEAK_REACH characters of a food word
                 (STRONG sentences are preferred as evidence)
    negate(s)  = NEGATE matches s
    confirmed  <=> exists s: food(s) & provide(s) & ~negate(s)
    likely     <=> ~confirmed & (TITLE_LIKELY(title) | LIKELY_PHRASE(text)), no negation
Online-only events are never food events.
"""
import re

from .text import links, one_line, sentences

FOOD_TYPES = [  # (label, regex), in display priority
    ("Dinner", r"\b(?:dinner|supper)s?\b"),
    ("Lunch", r"\b(?:lunch(?:eon)?|lunches|lunchtime)\b"),
    ("Breakfast", r"\b(?:breakfast|brunch|bagels?)\b"),
    ("Pizza", r"\bpizzas?\b"),
    ("Reception", r"\b(?:reception|hors d['’]?oeuvres|appeti[sz]ers|canap[eé]s|cocktails?|wine|beer|light bites|happy hour)\b"),
    ("Snacks", r"\b(?:refreshments?|snacks?|nibbles|finger foods?|light fare)\b"),
    ("Coffee", r"\b(?:coffee|tea|espresso|pastr(?:y|ies)|croissants?|muffins?)\b"),
    ("Sweets", r"\b(?:desserts?|ice cream|cakes?|cupcakes|cookies|donuts?|doughnuts?|sweets|treats|boba|bubble tea|chocolate)\b"),
    ("Food", r"\b(?:food|meals?|catered|catering|dumplings|tacos|burritos|sandwiches|bbq|barbe?cue|cookout|empanadas|samosas|drinks)\b"),
]
FOOD_RES = [(label, re.compile(rx, re.I)) for label, rx in FOOD_TYPES]

# Food as the *subject* of an event, not something on the table.
TOPIC = re.compile(
    r"\bfood[- ](?:insecurity|security|systems?|polic(?:y|ies)|justice|waste|access|sovereignty|studies|history|"
    r"science|environments?|supply|chains?|prices?|banks?|pantr(?:y|ies)|aid|assistance|stamps|safety|industry|"
    r"deserts?|labels?|cultures?|ways|politics|economy|economics|production|choices?)\b"
    r"|\b(?:nutrition(?:al)?|hunger|famine|agricultur\w*|obesity|eating disorders?)\b"
    r"|\breception (?:of|history|theory|in)\b|\bcritical reception\b|\breception (?:desk|area)\b"
    r"|\btea party\b|\bcoffee ?shop\b|\bcoffeehouse\b|\bchocolate (?:industry|trade)\b",
    re.I)

# Strong cues say outright that food is given out; weak cues imply it ("join us for pizza").
STRONG = re.compile(
    r"\b(?:will|shall|would) be (?:served|provided|available|offered|included|catered)\b"
    r"|\b(?:is|are) (?:served|provided|included|available|offered|catered)\b"
    r"|\b(?:served|provided|catered|complimentary|on us|on the house)\b"
    r"|\bfree (?:food|lunch|dinner|breakfast|pizza|snacks|refreshments|coffee|drinks|boba|ice cream|bagels|donuts)\b"
    r"|\b(?:reception|refreshments|lunch|dinner|drinks) (?:to follow|will follow|follows|afterwards?)\b"
    r"|\bfollowed by (?:a |an )?(?:light |small |brief |wine |cocktail )?(?:reception|lunch|dinner|refreshments|drinks)\b",
    re.I)
WEAK = re.compile(
    r"\b(?:to follow|will follow|follows|followed by|following the (?:talk|event|lecture|discussion|panel|program)|"
    r"afterwards?|preceded by)\b"
    r"|\b(?:join us for|stop by for|come (?:by|for)|grab|enjoy|there will be|we will have|we['’]ll have|"
    r"we['’]ll be serving|we will be serving|serving|will feature|featuring|we begin with)\b"
    r"|\bwith (?:a |an |some )?(?:light |free |delicious |catered |boxed |buffet )?"
    r"(?:lunch|dinner|breakfast|brunch|pizza|refreshments|snacks|reception|food|drinks|coffee)\b"
    r"|\b(?:light|boxed|buffet|catered|hot|free) (?:lunch|dinner|breakfast|refreshments|reception|snacks|meal)",
    re.I)

NEGATE = re.compile(
    r"\bbring (?:your|a|their) (?:own )?(?:lunch|food|dinner|breakfast)\b|\bbyo[lbf]?\b|\bbrown[- ]bag"
    r"|\bfor (?:purchase|sale)\b|\bto purchase\b|\bpurchase (?:food|lunch|dinner|tickets)\b|\bcash bar\b"
    r"|\bnot (?:be )?(?:provided|served|included|available)\b|\bno (?:food|lunch|refreshments|dinner|meals?|drinks)\b"
    r"|\b(?:will not|won['’]t) be (?:provided|served)\b|\bpotluck\b|\bown expense\b|\bvendors?\b|\bfood trucks?\b"
    r"|\$\s?\d+(?:\.\d\d)?\s*(?:per|a|/|each)\s*(?:person|plate|head|guest)\b"
    r"|\b(?:tickets?|admission|cost|fee|price)\b[^.!?$]{0,25}\$\s?\d",
    re.I)

# Plausibility check. A food word plus a "served"/"we will have" cue is not enough when the food
# is not for the people attending ("cat and dog treats"), is a figure of speech ("food for
# thought"), or is explicitly excluded ("non-pizza lunch"). Such phrases are blanked out before a
# sentence is read; when that is what kept an event off the map, the reason is kept as `doubt`.
ANIMAL = (r"(?:cats?|dogs?|pets?|pupp(?:y|ies)|pups?|kittens?|canines?|felines?|horses?|birds?|animals?|"
          r"dogg(?:y|ie)s?|(?:furry|four[- ]legged) (?:friends?|companions?))(?:['’]s?)?")
IMPLAUSIBLE = [  # (reason shown to readers, regex); checked on sentences, not titles, except animal food
    ("food for animals",
     rf"\b{ANIMAL}(?:\s*(?:,|and|&|or|/)\s*{ANIMAL})*\s+(?:treats|food|snacks|biscuits|cookies|chews|kibble|feed|chow)\b"
     rf"|\b(?:treats|food|snacks|biscuits|cookies)\s+for\s+(?:your\s+|the\s+|our\s+|all\s+)?(?:beloved\s+)?{ANIMAL}"
     r"|\bkibble\b|\bbird ?seed\b"),
    ("figure of speech",
     r"\bfood for thought\b|\bpiece of cake\b|\bmolotov cocktails?\b|\b(?:the )?last supper\b|\bspill(?:s|ing)? the tea\b"
     r"|\bcocktail of\b|\b(?:eye|ear|brain) candy\b|\bcake ?walk\b|\btreats? (?:you|yourself|them)\b"),
]
IMPLAUSIBLE_RES = [(why, re.compile(rx, re.I)) for why, rx in IMPLAUSIBLE]
EXCLUDED = re.compile(r"\bnon-\s?\w+|\b(?:instead of|rather than|other than) (?:a |an |the |the usual )?\w+", re.I)
WEAK_REACH = 60   # a weak cue counts only within this many characters of the food word

TITLE_LIKELY = re.compile(
    r"\b(?:lunch(?:eon)?|dinner|breakfast|brunch|pizza|reception|refreshments|snacks|"
    r"coffee (?:hour|chat|break|social|and|&)|tea (?:time|hour)|afternoon tea|happy hour|cookout|bbq|barbe?cue|"
    r"ice cream|food for thought|bagels?|donuts?|feast|banquet|social hour|mixer|welcome party|dessert)\b",
    re.I)

LIKELY_PHRASE = re.compile(
    r"\b(?:lunch(?:time)?|dinner|breakfast|pizza) (?:seminar|talk|series|discussion|lecture|conversation|workshop|"
    r"meeting|forum|session|colloquium|roundtable|panel)\b"
    r"|\b(?:and|with|plus|&|opening|closing|welcome|holiday|wine|cocktail|book launch) reception\b"
    r"|\breception (?:to follow|will follow|afterwards?|following)\b",
    re.I)

REG_ENCOURAGED = re.compile(
    r"\b(?:registration|rsvps?|registering|pre-registration)(?: is| are)? (?:strongly |highly )?"
    r"(?:encouraged|recommended|appreciated|requested|preferred|suggested)\b"
    r"|\bencouraged to (?:register|rsvp)\b|\bnot required,? but (?:is )?(?:encouraged|recommended|appreciated)\b",
    re.I)
REG_NONE = re.compile(
    r"\bno (?:registration|rsvp|tickets?|sign[- ]?ups?|reservations?) (?:is |are )?(?:required|necessary|needed)\b"
    r"|\b(?:registration|rsvp|tickets?|reservations?) (?:is |are )?not (?:required|necessary|needed)\b"
    r"|\bwithout (?:registration|an? rsvp)\b|\bdrop[- ]in\b|\bwalk[- ]ins? (?:are )?welcome\b|\bjust (?:show|drop) (?:up|by)\b"
    r"|\bfirst[- ]come,? first[- ]serve",
    re.I)
REG_REQUIRED = re.compile(
    r"\b(?:registration|rsvps?|pre-registration|advance registration|tickets?|reservations?) "
    r"(?:is |are )?(?:required|necessary|mandatory|needed|essential)\b"
    r"|\bmust (?:register|rsvp|sign up|reserve|have a ticket)\b"
    r"|\b(?:please )?(?:register|rsvp)(?: here| now| today| online| in advance| by| at| for| to attend| via| through| using|:| below)"
    r"|\bto (?:register|rsvp)\b|\bregistration (?:link|form|is open|opens|deadline|page)\b"
    r"|\b(?:sign up|reserve (?:a|your) (?:seat|spot|ticket))\b|\bspace is limited\b|\bseating is limited\b"
    r"|\btickets? (?:are )?(?:available|free|required)\b",
    re.I)
REG_LINK = re.compile(r"regist|rsvp|eventbrite|forms\.gle|tfaforms|qualtrics|sign[- ]?up|ticket|reserve|evite", re.I)


def _food_labels(text):
    return [label for label, rx in FOOD_RES if rx.search(text)]


def _trim(s, n=240):
    s = one_line(s)
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0] + "…"


def _screen(s, is_title=False):
    """Blank out topical and implausible food phrases. -> (text left to read, reasons for what was removed)"""
    body, reasons = TOPIC.sub(" ", s), []
    for why, rx in IMPLAUSIBLE_RES:
        if is_title and why != "food for animals":
            continue      # "Food for Thought" is a real lunch series name
        if any(_food_labels(m.group(0)) for m in rx.finditer(body)):
            reasons.append(why)
        body = rx.sub(" ", body)
    return EXCLUDED.sub(" ", body), reasons


def _near(body, cue_rx, reach=WEAK_REACH):
    """True when a cue match and a food word lie within `reach` characters of each other."""
    cues = [m.span() for m in cue_rx.finditer(body)]
    foods = [m.span() for _, rx in FOOD_RES for m in rx.finditer(body)]
    return any(max(c0, f0) - min(c1, f1) <= reach for c0, c1 in cues for f0, f1 in foods)


def detect_food(title, text, online=False):
    """-> {"status": confirmed|likely|byo|none, "types": [...], "evidence": str, "doubt"?: str}"""
    if online:
        return {"status": "none", "types": [], "evidence": ""}
    confirmed, likely, negated, doubts = [], [], [], []
    for s in [title] + sentences(text):
        body, reasons = _screen(s, is_title=s is title)
        labels = _food_labels(body)
        if not labels:
            # Would this sentence have counted without the plausibility check? Then say why it didn't.
            if reasons and s is not title and (STRONG.search(s) or WEAK.search(s)) and not NEGATE.search(s):
                doubts.append(f"{', '.join(reasons)}: “{_trim(s, 160)}”")
            continue
        if NEGATE.search(s):
            negated.append(s)
        elif s is not title and STRONG.search(s):
            confirmed.append((0, s, labels))
        elif s is not title and _near(body, WEAK):
            confirmed.append((1, s, labels))
        elif LIKELY_PHRASE.search(body):
            likely.append((s, labels))
    title_body = _screen(title, is_title=True)[0]
    result = _decide(title, title_body, confirmed, likely, negated)
    if doubts and result["status"] != "confirmed":
        result["doubt"] = doubts[0]
    return result


def _decide(title, title_body, confirmed, likely, negated):
    """Pick the status from the sentences sorted into confirmed / likely / negated."""
    if confirmed:
        types = []
        for _rank, _s, labels in confirmed:
            types += [lb for lb in labels if lb not in types]
        best = min(confirmed, key=lambda c: c[0])   # prefer a strong-cue sentence as evidence
        return {"status": "confirmed", "types": _order(types), "evidence": _trim(best[1]),
                "cue": "strong" if best[0] == 0 else "weak"}
    if TITLE_LIKELY.search(title_body) and not NEGATE.search(title):
        return {"status": "likely", "types": _order(_food_labels(title_body) or ["Food"]), "evidence": _trim(title)}
    if likely:
        return {"status": "likely", "types": _order(likely[0][1]), "evidence": _trim(likely[0][0])}
    if negated:
        return {"status": "byo", "types": [], "evidence": _trim(negated[0])}
    return {"status": "none", "types": [], "evidence": ""}


def _order(types):
    order = [label for label, _ in FOOD_TYPES]
    types = sorted(set(types), key=order.index)
    # "Food"/"Coffee" add nothing next to a specific meal.
    if len(types) > 1 and "Food" in types:
        types.remove("Food")
    return types


def detect_registration(text, html="", hint="", link=""):
    """-> {"status": required|recommended|none|unknown, "evidence": str, "link": str}"""
    reg_link = link
    if not reg_link:
        for label, href in links(html):
            if REG_LINK.search(label) or REG_LINK.search(href):
                reg_link = href
                break
    sents = sentences(text)
    for rx, status in ((REG_ENCOURAGED, "recommended"), (REG_NONE, "none"), (REG_REQUIRED, "required")):
        for s in sents:
            if rx.search(s):
                return {"status": status, "evidence": _trim(s, 180), "link": reg_link if status != "none" else ""}
    if hint in ("required", "rsvp"):
        return {"status": "required", "evidence": "RSVP link on the event page", "link": reg_link}
    if reg_link:
        return {"status": "required", "evidence": "Registration link on the event page", "link": reg_link}
    return {"status": "unknown", "evidence": "", "link": ""}
