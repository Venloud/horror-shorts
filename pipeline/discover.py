"""More real-story sources, DISCOVERY ONLY: find new topics; every story still needs a readable source page, which
becomes the fact ledger's only source (the model may not add anything that isn't in it).

  ntsb         data/aviation.json: curated strange NTSB-investigated aviation incidents (readable Wikipedia page
               as the source). Mixed into the `case` pool.
  newspapers   Library of Congress, Chronicling America (via the loc.gov API; the old API was retired in 2025):
               pages from before 1929 (config newspaper_queries). The source = the page's OCR text around the
               match (ALTO XML), used only if it reads cleanly. Serialized fiction and missing-person stories are
               skipped. `mystery` mode (true story).
  loc_folklore Library of Congress Folklife Today blog, "legends" posts (readable HTML). `lore` mode.
  duchas       Ireland's National Folklore Collection (duchas.ie API v0.6, only with DUCHAS_API_KEY). `lore` mode.
Flags: discovery (all), discovery_sources {ntsb, newspapers, loc_folklore, duchas}; discovery_share (0.25) = how
often a lore / mystery pick tries a discovery lead first. Any error = no lead, the normal lists are used.
"""
import html
import json
import random
import re
from urllib.parse import parse_qs, urlparse

import requests

from common import CONFIG, ROOT, env, log

UA = {"User-Agent": "NightFilesBot/1.0 (https://github.com/Venloud/horror-shorts; automated short-video builder)"}
AVIATION_FILE = ROOT / "data" / "aviation.json"
SKIP_WORDS = re.compile(r"\b(missing|disappear\w*|kidnap\w*|abduct\w*|runaway|copyright|chapter [ivx\d]+|"
                        r"continued from|to be continued)\b", re.IGNORECASE)


def enabled(name: str | None = None) -> bool:
    if not CONFIG.get("discovery", True):
        return False
    return name is None or bool((CONFIG.get("discovery_sources") or {}).get(name, True))


def _used(history: list[dict]) -> set[str]:
    return {str(h.get(k)) for h in history for k in ("case", "source") if h.get(k)}


# ---------- NTSB aviation cases (mixed into the `case` pool) ----------

def aviation_cases() -> list[dict]:
    if not enabled("ntsb") or not AVIATION_FILE.exists():
        return []
    return json.loads(AVIATION_FILE.read_text())


# ---------- Chronicling America (before 1929) ----------

def _alto_text(word_coords_url: str) -> str:
    """Full OCR words of a newspaper page from its ALTO XML (tile.loc.gov storage path of the page)."""
    seg = parse_qs(urlparse(word_coords_url).query).get("segment", [""])[0]
    if not seg.endswith(".xml"):
        raise RuntimeError("no ALTO segment")
    r = requests.get("https://tile.loc.gov/storage-services" + seg, headers=UA, timeout=40)
    r.raise_for_status()
    words = re.findall(r'CONTENT="([^"]+)"', r.text)
    return html.unescape(" ".join(words))


def _window(text: str, term: str, words: int = 380) -> str:
    """The article around the first match (OCR pages hold many articles)."""
    tokens = text.split()
    idx = next((i for i, t in enumerate(tokens) if term.lower() in t.lower()), None)
    if idx is None:
        return ""
    return " ".join(tokens[max(0, idx - words // 3): idx + words])


def readable(text: str) -> bool:
    """OCR quality gate: enough real words, not mostly noise."""
    toks = text.split()
    if len(toks) < 150:
        return False
    good = sum(1 for t in toks if re.fullmatch(r"[A-Za-z][a-z']{2,}[,.;:!?]?", t))
    return good / len(toks) >= 0.6


def newspaper_lead(history: list[dict]) -> dict | None:
    if not enabled("newspapers"):
        return None
    used = _used(history)
    queries = list(CONFIG.get("newspaper_queries") or ["sea serpent", "ghost seen", "haunted house",
                                                      "strange light in the sky", "mysterious noises", "wild man"])
    random.shuffle(queries)
    for q in queries[:3]:
        r = requests.get("https://www.loc.gov/collections/chronicling-america/", headers=UA, timeout=40, params={
            "q": q, "dates": "1850/1928", "fo": "json", "c": 12, "at": "results"})
        r.raise_for_status()
        for res in r.json().get("results") or []:
            url = res.get("url", "").split("&q=")[0]
            if url in used or not res.get("word_coordinates_url"):
                continue
            try:
                text = _window(_alto_text(res["word_coordinates_url"]), q.split()[-1])
            except Exception as e:  # noqa: BLE001
                log(f"Newspaper page unreadable ({str(e)[:80]})")
                continue
            if not readable(text) or SKIP_WORDS.search(text):
                continue
            title = f"{res.get('title', 'Old newspaper').split(' of ', 1)[-1]} ({q})"
            log(f"Discovery lead (Chronicling America, {res.get('date')}): {title}")
            return {"title": title, "key": url, "url": url, "source": "Chronicling America (Library of Congress)",
                    "date": res.get("date"), "text": f"NEWSPAPER PAGE, {res.get('date')} (OCR text, may contain "
                                                     f"errors; use only what is clearly readable). This is a "
                                                     f"newspaper REPORT: tell it as what the paper reported "
                                                     f"(\"a newspaper reported that...\"), never as proven fact:"
                                                     f"\n{text}"}
    return None


# ---------- Library of Congress folklore ----------

def loc_folklore_lead(history: list[dict]) -> dict | None:
    if not enabled("loc_folklore"):
        return None
    from sources import page_text
    used = _used(history)
    r = requests.get("https://blogs.loc.gov/folklife/category/legends/", headers=UA, timeout=40)
    r.raise_for_status()
    posts = re.findall(r'href="(https://blogs\.loc\.gov/folklife/20\d\d/\d\d/[a-z0-9\-]+/)"[^>]*>([^<]{8,140})<',
                       r.text)
    posts = [(u, t.strip()) for u, t in dict(posts).items() if u not in used and t.strip()]
    random.shuffle(posts)
    for url, title in posts[:4]:
        try:
            text = page_text(url)
        except Exception as e:  # noqa: BLE001
            log(f"Folklife post unreadable ({str(e)[:80]})")
            continue
        if len(text) >= 1200:
            log(f"Discovery lead (LOC Folklife): {title}")
            return {"title": title, "key": url, "url": url, "source": "Library of Congress, Folklife Today",
                    "text": text}
    return None


# ---------- Dúchas (National Folklore Collection, Ireland) ----------

def duchas_lead(history: list[dict]) -> dict | None:
    key = env("DUCHAS_API_KEY", required=False)
    if not key or not enabled("duchas"):
        return None
    from sources import page_text
    used = _used(history)
    topic = random.choice(CONFIG.get("duchas_topic_ids") or [0]) if CONFIG.get("duchas_topic_ids") else None
    if topic is None:
        log("Dúchas: set config duchas_topic_ids (e.g. the topic ids for ghosts / fairies) to use it")
        return None
    r = requests.get("https://www.duchas.ie/api/v0.6/cbes", headers=UA, timeout=40,
                     params={"apiKey": key, "TopicID": topic, "Language": "en"})
    r.raise_for_status()
    items = []

    def walk(o):  # the response nests volumes -> pages -> items; collect anything with an item URL
        if isinstance(o, dict):
            u = o.get("URL") or o.get("Url") or o.get("url")
            if isinstance(u, str) and "/cbes/" in u:
                items.append((u, o.get("Title") or o.get("title") or "Irish folklore story"))
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(r.json())
    random.shuffle(items)
    for url, title in items[:4]:
        if url in used:
            continue
        try:
            text = page_text(url)
        except Exception:  # noqa: BLE001
            continue
        if len(text) >= 600:
            log(f"Discovery lead (Dúchas): {title}")
            return {"title": str(title), "key": url, "url": url, "source": "Dúchas, National Folklore Collection",
                    "text": text}
    return None


def lead(kind: str, history: list[dict]) -> dict | None:
    """A discovery lead for `mystery` (old newspapers) or `lore` (LOC folklore, Dúchas), or None."""
    if not enabled() or random.random() >= float(CONFIG.get("discovery_share", 0.25)):
        return None
    finders = [newspaper_lead] if kind == "mystery" else [loc_folklore_lead, duchas_lead] if kind == "lore" else []
    random.shuffle(finders)
    for find in finders:
        try:
            found = find(history)
            if found:
                return found
        except Exception as e:  # noqa: BLE001
            log(f"Discovery {find.__name__} skipped ({str(e)[:120]})")
    return None
