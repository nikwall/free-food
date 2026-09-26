"""HTML-to-text helpers shared by sources and the classifier."""
import html as htmllib
import re

import lxml.html

BLOCK_TAGS = ("p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article")


def html_to_text(fragment):
    """Plain text with line breaks at block boundaries; entities decoded."""
    if not fragment:
        return ""
    if "<" not in fragment:
        return clean(htmllib.unescape(fragment))
    try:
        root = lxml.html.fromstring(f"<div>{fragment}</div>")
    except (lxml.etree.ParserError, ValueError):
        return clean(htmllib.unescape(re.sub(r"<[^>]+>", " ", fragment)))
    for bad in root.xpath("//script|//style"):
        bad.drop_tree()
    for el in root.iter(*BLOCK_TAGS):
        el.tail = "\n" + (el.tail or "")
        if el.tag == "br":
            continue
        el.text = "\n" + (el.text or "")
    return clean(root.text_content())


def clean(text):
    text = htmllib.unescape(text or "").replace("\xa0", " ").replace("​", "")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n[ \n]*", "\n", text)
    return text.strip()


def one_line(text):
    return re.sub(r"\s+", " ", clean(text)).strip()


def sentences(text):
    """Split into sentences / lines. Good enough for keyword-in-context rules."""
    parts = []
    for line in (text or "").split("\n"):
        parts.extend(p.strip() for p in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9“\"(])", line) if p.strip())
    return parts


def links(fragment):
    """(text, href) pairs for every anchor in an HTML fragment."""
    if not fragment or "<a" not in fragment:
        return []
    try:
        root = lxml.html.fromstring(f"<div>{fragment}</div>")
    except (lxml.etree.ParserError, ValueError):
        return []
    return [(one_line(a.text_content()), a.get("href", "")) for a in root.iter("a") if a.get("href")]
