#!/usr/bin/env python3
"""Builds the daily news brief page from free RSS feeds. Python standard library only."""
import sys, re, html, json, datetime as dt, urllib.request, xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

HERE = Path(__file__).parent
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
UA = {"User-Agent": "Mozilla/5.0 (compatible; DailyBriefBot/1.0)"}
MAX_AGE_HOURS = 72
BREAKING_WORDS = ("breaking", "just in", "urgent", "live updates")

# (label, source name, feed URL). Edit freely: add, remove or swap feeds.
SLOTS = [
    ("Business · Global",     "BBC News",         "http://feeds.bbci.co.uk/news/business/rss.xml"),
    ("Markets · India",       "Economic Times",   "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    ("Investing · Global",    "CNBC",             "https://www.cnbc.com/id/10000664/device/rss/rss.html"),
    ("Economics · India",     "Economic Times",   "https://economictimes.indiatimes.com/news/economy/rssfeeds/1373380680.cms"),
    ("Economics · Global",    "The Guardian",     "https://www.theguardian.com/business/economics/rss"),
    ("Geopolitics · Global",  "BBC News",         "http://feeds.bbci.co.uk/news/world/rss.xml"),
    ("Politics · India",      "The Hindu",        "https://www.thehindu.com/news/national/feeder/default.rss"),
    ("Politics · Global",     "The Guardian",     "https://www.theguardian.com/us-news/us-politics/rss"),
    ("Tech · Global",         "TechCrunch",       "https://techcrunch.com/feed/"),
    ("Digital Marketing",     "PPC Land",         "https://ppc.land/feed/"),
]
# Spare feeds used if a slot's feed is down or empty.
BACKUP = {
    "Markets · India": "https://indianexpress.com/section/business/feed/",
    "Tech · Global": "https://www.theverge.com/rss/index.xml",
    "Digital Marketing": "https://searchengineland.com/feed",
}
NS = {"media": "http://search.yahoo.com/mrss/", "content": "http://purl.org/rss/1.0/modules/content/",
      "atom": "http://www.w3.org/2005/Atom", "dc": "http://purl.org/dc/elements/1.1/"}

def fetch(url, timeout=12):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def clean(text, limit=230):
    text = re.sub(r"<[^>]+>", " ", html.unescape(text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
    return cut[: end + 1] if end > 80 else cut.rsplit(" ", 1)[0] + "…"

def parse_date(s):
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s)
    except Exception:
        try:
            d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)

def feed_image(item):
    for tag in ("media:content", "media:thumbnail"):
        for el in item.findall(tag, NS):
            if el.get("url") and (el.get("medium", "image") == "image" or "image" in el.get("type", "image")):
                return el.get("url")
    for el in item.findall("enclosure"):
        if "image" in el.get("type", ""):
            return el.get("url")
    body = (item.findtext("content:encoded", "", NS) or item.findtext("description") or "")
    m = re.search(r'<img[^>]+src=["\']([^"\']+)', html.unescape(body))
    return m.group(1) if m else None

def og_image(url):
    try:
        page = fetch(url, timeout=8)[:300000].decode("utf-8", "ignore")
        m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', page) or \
            re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', page)
        return html.unescape(m.group(1)) if m else None
    except Exception:
        return None

def read_feed(url):
    root = ET.fromstring(fetch(url))
    items = []
    for it in root.iter("item"):
        link = (it.findtext("link") or "").strip()
        items.append(dict(title=clean(it.findtext("title"), 140), link=link,
                          summary=clean(it.findtext("description") or it.findtext("content:encoded", "", NS)),
                          date=parse_date(it.findtext("pubDate") or it.findtext("dc:date", "", NS)),
                          image=feed_image(it)))
    for it in root.findall("atom:entry", NS):
        l = it.find("atom:link", NS)
        items.append(dict(title=clean(it.findtext("atom:title", "", NS), 140), link=l.get("href") if l is not None else "",
                          summary=clean(it.findtext("atom:summary", "", NS) or it.findtext("atom:content", "", NS)),
                          date=parse_date(it.findtext("atom:updated", "", NS)), image=None))
    return [i for i in items if i["title"] and i["link"]]

def pick(label, source, url, used):
    now = dt.datetime.now(dt.timezone.utc)
    for u in (url, BACKUP.get(label)):
        if not u:
            continue
        try:
            items = read_feed(u)
        except Exception as e:
            print(f"[warn] {label}: {u} failed: {e}", file=sys.stderr)
            continue
        items.sort(key=lambda i: i["date"] or dt.datetime.min.replace(tzinfo=dt.timezone.utc), reverse=True)
        for i in items:
            if i["title"].lower() in used:
                continue
            if i["date"] and (now - i["date"]).total_seconds() > MAX_AGE_HOURS * 3600:
                continue
            used.add(i["title"].lower())
            i.update(label=label, source=source)
            return i
    return None

def is_breaking(i):
    text = (i["title"] + " " + i["summary"]).lower()
    fresh = i["date"] and (dt.datetime.now(dt.timezone.utc) - i["date"]).total_seconds() < 3 * 3600
    return any(w in text for w in BREAKING_WORDS) or (fresh and "Geopolitics" in i["label"] and "attack" in text)

def esc(s): return html.escape(s or "", quote=True)

def poster(i, g, breaking):
    img = f'<img src="{esc(i["image"])}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">' if i.get("image") else ""
    label = "Breaking" if breaking else esc(i["label"])
    k = "kicker-breaking" if breaking else "kicker-normal"
    return (f'<div class="poster g{g}">{img}<div class="poster-scrim"></div><div class="poster-top">'
            f'<span class="kicker {k}">{label}</span><h2 class="poster-headline">{esc(i["title"])}</h2></div>'
            f'<span class="poster-brand">{esc(i["source"])}</span></div>')

def foot(i):
    d = i["date"].astimezone(IST).strftime("%b %d, %Y") if i.get("date") else ""
    return (f'<div class="story-foot"><span class="story-source">{esc(i["source"])} &middot; {d}</span>'
            f'<span class="story-cta">Read full report &rarr;</span></div>')

def grid_card(i, g):
    return (f'<a class="story-link pure-entry" href="{esc(i["link"])}" target="_blank" rel="noopener noreferrer">'
            f'{poster(i, g, False)}<div class="pure-body"><p class="story-copy">{esc(i["summary"])}</p>{foot(i)}</div></a>')

def split_row(i, g, idx, breaking, closing=False):
    c = " closing" if closing else ""
    b = " breaking" if breaking else ""
    tag = "Breaking" if breaking else esc(i["label"])
    return (f'<a class="story-link split-row{c}" href="{esc(i["link"])}" target="_blank" rel="noopener noreferrer">'
            f'{poster(i, g, breaking)}<div class="split-right"><div class="split-index{b}">{idx:02d} &middot; {tag}</div>'
            f'<div class="split-copy-box{b}"><p class="story-copy">{esc(i["summary"])}</p>{foot(i)}</div></div></a>')

DEMO = [dict(label=l, source=s, title=f"Sample headline for {l}", link="https://example.com",
             summary="This is a sample summary line that shows how your daily brief will look once real news is pulled in.",
             date=dt.datetime.now(dt.timezone.utc), image=None) for l, s, _ in SLOTS]

def build(demo=False):
    used, stories = set(), []
    if demo:
        stories = [dict(x) for x in DEMO]
    else:
        for label, source, url in SLOTS:
            i = pick(label, source, url, used)
            if i:
                stories.append(i)
    if not stories:
        raise SystemExit("No stories fetched; keeping the previous page.")
    for i in stories:
        if not i.get("image") and not demo:
            i["image"] = og_image(i["link"])
    flags = [is_breaking(i) for i in stories]
    hero = flags.index(True) if True in flags else 0
    order = [hero] + [n for n in range(len(stories)) if n != hero]
    stories = [stories[n] for n in order]; flags = [flags[n] for n in order]
    parts, n, gi = [split_row(stories[0], 1, 1, flags[0])], 1, 2
    rest = stories[1:]; rflags = flags[1:]
    closing = None
    if len(rest) % 2 == 1:
        closing = (rest.pop(), rflags.pop())
    for k in range(0, len(rest), 2):
        parts.append('<section class="pure-grid">' + grid_card(rest[k], gi % 6 + 1) + grid_card(rest[k + 1], (gi + 1) % 6 + 1) + '</section>')
        gi += 2
    if closing:
        parts.append(split_row(closing[0], 3, len(stories), closing[1], closing=True))
    date = dt.datetime.now(IST).strftime("%A, %d %B %Y")
    page = (HERE / "template.html").read_text(encoding="utf-8").replace("{{DATE}}", date).replace("{{CONTENT}}", "\n".join(parts))
    out = HERE / "docs"; (out / "archive").mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(page, encoding="utf-8")
    (out / "archive" / f"{dt.datetime.now(IST):%Y-%m-%d}.html").write_text(page, encoding="utf-8")
    print(f"Built {len(stories)} stories for {date}")

if __name__ == "__main__":
    build(demo="--demo" in sys.argv)
