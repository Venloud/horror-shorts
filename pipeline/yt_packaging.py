"""Packaging for YouTube Shorts + TikTok: title, description, hashtags, search tags (flag `packaging`).

One small LLM call (story._json_call: Gemini chain -> Groq) proposes a curiosity title, a hook sentence, the subject,
the place, 1-2 topic hashtags, 2 niche hashtags (from a whitelist) and 10-15 search phrases. Everything is then
validated in code; anything that fails is replaced by a deterministic fallback, so packaging never stops a post.

  YouTube title   : "<hook phrase>... <Subject> of <Place> #shorts"  (<= 70 chars, max 1 emoji, no ALL CAPS)
  YouTube desc.   : line 1 hook sentence (different words from the title)
                    line 2 "TRUE STORY" / "Fictional story." label (only when the story has one)
                    credits (music / visuals), then: #topic #place #niche1 #niche2 #shorts
  YouTube tags    : 10-15 search phrases, < 400 chars (snippet.tags)
  TikTok caption  : hook sentence (+ label) + credits + 3-5 hashtags (no #shorts, never #fyp/#viral)
Hashtags across title + description <= 8.
"""
import json
import re
from difflib import SequenceMatcher

from common import CONFIG, env, log

# Niche hashtags the model may pick from (by story kind). Topic/place tags are free but must come from the story.
NICHE = {
    "lore": ["folklore", "legends", "mythology", "urbanlegend", "scarystories", "cryptid", "ghoststory",
             "supernatural", "creepy", "monsters"],
    "true": ["truecrime", "unsolvedmysteries", "mystery", "coldcase", "crimestory", "history", "darkhistory",
             "unsolved", "strangehistory", "heist"],
    "fiction": ["scarystories", "horrorstory", "creepypasta", "shortstory", "thriller", "scary", "creepy",
                "horrorstories"],
}
NICHE_DEFAULT = {"lore": ["folklore", "scarystories"], "true": ["truecrime", "unsolvedmysteries"],
                 "fiction": ["scarystories", "horrorstory"]}
BANNED = {"fyp", "foryou", "foryoupage", "fy", "viral", "trending", "xyzbca", "tiktok", "explore", "blowthisup",
          "goviral", "shorts", "youtube", "youtubeshorts", "follow", "like", "subscribe", "fypage", "capcut",
          "nsfw", "gore", "18plus"}
# Other creators / channels / brands: never borrow their names as tags.
CREATORS = {"mrballen", "mrnightmare", "nexpo", "lazymasquerade", "barbarafromthepost", "scarystoriesdaily",
            "buzzfeedunsolved", "unsolvedmysteriesnetflix", "netflix", "lemmino", "cryptiq", "nightdocs",
            "corpsehusband", "chillsdaily", "chills", "slapped", "theparanormalfiles", "bedtimestories"}
CLICKBAIT = re.compile(r"\b(you won'?t believe|shocking|gone wrong|100%|must watch|insane|not clickbait|"
                       r"\(real\)|\(gone|omg|watch till the end|wait for it)\b", re.IGNORECASE)
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿\U0001F000-\U0001F2FF]")
ACRONYMS = {"FBI", "CIA", "DNA", "UFO", "USA", "UK", "US", "NASA", "KGB", "NYC", "LA", "DB", "D.B.", "II", "III",
            "WWII", "WW2", "LAPD", "NYPD", "TV"}

PROMPT = """You package a short illustrated horror video (YouTube Shorts + TikTok) for search and curiosity.
Use ONLY what the story below says. Never promise anything the video doesn't deliver, never invent facts.

STORY KIND: {kind}{label_note}
TITLE: {title}
HOOK (first sentence): {hook}
PREMISE: {premise}
SETTING: {setting}
NARRATION (excerpt): {narration}

Return JSON:
- "title_hook": a short curiosity phrase taken from the hook (3-7 words), e.g. "It Carries Its Own Coffin",
  "The Password Was 'Louvre'". Title Case, no ALL CAPS words, no emoji, no clickbait words.
- "subject": the name people search for (the legend, case, person or creature), e.g. "The Lagahoo", "D.B. Cooper".
  For an invented story: a short descriptive subject (e.g. "The Platform Four Rule").
- "place": the real place / country of origin if the story names one, written the way it reads after "of"
  (e.g. "Trinidad", "the Philippines"), else "".
- "category": 1-3 words for search, e.g. "Trinidad Folklore", "True Heist", "Unsolved Mystery", "Scary Story".
- "hook_sentence": ONE sentence for the description, different wording from title_hook, max 140 characters.
- "topic_tags": 1-2 hashtags (lowercase, letters/digits only, no #) for the subject, e.g. ["lagahoo"], ["dbcooper"].
  Only names that appear in the story. Never another creator's or channel's name.
- "place_tag": one lowercase hashtag for the place/origin (e.g. "trinidad") or "".
- "niche_tags": exactly 2 from this list (best fit first): {niche}
- "search_tags": 12 search phrases people would type (lowercase, 1-4 words each): the subject, alternative
  spellings, "<place> folklore" / "<subject> legend" / "true crime story" / "scary legend" style phrases."""


def _kind(story: dict) -> str:
    """true (real case) / lore (legend) / fiction (anything else, incl. the owner's SCRIPT stories)."""
    if story.get("true_story") or story.get("mode") in ("case", "mystery", "inbox-true"):
        return "true"
    return "lore" if story.get("mode") == "lore" else "fiction"


def _shouty(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return bool(CLICKBAIT.search(text)) or (len(letters) > 8 and sum(c.isupper() for c in letters) / len(letters) > 0.6)


def _misleading(text: str, story: dict, kind: str) -> bool:
    import notify
    t = text.lower()
    if kind != "true" and re.search(r"\btrue (story|crime)\b|\breal (story|case)\b", t):
        return True
    return "unsolved" in t and story.get("true_story") and notify.is_resolved(story)


def _default_category(story: dict, kind: str, place: str) -> str:
    import notify
    if kind == "lore":
        return f"{place} Folklore" if place else "Folklore"
    if kind == "true":
        return "True Story" if notify.is_resolved(story) or story.get("mode") == "case" else "Unsolved Mystery"
    return "Scary Story"


def _label(story: dict) -> str:
    import notify
    if story.get("true_story"):
        return "TRUE STORY"
    if notify.is_fiction(story):
        return "Fictional story."
    return ""


def _story_text(story: dict) -> str:
    parts = [story.get("title", ""), story.get("premise", ""), story.get("setting", ""), story.get("case") or "",
             story.get("caption", "")] + [sc.get("narration", "") for sc in story.get("scenes") or []]
    parts += [str(x) for x in story.get("fact_ledger") or []]
    return " ".join(p for p in parts if p)


def _squash(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


def hook_of(story: dict) -> str:
    scenes = story.get("scenes") or []
    text = scenes[0].get("narration", "") if scenes else (story.get("caption") or "").split("\n")[0]
    first = re.split(r"(?<=[.!?])\s+", text.strip())[0] if text else ""
    return first.strip()


def clean_tag(t: str) -> str:
    return _squash(str(t).lstrip("#"))


def valid_tag(t: str, story: dict, kind: str, topic: bool = False) -> str | None:
    """A cleaned tag or None: lowercase letters/digits, 3-30 chars, not spam/banned/creator, not misleading."""
    import notify
    t = clean_tag(t)
    if not 3 <= len(t) <= (20 if topic else 30) or t in BANNED or t in CREATORS or any(c in t for c in CREATORS if len(c) > 5):
        return None
    true_only = ("truecrime", "truestory", "crimestory", "coldcase", "unsolvedmysteries", "unsolved")
    if kind != "true" and t in true_only:
        return None
    if kind == "true" and t in ("fiction", "creepypasta", "shortstory"):
        return None
    if "unsolved" in t and story.get("true_story") and notify.is_resolved(story):
        return None
    if topic and t[:max(5, len(t) - 3)] not in _squash(_story_text(story)):  # topic/place tag: from the story
        return None
    return t


def _fix_caps(s: str) -> str:
    words = s.split()
    out = []
    for w in words:
        core = re.sub(r"[^A-Za-z.]", "", w)
        if len(core) > 3 and core.isupper() and core not in ACRONYMS:
            w = w.capitalize()
        out.append(w)
    return " ".join(out)


def _limit_emoji(s: str, n: int = 1) -> str:
    seen = 0

    def keep(m):
        nonlocal seen
        seen += 1
        return m.group(0) if seen <= n else ""
    return re.sub(r"\s{2,}", " ", EMOJI.sub(keep, s)).strip()


def make_title(hook: str, subject: str, place: str, category: str, story: dict, limit: int = 70) -> str:
    suffix = " #shorts"
    room = limit - len(suffix)
    hook = _limit_emoji(_fix_caps(CLICKBAIT.sub("", hook or "").strip(" .,:;-|")), 0)
    subject = _fix_caps((subject or "").strip(" .,:;-|"))
    place = (place or "").strip()
    if place and _squash(re.sub(r"^the\s+", "", place, flags=re.IGNORECASE)) in _squash(subject):
        place = ""
    tail = f"{subject} of {place}" if subject and place else subject
    cands = []
    if hook and tail:
        cands.append(f"{hook}... {tail}")
    if hook and subject and tail != subject:
        cands.append(f"{hook}... {subject}")
    if hook and subject and category:
        cands.append(f"{hook} | {category}")
    if tail and category and _squash(category) not in _squash(tail):
        cands.append(f"{tail} | {category}")
    cands += [tail, story.get("title", "")]
    for c in cands:
        c = re.sub(r"\s{2,}", " ", c).strip()
        if c and len(c) <= room and not c.isupper():
            return c + suffix
    t = story.get("title", "Night Files")
    return (t[:room].rsplit(" ", 1)[0] if len(t) > room else t) + suffix


def _phrase(s: str) -> str:
    s = re.sub(r"[<>#\"]", "", str(s)).strip().lower()
    return re.sub(r"\s{2,}", " ", s)


def search_tags(raw: list, subject: str, place: str, kind: str) -> list[str]:
    defaults = {"lore": ["scary legend", "folklore", "creepy legend", "folklore creatures", "legends explained",
                         "monster legend", "horror story", "scary stories", "illustrated horror", "dark folklore",
                         "urban legend", "myths and legends"],
                "true": ["true crime story", "unsolved mystery", "true story", "mystery explained", "true crime",
                         "strange history", "dark history", "real story", "illustrated horror", "unexplained",
                         "crime documentary short", "history mystery"],
                "fiction": ["scary story", "horror story", "creepy story", "short horror story", "scary stories",
                            "horror short", "creepy stories", "fictional horror", "illustrated horror",
                            "bedtime horror", "thriller story", "suspense story"]}
    subj = _phrase(re.sub(r"^the\s+", "", subject or "", flags=re.IGNORECASE))
    extra = [subj, f"{subj} legend" if kind == "lore" else f"{subj} story"] if subj else []
    if place:
        extra.append(f"{_phrase(place)} folklore" if kind == "lore" else f"{_phrase(place)} mystery")
    out, total = [], 0
    for p in [_phrase(x) for x in list(raw or []) + extra + defaults[kind]]:
        if not p or len(p) > 30 or len(p.split()) > 5 or p in out or clean_tag(p) in BANNED | CREATORS:
            continue
        cost = len(p) + (2 if " " in p else 0) + 1  # YouTube counts quotes around multi-word tags + a comma
        if total + cost > 390:
            break
        out.append(p)
        total += cost
        if len(out) >= 15:
            break
    return out


def package(story: dict, use_llm: bool = True) -> dict:
    """Packaging for this story (also stored in it): yt_title, yt_description_core, yt_tags, hashtags,
    tiktok_caption_core, hook_sentence. Credits are added by caption_text / youtube.upload."""
    kind = _kind(story)
    hook = hook_of(story)
    label = _label(story)
    ans = {}
    if use_llm and CONFIG.get("packaging", True):
        try:
            from story import _json_call
            prompt = PROMPT.format(
                kind={"true": "true story (real case)", "lore": "legend / folklore (told as a legend)",
                      "fiction": "invented fictional story"}[kind],
                label_note=" - the video says it is fictional" if label.startswith("Fictional") else "",
                title=story.get("title", ""), hook=hook, premise=story.get("premise", ""),
                setting=story.get("setting", ""),
                narration=" ".join(sc.get("narration", "") for sc in story.get("scenes") or [])[:1500],
                niche=", ".join(NICHE[kind]))
            ans = _json_call(prompt, env("GEMINI_API_KEY", required=False), temperature=0.4) or {}
        except Exception as e:  # noqa: BLE001 (packaging never stops a post)
            log(f"Packaging: LLM call failed ({str(e)[:150]}); deterministic packaging")
            ans = {}

    subject = str(ans.get("subject") or story.get("case") or story.get("title") or "").strip()
    place = str(ans.get("place") or "").strip()
    sq = _squash(re.sub(r"^the\s+", "", place, flags=re.IGNORECASE))
    if place and sq[:max(5, len(sq) - 3)] not in _squash(_story_text(story)):
        place = ""  # never a place the story doesn't name ("Philippine folklore" still counts for "Philippines")
    category = _fix_caps(str(ans.get("category") or "").strip())[:28]
    if _misleading(category, story, kind):
        category = ""
    category = category or _default_category(story, kind, place)
    raw_hook = str(ans.get("title_hook") or "")
    if _shouty(raw_hook):  # clickbait / ALL CAPS: drop the hook rather than half-clean it
        raw_hook = ""
    title = make_title(raw_hook, subject, place, category, story)
    if CLICKBAIT.search(title) or (kind != "true" and re.search(r"\btrue\b", title, re.IGNORECASE)):
        title = make_title("", subject, place, "", story)

    sentence = str(ans.get("hook_sentence") or "").strip()
    sentence = "" if _shouty(sentence) or _misleading(sentence, story, kind) else _limit_emoji(sentence, 1)
    sentence = sentence or hook
    if len(sentence) > 160 or SequenceMatcher(None, _squash(sentence), _squash(title)).ratio() > 0.7:
        sentence = hook if SequenceMatcher(None, _squash(hook), _squash(title)).ratio() <= 0.7 else \
            (story.get("premise") or hook)
    sentence = sentence[:160].strip()

    topic = [t for t in (valid_tag(x, story, kind, topic=True) for x in (ans.get("topic_tags") or [])[:2]) if t]
    if not topic:  # fallback: the subject's name, if it's in the story
        t = valid_tag(re.sub(r"^the\s+", "", subject, flags=re.IGNORECASE), story, kind, topic=True)
        topic = [t] if t else []
    place_tag = valid_tag(ans.get("place_tag") or re.sub(r"^the\s+", "", place, flags=re.IGNORECASE),
                          story, kind, topic=True) if (ans.get("place_tag") or place) else None
    niche = [t for t in (valid_tag(x, story, kind) for x in ans.get("niche_tags") or []) if t and t in NICHE[kind]]
    for d in NICHE_DEFAULT[kind]:
        if len(niche) >= 2:
            break
        if d not in niche and valid_tag(d, story, kind):
            niche.append(d)
    tags = []
    for t in topic[:1] + ([place_tag] if place_tag else []) + niche[:2] + topic[1:]:
        if t and t not in tags:
            tags.append(t)
    for extra in NICHE_DEFAULT[kind] + NICHE[kind]:  # at least 3 (TikTok wants 3-5): pad with niche tags
        if len(tags) >= 3:
            break
        if extra not in tags and valid_tag(extra, story, kind):
            tags.append(extra)
    tags = tags[:4]  # + #shorts = 4-5 in the description; with the title's #shorts <= 8 in total

    yt_tags = search_tags(ans.get("search_tags") or [], subject, re.sub(r"^the\s+", "", place, flags=re.I), kind)
    if story.get("true_story"):
        import notify
        if notify.is_resolved(story):
            yt_tags = [t for t in yt_tags if "unsolved" not in t]
    tiktok_tags = tags[:5]
    pack = {
        "yt_title": title,
        "hook_sentence": sentence,
        "label": label,
        "hashtags": tags,
        "yt_hashtag_line": " ".join("#" + t for t in tags + ["shorts"]),
        "tiktok_hashtag_line": " ".join("#" + t for t in tiktok_tags),
        "yt_tags": yt_tags,
        "packaging_source": "llm" if ans else "fallback",
    }
    story["packaging"] = pack
    story["hashtags"] = tags
    log(f"Packaging ({pack['packaging_source']}): title {title!r}; tags {pack['yt_hashtag_line']}; "
        f"search tags {len(yt_tags)}")
    return pack


def _credits(story: dict) -> str:
    credit = CONFIG.get("music_credits", {}).get(story.get("music_file") or "", "")
    lines = [credit] if credit else []
    if story.get("media_assets"):
        try:
            from media import credits
            lines.append(credits(story["media_assets"])[0])
        except Exception as e:  # noqa: BLE001
            log(f"Visual credit line skipped ({e})")
    return "\n".join(lines)


def tiktok_caption(story: dict) -> str:
    p = story.get("packaging") or package(story)
    first = p["hook_sentence"]
    if p["label"] == "TRUE STORY":
        first = f"TRUE STORY: {first}"
    elif p["label"]:
        first = f"{first} (fictional story)"
    credit = _credits(story)
    return "\n".join([first] + ([credit] if credit else []) + ["", p["tiktok_hashtag_line"]]).strip()


def youtube_description(story: dict) -> str:
    """Line 1 hook, line 2 label, credits, hashtag line (#shorts last). Visual credits are appended by
    youtube.upload(credits=...)."""
    p = story.get("packaging") or package(story)
    lines = [p["hook_sentence"]]
    if p["label"]:
        lines.append(p["label"])
    credit = CONFIG.get("music_credits", {}).get(story.get("music_file") or "", "")
    if credit:
        lines.append(credit)
    lines.append(p["yt_hashtag_line"])
    return "\n".join(lines)


def count_hashtags(*texts: str) -> int:
    return len({m.lower() for t in texts for m in re.findall(r"#(\w+)", t)})


if __name__ == "__main__":  # quick look: python yt_packaging.py story.json
    import sys
    s = json.load(open(sys.argv[1], encoding="utf-8"))
    pk = package(s, use_llm=len(sys.argv) < 3)
    print(json.dumps(pk, indent=2, ensure_ascii=False))
    print("---- TikTok\n" + tiktok_caption(s) + "\n---- YouTube\n" + youtube_description(s))
