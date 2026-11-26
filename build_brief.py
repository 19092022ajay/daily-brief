#!/usr/bin/env python3
"""Daily news brief: topic sections, each with India (domestic) + Global stories.
Free RSS feeds only. Python standard library only."""
import sys, re, html, datetime as dt, urllib.request, xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

HERE = Path(__file__).parent
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
UA = {"User-Agent": "Mozilla/5.0 (compatible; DailyBriefBot/1.0)"}
MAX_AGE_HOURS = 72          # ignore stories older than this
BREAKING_HOURS = 12         # a story must be this fresh to be "Breaking"
MAX_BREAKING = 3

# ---- EDIT HERE: topics, and the feeds for each region (first working feed wins) ----
TOPICS = [
  ("Business", [
    ("India",  [("The Hindu BusinessLine", "https://www.thehindubusinessline.com/feeder/default.rss"),
                ("Indian Express", "https://indianexpress.com/section/business/feed/")]),
    ("Global", [("BBC News", "http://feeds.bbci.co.uk/news/business/rss.xml"),
                ("The Guardian", "https://www.theguardian.com/uk/business/rss")])]),
  ("Markets", [
    ("India",  [("Economic Times", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
                ("Indian Express", "https://indianexpress.com/section/business/feed/")]),
    ("Global", [("CNBC", "https://www.cnbc.com/id/20910258/device/rss/rss.html"),
                ("BBC News", "http://feeds.bbci.co.uk/news/business/rss.xml")])]),
  ("Economics", [
    ("India",  [("Economic Times", "https://economictimes.indiatimes.com/news/economy/rssfeeds/1373380680.cms"),
                ("The Hindu", "https://www.thehindu.com/business/Economy/feeder/default.rss")]),
    ("Global", [("The Guardian", "https://www.theguardian.com/business/economics/rss"),
                ("CNBC", "https://www.cnbc.com/id/20910258/device/rss/rss.html")])]),
  ("Geopolitics", [
    ("India",  [("The Hindu", "https://www.thehindu.com/news/international/feeder/default.rss"),
                ("Indian Express", "https://indianexpress.com/section/world/feed/")]),
    ("Global", [("BBC News", "http://feeds.bbci.co.uk/news/world/rss.xml"),
                ("The Guardian", "https://www.theguardian.com/world/rss")])]),
  ("Politics", [
    ("India",  [("The Hindu", "https://www.thehindu.com/news/national/feeder/default.rss"),
                ("Indian Express", "https://indianexpress.com/section/india/feed/")]),
    ("Global", [("The Guardian", "https://www.theguardian.com/us-news/us-politics/rss"),
                ("BBC News", "http://feeds.bbci.co.uk/news/politics/rss.xml")])]),
  ("Tech", [
    ("India",  [("Economic Times", "https://economictimes.indiatimes.com/tech/rssfeeds/13357270.cms"),
                ("Indian Express", "https://indianexpress.com/section/technology/feed/")]),
    ("Global", [("TechCrunch", "https://techcrunch.com/feed/"),
                ("The Verge", "https://www.theverge.com/rss/index.xml")])]),
  ("Investing & Finance", [
    ("India",  [("Economic Times", "https://economictimes.indiatimes.com/wealth/rssfeeds/837555174.cms"),
                ("Mint", "https://www.livemint.com/rss/money")]),
    ("Global", [("CNBC", "https://www.cnbc.com/id/15839069/device/rss/rss.html"),
                ("The Guardian", "https://www.theguardian.com/business/rss")])]),
  ("Digital Marketing", [
    ("India",  [("Social Samosa", "https://www.socialsamosa.com/feed/"),
                ("Search Engine Land", "https://searchengineland.com/feed")]),
    ("Global", [("PPC Land", "https://ppc.land/feed/"),
                ("Search Engine Land", "https://searchengineland.com/feed")])]),
]
# Feeds scanned for Breaking news (top headlines)
BREAKING_FEEDS = [("BBC News", "http://feeds.bbci.co.uk/news/rss.xml"),
                  ("The Hindu", "https://www.thehindu.com/feeder/default.rss")]
BREAKING_WORDS = ("breaking", "just in", "urgent", "flash")
IMPACT_WORDS = ("killed", "dead", "dies", "attack", "explosion", "earthquake", "crash", "resigns", "resignation",
                "ceasefire", "invades", "strikes", "collapse", "arrested", "sanctions", "emergency", "rate cut",
                "rate hike", "plunge", "surge", "default", "shutdown")
# -------------------------------------------------------------------------------------

NS = {"media": "http://search.yahoo.com/mrss/", "content": "http://purl.org/rss/1.0/modules/content/",
      "atom": "http://www.w3.org/2005/Atom", "dc": "http://purl.org/dc/elements/1.1/"}
EPOCH = dt.datetime.min.replace(tzinfo=dt.timezone.utc)

def fetch(url, timeout=12):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
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
    body = item.findtext("content:encoded", "", NS) or item.findtext("description") or ""
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

def parse_feed(data):
    root = ET.fromstring(data)
    items = []
    for it in root.iter("item"):
        items.append(dict(title=clean(it.findtext("title"), 140), link=(it.findtext("link") or "").strip(),
                          summary=clean(it.findtext("description") or it.findtext("content:encoded", "", NS)),
                          date=parse_date(it.findtext("pubDate") or it.findtext("dc:date", "", NS)),
                          image=feed_image(it)))
    for it in root.findall("atom:entry", NS):
        l = it.find("atom:link", NS)
        items.append(dict(title=clean(it.findtext("atom:title", "", NS), 140), link=l.get("href") if l is not None else "",
                          summary=clean(it.findtext("atom:summary", "", NS) or it.findtext("atom:content", "", NS)),
                          date=parse_date(it.findtext("atom:updated", "", NS)), image=None))
    items = [i for i in items if i["title"] and i["link"]]
    items.sort(key=lambda i: i["date"] or EPOCH, reverse=True)
    return items

def age_hours(i):
    return (dt.datetime.now(dt.timezone.utc) - i["date"]).total_seconds() / 3600 if i["date"] else 9999

def is_breaking(i):
    text = (i["title"] + " " + i["summary"]).lower()
    if age_hours(i) > BREAKING_HOURS:
        return False
    return any(w in text for w in BREAKING_WORDS) or (age_hours(i) < 6 and any(w in text for w in IMPACT_WORDS))

def pick(feeds, used):
    for source, url in feeds:
        try:
            items = parse_feed(fetch(url))
        except Exception as e:
            print(f"[warn] {source} {url}: {e}", file=sys.stderr)
            continue
        for i in items:
            if i["title"].lower() in used or age_hours(i) > MAX_AGE_HOURS:
                continue
            used.add(i["title"].lower())
            i["source"] = source
            return i
    return None

def find_breaking(used):
    found = []
    for source, url in BREAKING_FEEDS:
        try:
            items = parse_feed(fetch(url))[:12]
        except Exception as e:
            print(f"[warn] breaking {source}: {e}", file=sys.stderr)
            continue
        for i in items:
            if is_breaking(i) and i["title"].lower() not in used:
                used.add(i["title"].lower()); i["source"] = source; found.append(i)
    found.sort(key=lambda i: i["date"] or EPOCH, reverse=True)
    return found[:MAX_BREAKING]

def esc(s): return html.escape(s or "", quote=True)
def slug(s): return re.sub(r"[^a-z]+", "-", s.lower()).strip("-")

def poster(i, g, label, breaking):
    img = (f'<img src="{esc(i["image"])}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">'
           if i.get("image") else "")
    k = "kicker-breaking" if breaking else "kicker-normal"
    return (f'<div class="poster g{g}">{img}<div class="poster-scrim"></div><div class="poster-top">'
            f'<span class="kicker {k}">{esc(label)}</span><h2 class="poster-headline">{esc(i["title"])}</h2></div>'
            f'<span class="poster-brand">{esc(i["source"])}</span></div>')

def foot(i):
    d = i["date"].astimezone(IST).strftime("%b %d, %Y") if i.get("date") else ""
    return (f'<div class="story-foot"><span class="story-source">{esc(i["source"])} &middot; {d}</span>'
            f'<span class="story-cta">Read full report &rarr;</span></div>')

def card(i, g, label):
    return (f'<a class="story-link pure-entry" href="{esc(i["link"])}" target="_blank" rel="noopener noreferrer">'
            f'{poster(i, g, label, False)}<div class="pure-body"><p class="story-copy">{esc(i["summary"])}</p>{foot(i)}</div></a>')

def breaking_row(i, n):
    return (f'<a class="story-link split-row" href="{esc(i["link"])}" target="_blank" rel="noopener noreferrer">'
            f'{poster(i, 1, "Breaking", True)}<div class="split-right"><div class="split-index breaking">{n:02d} &middot; Breaking</div>'
            f'<div class="split-copy-box breaking"><p class="story-copy">{esc(i["summary"])}</p>{foot(i)}</div></div></a>')

def demo_item(label):
    return dict(title=f"Sample headline: {label}", link="https://example.com", source="Sample Source",
                summary="This is a sample summary line that shows how your daily brief will look once real news is pulled in.",
                date=dt.datetime.now(dt.timezone.utc), image=None)

def build(demo=False):
    used, sections, total = set(), [], 0
    breaking = [demo_item("Breaking")] if demo else find_breaking(used)
    if breaking:
        rows = "".join(breaking_row(i, n + 1) for n, i in enumerate(breaking))
        sections.append(("Breaking", f'<section class="topic" id="breaking"><h2 class="topic-head breaking">Breaking</h2>{rows}</section>'))
    for ti, (topic, regions) in enumerate(TOPICS):
        cards = []
        for region, feeds in regions:
            i = demo_item(f"{topic} {region}") if demo else pick(feeds, used)
            if i:
                cards.append(i); i["label"] = f"{topic} · {region}"
        if not cards:
            continue
        for i in cards:
            if not i.get("image") and not demo:
                i["image"] = og_image(i["link"])
        total += len(cards)
        body = "".join(card(i, (ti + n) % 6 + 1, i["label"]) for n, i in enumerate(cards))
        sections.append((topic, f'<section class="topic" id="{slug(topic)}"><h2 class="topic-head"><span>{esc(topic)}</span><span class="head-note">India &middot; Global</span></h2><div class="pure-grid">{body}</div></section>'))
    if not sections:
        raise SystemExit("No stories fetched; keeping the previous page.")
    nav = '<nav class="topnav">' + "".join(f'<a href="#{slug(t)}">{esc(t)}</a>' for t, _ in sections) + "</nav>"
    date = dt.datetime.now(IST).strftime("%A, %d %B %Y")
    page = (HERE / "template.html").read_text(encoding="utf-8").replace("{{DATE}}", date) \
        .replace("{{CONTENT}}", nav + "\n" + "\n".join(s for _, s in sections))
    out = HERE / "docs"; (out / "archive").mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(page, encoding="utf-8")
    (out / "archive" / f"{dt.datetime.now(IST):%Y-%m-%d}.html").write_text(page, encoding="utf-8")
    print(f"Built {total} topic stories + {len(breaking)} breaking for {date}")

if __name__ == "__main__":
    build(demo="--demo" in sys.argv)
