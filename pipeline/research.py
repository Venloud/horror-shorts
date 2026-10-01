"""Research before writing (flag `research`): Gemini with Google Search grounding finds 3-6 sources beyond
Wikipedia, and only the lines Google's grounding metadata actually backs are kept. Wikipedia stays the base source;
this block is appended to it, so it ends up in the fact ledger (and in the fact check for true stories).

Free tier: grounding is free ONLY on gemini-2.5-flash / gemini-2.5-flash-lite (500 requests per day, shared;
the 3.x writer models have no free grounding), so `research_models` lists those. Daily usage is counted in
cache/media-search/research_usage.json (saved between builds by build.yml's media-search cache) and capped at
`research_daily_limit`; a per-day 429 marks it used up for the day. Any problem = Wikipedia only, never a failure.
"""
import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

from common import CONFIG, ROOT, env, log

URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
USAGE = ROOT / "cache" / "media-search" / "research_usage.json"
STATE = {"out": False}

PROMPT = """Research this topic with Google Search for a short, strictly factual narrated video: {topic}
Kind: {kind}. {notes}
Find 3 to 6 reliable sources OTHER than Wikipedia (news outlets, museums, universities, books, official records,
folklore archives, encyclopedias). Then write up to 25 short lines, one fact per line:
FACT: <one fact the sources state, with names, numbers and dates exactly as written there>
RUMOR: <a claim the sources report as rumor, legend, theory or unconfirmed (say who claims it)>
Rules: only what the sources say; never guess or fill gaps; if sources disagree, write both as RUMOR lines;
no opinions; no advice. Plain lines only, no markdown."""


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _usage() -> dict:
    try:
        return json.loads(USAGE.read_text())
    except Exception:  # noqa: BLE001
        return {}


def _count(n: int = 1) -> int:
    u = _usage()
    u = {k: v for k, v in u.items() if k >= _today()[:8]}  # keep this month only
    u[_today()] = u.get(_today(), 0) + n
    try:
        USAGE.parent.mkdir(parents=True, exist_ok=True)
        USAGE.write_text(json.dumps(u))
    except OSError:
        pass
    return u[_today()]


def used_today() -> int:
    return _usage().get(_today(), 0)


def _real_url(uri: str) -> str:
    """Grounding chunks point at a vertexaisearch redirect; follow it once to get the real page URL."""
    if "grounding-api-redirect" not in uri:
        return uri
    try:
        r = requests.head(uri, allow_redirects=False, timeout=10)
        return r.headers.get("Location") or uri
    except Exception:  # noqa: BLE001
        return uri


def _domain(url: str, title: str = "") -> str:
    host = urlparse(url).netloc.lower()
    if not host or "vertexaisearch" in host:
        host = (title or "").lower()
    return host[4:] if host.startswith("www.") else host


def _grounded_lines(text: str, meta: dict) -> list[str]:
    """Only FACT/RUMOR lines that overlap a segment Google says is supported by a search result."""
    segs = [s.get("segment", {}).get("text", "") for s in meta.get("groundingSupports") or []
            if s.get("groundingChunkIndices")]
    keep = []
    for ln in text.splitlines():
        ln = ln.strip().lstrip("-* ").strip()
        if not re.match(r"(FACT|RUMOR):", ln, re.IGNORECASE):
            continue
        body = ln.split(":", 1)[1].strip()
        if len(body) < 12:
            continue
        if any(body[:60] in s or s[:60] in body or (len(s) > 20 and s in ln) for s in segs if s):
            keep.append(ln)
    return keep


def research(topic: str, kind: str = "lore", notes: str = "") -> dict | None:
    """{"text": block for the source, "sources": [{title, url, domain}], "facts": n} or None (Wikipedia only)."""
    if not CONFIG.get("research", True):
        return None
    if STATE["out"]:
        log("Research: grounding used up for today: Wikipedia only")
        return None
    limit = int(CONFIG.get("research_daily_limit", 400))
    if used_today() >= limit:
        log(f"Research: daily grounding budget used ({used_today()}/{limit}): Wikipedia only")
        STATE["out"] = True
        return None
    key = env("GEMINI_API_KEY", required=False)
    if not key:
        return None
    prompt = PROMPT.format(topic=topic, kind=kind, notes=(notes or "")[:600])
    for model in CONFIG.get("research_models", ["gemini-2.5-flash", "gemini-2.5-flash-lite"]):
        for attempt in range(2):
            try:
                r = requests.post(URL.format(model=model), timeout=120, headers={"x-goog-api-key": key}, json={
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "tools": [{"google_search": {}}], "generationConfig": {"temperature": 0.2}})
            except Exception as e:  # noqa: BLE001
                log(f"Research: {model} request failed ({str(e)[:120]})")
                break
            _count()
            if r.status_code == 429:
                if re.search(r"PerDay|per day", r.text, re.IGNORECASE):
                    log(f"Research: {model} daily grounding limit reached")
                    break  # next model (the 500/day is shared, so this usually ends it)
                time.sleep(20)
                continue
            if r.status_code in (500, 502, 503, 504):
                time.sleep(10)
                continue
            if r.status_code != 200:
                log(f"Research: {model} HTTP {r.status_code} ({r.text[:150]})")
                break
            try:
                cand = r.json()["candidates"][0]
                text = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))
                meta = cand.get("groundingMetadata") or {}
            except Exception as e:  # noqa: BLE001
                log(f"Research: unreadable answer from {model} ({str(e)[:100]})")
                break
            return _package(topic, text, meta, model)
    STATE["out"] = True
    log("Research: no grounded answer: Wikipedia only")
    return None


def _package(topic: str, text: str, meta: dict, model: str) -> dict | None:
    sources, seen = [], set()
    for ch in meta.get("groundingChunks") or []:
        web = ch.get("web") or {}
        if not web.get("uri"):
            continue
        url = _real_url(web["uri"])
        dom = _domain(url, web.get("title", ""))
        if not dom or "wikipedia.org" in dom or dom in seen:
            continue
        seen.add(dom)
        sources.append({"title": web.get("title") or dom, "url": url, "domain": dom})
    sources = sources[:6]
    lines = _grounded_lines(text, meta)
    if not sources or not lines:
        log(f"Research: {model} found nothing usable beyond Wikipedia ({len(sources)} sources, {len(lines)} lines)")
        return None
    block = ("RESEARCH (Google Search via Gemini; only lines backed by these sources; RUMOR = unconfirmed, say so "
             "if used):\n" + "\n".join(lines[:25]) + "\nSources: " + "; ".join(f"{s['domain']} {s['url']}" for s in sources))
    log(f"Research: {len(sources)} sources ({', '.join(s['domain'] for s in sources)}), {len(lines)} grounded lines "
        f"via {model} ({used_today()} grounded calls today)")
    return {"text": block, "sources": sources, "facts": len(lines), "model": model}


def add_to(facts: str, story_holder: dict, topic: str, kind: str, notes: str = "") -> str:
    """Append research to a Wikipedia source text; remembers the sources for story.json (story_holder)."""
    res = research(topic, kind, notes)
    if not res:
        return facts
    story_holder.setdefault("sources", []).extend(res["sources"])
    return facts.rstrip() + "\n\n" + res["text"]
