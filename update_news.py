#!/usr/bin/env python3
"""Daily updater for the teacher app (GitHub Actions, every morning).
Fetches education news, translates it to Persian and creates fresh daily ideas with FREE AI
(keyless Pollinations by default; Gemini/OpenRouter free keys if provided as secrets). Writes news.json."""
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

def llm(prompt, want_json=True):
    """Free AI only: Gemini/OpenRouter/Pollinations keys if present in env, otherwise keyless Pollinations."""
    sysmsg = ("You are an expert early-childhood English teacher trainer and Persian content writer for an Iranian preschool "
              "English teacher (kids 3-7, play-based, Gardner multiple intelligences). Write fluent Persian; keep classroom English phrases in English. "
              "Never invent fake statistics, testimonials or links. Never diagnose children or suggest medication; activities must be safe "
              "(no pressure on a child's body, no small objects for under-4s, no fire, no food without allergy check, no breath-holding). "
              "Respect Iranian cultural and religious norms.")
    full = prompt + ("\n\nReturn ONLY valid JSON, no markdown." if want_json else "")
    def parse(t):
        if not want_json: return t
        t = t.replace("```json", "").replace("```", "")
        return json.loads(t[t.index("{"): t.rindex("}") + 1]) if "{" in t else json.loads(t[t.index("["): t.rindex("]") + 1])
    tries = []
    if os.environ.get("GEMINI_API_KEY"):
        tries.append(("gemini", None))
    if os.environ.get("OPENROUTER_API_KEY"):
        tries.append(("openrouter", None))
    tries.append(("pollinations", None))
    for name, _ in tries:
        try:
            if name == "gemini":
                url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key=" + os.environ["GEMINI_API_KEY"]
                body = {"systemInstruction": {"parts": [{"text": sysmsg}]}, "contents": [{"role": "user", "parts": [{"text": full}]}],
                        "generationConfig": {"temperature": 0.95, **({"responseMimeType": "application/json"} if want_json else {})}}
                req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=120) as r:
                    j = json.loads(r.read())
                return parse("".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"]))
            msgs = [{"role": "system", "content": sysmsg}, {"role": "user", "content": full}]
            if name == "openrouter":
                url, hdr, model = "https://openrouter.ai/api/v1/chat/completions", {"Authorization": "Bearer " + os.environ["OPENROUTER_API_KEY"]}, "openrouter/free"
            else:
                key = os.environ.get("POLLINATIONS_KEY")
                url, hdr, model = (("https://gen.pollinations.ai/v1/chat/completions", {"Authorization": "Bearer " + key}, "openai") if key
                                   else ("https://text.pollinations.ai/openai", {}, "openai"))
            req = urllib.request.Request(url, data=json.dumps({"model": model, "messages": msgs, "temperature": 0.95}).encode(),
                                         headers={"Content-Type": "application/json", **UA, **hdr})
            with urllib.request.urlopen(req, timeout=180) as r:
                raw = r.read().decode("utf-8", "replace")
            try:
                t = json.loads(raw)["choices"][0]["message"]["content"]
            except Exception:
                t = raw
            return parse(t)
        except Exception as e:
            print("llm failed:", name, e)
    return None

def translate(items):
    todo = [i for i in items if not i.get("fa_title")][:20]
    if not todo:
        return
    payload = [{"id": n, "title": i["title"], "summary": i.get("summary", "")[:300]} for n, i in enumerate(todo)]
    res = llm("Translate these news items for an Iranian preschool English teacher into fluent Persian. "
              'Return JSON {"items":[{"id":0,"fa_title":"","fa_summary":""}]}.\n' + json.dumps(payload, ensure_ascii=False))
    try:
        for o in (res or {}).get("items", []):
            it = todo[int(o["id"])]
            it["fa_title"], it["fa_summary"] = o.get("fa_title", ""), o.get("fa_summary", "")
    except Exception as e:
        print("translation parse failed:", e)

def validate_daily(d):
    if not isinstance(d, dict): return None
    les = d.get("lessons")
    if not isinstance(les, list): return None
    les = [l for l in les if isinstance(l, dict) and str(l.get("title", "")).strip() and str(l.get("idea", "")).strip()]
    if not les: return None
    for l in les:
        l["say"] = [str(x) for x in l.get("say", []) if isinstance(x, (str, int))] if isinstance(l.get("say"), list) else []
    g = d.get("game") if isinstance(d.get("game"), dict) else {}
    ig = d.get("ig") if isinstance(d.get("ig"), dict) else {}
    return {"tip": str(d.get("tip", "")), "lessons": les[:3],
            "game": {"title": str(g.get("title", "")), "how": str(g.get("how", ""))} if g.get("title") else None,
            "ig": {k: str(ig.get(k, "")) for k in ("title", "hook", "caption")} if ig.get("title") else None}

def make_daily(old_daily, items):
    hist = (old_daily or {}).get("history", [])[:40]
    today = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3, minutes=30)))
    heads = [i["title"] for i in items[:8]]
    prompt = (f"Today is {today.strftime('%Y-%m-%d')} (Tehran). Create FRESH, creative daily inspiration for the teacher. "
              f"Do NOT repeat any of these previous ideas: {json.dumps(hist, ensure_ascii=False)}. "
              f"Recent world news headlines in early-childhood education (use one as inspiration if relevant): {json.dumps(heads, ensure_ascii=False)}. "
              'JSON: {"tip":"one practical evidence-based tip for the teacher (2-3 sentences)",'
              '"lessons":[{"title":"","age":"","idea":"3-4 sentence original play-based English activity with materials","say":["English phrases"]}],'
              '"game":{"title":"new therapeutic play game","how":"3-4 sentences, with safety note"},'
              '"ig":{"title":"","hook":"","caption":"Persian Instagram caption for parents with emojis and CTA"}}. Give exactly 3 lessons for different ages.')
    try:
        d = validate_daily(llm(prompt))
    except Exception as e:
        print("daily failed:", e); d = None
    if not d:
        return old_daily
    new_hist = [(d.get("ig") or {}).get("hook", "")] + [l.get("title", "") for l in d["lessons"]] + [(d.get("game") or {}).get("title", "")]
    return {"date": today.strftime("%Y-%m-%d"), "updated_fa": today.strftime("%Y-%m-%d ساعت %H:%M"), "items": d, "history": [h for h in new_hist if h] + hist}

def main():
    try:
        prev = json.load(open("news.json", encoding="utf-8"))
    except Exception:
        prev = {}
    old = prev.get("items", [])
    fresh = []
    sources = [(t, gnews(q)) for t, q in TOPICS] + EXTRA_FEEDS
    for topic, url in sources:
        try:
            fresh += parse(fetch(url), topic)[:PER_TOPIC]
        except Exception as e:
            print("feed failed:", topic, e)
    for it in old:
        if not it.get("ts"):
            try: it["ts"] = datetime.datetime.strptime(it.get("date", ""), "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc).timestamp()
            except Exception: it["ts"] = 0
    seen, merged = set(), []
    for it in sorted(old + fresh, key=lambda x: (x.get("ts", 0), bool(x.get("fa_title"))), reverse=True):
        k = re.sub(r"\W+", "", it["title"].lower())[:80]
        if k in seen:
            continue
        seen.add(k)
        merged.append(it)
    cutoff = datetime.datetime.now(datetime.timezone.utc).timestamp() - KEEP_DAYS * 86400
    merged = [i for i in merged if i.get("ts", 0) >= cutoff][:MAX_ITEMS]
    try:
        translate(merged)
    except Exception as e:
        print("translate failed:", e)
    import time; time.sleep(16)
    daily = make_daily(prev.get("daily"), merged)
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3, minutes=30)))
    with open("news.json.tmp", "w", encoding="utf-8") as f:
        json.dump({"updated": now.strftime("%Y-%m-%d %H:%M"), "updated_fa": now.strftime("%Y-%m-%d ساعت %H:%M (تهران)"),
                   "items": merged, "daily": daily}, f, ensure_ascii=False, indent=1)
    os.replace("news.json.tmp", "news.json")
    print("items:", len(merged))

if __name__ == "__main__":
    main()
