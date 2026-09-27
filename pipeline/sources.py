"""Real-story sources: FBI case files, plus the creator's own inbox of links and pasted stories.

inbox/links.txt  one link per line.  "true <url>"    -> retell the real story, facts only
                                     "fiction <url>" -> use it as inspiration for an ORIGINAL story
                                     a bare url      -> treated as "true"
inbox/*.txt      any other text file = a pasted story/article. First line "TRUE", "FICTION", "SCRIPT" or "SCRIPT TRUE"
                 (default FICTION = inspiration only; SCRIPT = narrate these exact words, only add the visuals;
                 SCRIPT TRUE = same, but it's a real story: "This is a true story." opener, TRUE STORY badge,
                 and real people are never shown with faces).
Each item is used once (tracked in data/history.json). Inbox items jump the queue.
"""
import json
import random
import re

import requests

from common import ROOT, log

INBOX = ROOT / "inbox"
CASES_FILE = ROOT / "data" / "cases.json"
UA = {"User-Agent": "Mozilla/5.0 (compatible; NightFilesBot/1.0; +https://venloud.github.io/nightfiles/)"}
WIKI_API = "https://en.wikipedia.org/w/api.php"


# ---------- fetching text ----------


def _split_wiki(text: str, limit: int) -> str:
    """Main article text plus a short 'In popular culture' section (used for pop-culture references)."""
    pop = ""
    m = re.search(r"\n==\s*(In popular culture|Popular culture|In fiction|Legacy|Cultural impact|In media)\s*==\n(.*?)(\n==[^=]|$)", text, re.S)
    if m:
        pop = m.group(2).strip()[:1500]
    main = re.split(r"\n==\s*(See also|References|Notes|Further reading|External links|In popular culture|Popular culture|In fiction|In media)\s*==", text)[0]
    main = main[: limit - len(pop) - 40]
    return main + (f"\n\nIN POPULAR CULTURE:\n{pop}" if pop else "")

def page_text(url: str, limit: int = 9000) -> str:
    """Readable text of a web page (article paragraphs only)."""
    if "reddit.com" in url:
        return _reddit_text(url, limit)
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form", "noscript", "iframe"]):
        tag.decompose()
    root = soup.find("article") or soup.find(id="content-core") or soup.find("main") or soup.body or soup
    parts = [el.get_text(" ", strip=True) for el in root.find_all(["h1", "h2", "h3", "p", "li"])]
    text = "\n".join(p for p in parts if len(p) > 40)
    if len(text) < 600:
        raise RuntimeError(f"not enough readable text at {url} ({len(text)} chars)")
    return text[:limit]


def _reddit_text(url: str, limit: int) -> str:
    r = requests.get(url.split("?")[0].rstrip("/") + ".json", headers=UA, timeout=30)
    r.raise_for_status()
    post = r.json()[0]["data"]["children"][0]["data"]
    text = f"{post.get('title', '')}\n\n{post.get('selftext', '')}".strip()
    if len(text) < 300:
        raise RuntimeError("Reddit post has no story text")
    return text[:limit]


def wiki_text(query: str, limit: int = 9000) -> str:
    """Wikipedia article text, finding the best-matching article for the query."""
    s = requests.get(WIKI_API, headers=UA, timeout=30, params={
        "action": "query", "format": "json", "list": "search", "srsearch": query, "srlimit": 1})
    s.raise_for_status()
    hits = s.json()["query"]["search"]
    if not hits:
        raise RuntimeError(f"no Wikipedia article for {query}")
    r = requests.get(WIKI_API, headers=UA, timeout=30, params={
        "action": "query", "format": "json", "prop": "extracts", "explaintext": 1,
        "redirects": 1, "titles": hits[0]["title"]})
    r.raise_for_status()
    text = next(iter(r.json()["query"]["pages"].values())).get("extract", "")
    if len(text) < 800:
        raise RuntimeError(f"Wikipedia article for {query} too short")
    return _split_wiki(text, limit)


# ---------- FBI case files ----------

def next_case(history: list[dict]) -> dict:
    used = {h.get("case") for h in history if h.get("case")}
    fresh = [c for c in json.loads(CASES_FILE.read_text()) if c["title"] not in used]
    if not fresh:
        raise RuntimeError("All FBI cases have been used. Add more to data/cases.json.")
    return random.choice(fresh)


def case_facts(case: dict) -> str:
    try:
        text = page_text(case["url"])
        log(f"Case source: FBI page ({len(text)} chars)")
        return text
    except Exception as e:  # noqa: BLE001
        log(f"FBI page failed ({str(e)[:120]}), using Wikipedia")
        return wiki_text(case.get("wiki") or case["title"])


# ---------- the creator's inbox ----------

def next_inbox(history: list[dict]) -> dict | None:
    """The oldest unused inbox item, or None. Returns {key, kind, text?, url?}."""
    if not INBOX.exists():
        return None
    used = {h.get("source") for h in history if h.get("source")}
    links = INBOX / "links.txt"
    if links.exists():
        for line in links.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            kind, _, url = line.partition(" ") if line.split()[0].lower() in ("true", "fiction") else ("true", "", line)
            url = url.strip()
            if url.startswith("http") and url not in used:
                return {"key": url, "kind": kind.lower(), "url": url}
    for f in sorted(INBOX.glob("*.txt")):
        if f.name == "links.txt" or f"inbox/{f.name}" in used:
            continue
        lines = f.read_text(encoding="utf-8").strip().splitlines()
        if not lines:
            continue
        kind, true = "fiction", False
        first = " ".join(lines[0].upper().split())
        if first in ("SCRIPT TRUE", "TRUE SCRIPT"):
            kind, true = "script", True
            lines.pop(0)
        elif first in ("TRUE", "FICTION", "SCRIPT"):
            kind = lines.pop(0).strip().lower()
        text = "\n".join(lines).strip()
        if len(text) > 200:
            return {"key": f"inbox/{f.name}", "kind": kind, "true": true, "text": text[:9000]}
    return None


def inbox_text(item: dict) -> str:
    return item.get("text") or page_text(item["url"])
