#!/usr/bin/env python3
"""Daily news updater for the teacher app. Runs on GitHub Actions every morning.
Fetches articles from Google News RSS searches, keeps the last 21 days, writes news.json.
Optional: if the ANTHROPIC_API_KEY secret is set, adds Persian translations of titles/summaries."""
import json, os, re, html, urllib.request, urllib.parse, datetime, email.utils
import xml.etree.ElementTree as ET

TOPICS = [
    ("آموزش کودک", "early childhood education research"),
    ("آموزش زبان به کودک", "teaching English to young learners"),
    ("گاردنر و هوش‌های چندگانه", "Howard Gardner multiple intelligences"),
    ("یادگیری بازی‌محور", "play-based learning preschool"),
    ("رشد کودک", "child development research preschool"),
    ("ADHD و تمرکز", "ADHD preschool classroom strategies"),
    ("اوتیسم", "autism early childhood classroom"),
    ("فنلاند", "Finland early childhood education"),
    ("مونته‌سوری و رجیو", "Montessori OR \"Reggio Emilia\" preschool"),
]
EXTRA_FEEDS = [("رشد کودک", "https://www.sciencedaily.com/rss/mind_brain/child_development.xml")]
KEEP_DAYS, PER_TOPIC, MAX_ITEMS = 21, 6, 80
UA = {"User-Agent": "Mozilla/5.0 (teacher-app news bot)"}

def gnews(q):
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": q + " when:7d", "hl": "en-US", "gl": "US", "ceid": "US:en"})

def clean(t):
    t = html.unescape(re.sub(r"<[^>]+>", " ", t or ""))
    return re.sub(r"\s+", " ", t).strip()

def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read()

def parse(xml_bytes, topic):
    out = []
    root = ET.fromstring(xml_bytes)
    for it in root.iter("item"):
        title = clean(it.findtext("title"))
        link = (it.findtext("link") or "").strip()
        src_el = it.find("source")
        source = clean(src_el.text) if src_el is not None and src_el.text else ""
        if source and title.endswith(" - " + source):
            title = title[: -len(" - " + source)]
        desc = clean(it.findtext("description"))
        if source and desc.endswith(source):
            desc = desc[: -len(source)].strip()
        if desc.startswith(title):
            desc = ""
        pub = it.findtext("pubDate") or ""
        try:
            dt = email.utils.parsedate_to_datetime(pub)
        except Exception:
            dt = datetime.datetime.now(datetime.timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        if title and link:
            out.append({"title": title, "link": link, "source": source, "summary": desc[:400],
                        "topic": topic, "ts": dt.timestamp(), "date": dt.strftime("%Y-%m-%d")})
    return out

def translate(items):
    key = os.environ.get("ANTHROPIC_API_KEY")
    todo = [i for i in items if not i.get("fa_title")]
    if not key or not todo:
        return
    for start in range(0, len(todo), 15):
        batch = todo[start:start + 15]
        payload = [{"id": n, "title": i["title"], "summary": i.get("summary", "")} for n, i in enumerate(batch)]
        prompt = ("Translate these news items for an Iranian preschool English teacher into fluent Persian. "
                  "Return ONLY a JSON array of objects {id, fa_title, fa_summary}.\n" + json.dumps(payload, ensure_ascii=False))
        body = json.dumps({"model": os.environ.get("ANTHROPIC_MODEL", "claude-haiku-5-5"), "max_tokens": 4000,
                           "messages": [{"role": "user", "content": prompt}]}).encode()
        req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
            "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                text = json.loads(r.read())["content"][0]["text"]
            arr = json.loads(text[text.index("["): text.rindex("]") + 1])
            for o in arr:
                it = batch[int(o["id"])]
                it["fa_title"], it["fa_summary"] = o.get("fa_title", ""), o.get("fa_summary", "")
        except Exception as e:
            print("translation skipped:", e)

def main():
    try:
        old = json.load(open("news.json", encoding="utf-8")).get("items", [])
    except Exception:
        old = []
    fresh = []
    sources = [(t, gnews(q)) for t, q in TOPICS] + EXTRA_FEEDS
    for topic, url in sources:
        try:
            fresh += parse(fetch(url), topic)[:PER_TOPIC]
        except Exception as e:
            print("feed failed:", topic, e)
    seen, merged = set(), []
    for it in sorted(fresh + old, key=lambda x: x.get("ts", 0), reverse=True):
        k = re.sub(r"\W+", "", it["title"].lower())[:80]
        if k in seen:
            continue
        seen.add(k)
        merged.append(it)
    cutoff = datetime.datetime.now(datetime.timezone.utc).timestamp() - KEEP_DAYS * 86400
    merged = [i for i in merged if i.get("ts", 0) >= cutoff][:MAX_ITEMS]
    translate(merged)
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3, minutes=30)))
    json.dump({"updated": now.strftime("%Y-%m-%d %H:%M"), "updated_fa": now.strftime("%Y-%m-%d ساعت %H:%M (تهران)"),
               "items": merged}, open("news.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("items:", len(merged))

if __name__ == "__main__":
    main()
