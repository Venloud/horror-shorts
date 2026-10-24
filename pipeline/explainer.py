"""Render style "explainer" (default for every mode): the story is told with STORY PICTURES, explained by graphics,
with the approved host as occasional B-roll (owner, Oct 24):
  story picture -> explanatory graphic -> second story picture -> (rare host reaction), a new visual every 1.5-3 s.
(a) story pictures: each scene's own image_prompt / image_query shots, through the existing media chain (asset
    library when fresh_images is OFF, licensed archive photos / prints and Pexels / Pixabay photos + clips, then AI
    images: images.generate_images, same budget / QA / fallbacks as classic). Never another scene's picture.
(b) graphics: noir.py templates (date_stamp, evidence, map_route, fact, quote, missing, closing...), LLM-picked or
    built from the narration + fact ledger; every word / number on screen is said in that scene (graphic_problem).
(c) the host: ONLY the approved M01-M04 / F01-F22 art (sprites.py): max 1 shot per scene, never in two scenes in a
    row, <= 2 s, <= 15% of the runtime, mostly F-face reactions over a blurred crop of the scene's picture.
No progress rail, no corner label, no end card: the video ends on the closing graphic / last picture.

Flow (main.py): adapt(story) -> fit_duration -> build(): story_images -> plan_graphics -> sequence -> render ->
visual_qa (hard: visual_qa.json, shot_manifest.json, provenance.json in the workdir). Music is added after.
"""
import json
import os
import re
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from common import CONFIG, ROOT, env, log

W, H, FPS = 1080, 1920, 30
FONT_DIR = ROOT / "assets" / "fonts" / "explainer"
SHOT_MIN, SHOT_MAX = 2.0, 7.0
# Dark Editorial Noir (Oct 21): INK = bone text on dark grounds, BLACK = midnight
INK, BLACK = (236, 230, 221), (16, 20, 25)
CAP_Y = 1565  # Pillow captions (only when Remotion polish is off) sit in the lower strip


class ExplainerUnavailable(RuntimeError):
    """The explainer style can't run (a scene without a picture of its own, nothing planned...)."""


def accent() -> tuple:
    h = str(CONFIG.get("explainer_accent", "#FF2D87")).lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def style_for(story: dict) -> str:
    forced = (os.environ.get("RENDER_STYLE") or "").strip().lower()
    if forced:
        return "explainer" if forced == "explainer" else forced
    if story.get("mode") in (CONFIG.get("explainer_for_modes") or []):
        return "explainer"
    return "explainer" if CONFIG.get("render_style") == "explainer" else "classic"


def forced() -> bool:
    return (os.environ.get("RENDER_STYLE") or "").strip().lower() == "explainer"


# ================================================================ writing

REWRITE_PROMPT = """You rewrite the narration of a short vertical {kind} video for the Night Files channel into the
EXPLAINER style. The video cuts every 2-3 seconds between static character-first stages, purposeful action poses,
reusable overlays and motion graphics, information cards, and title cards.

STYLE (Van's mid-conversation method)
- Point of view: third person for documented true stories; use second person only when the story genuinely calls for an immersive POV. {who}
- Open mid-conversation: the first sentence sounds like it was said halfway through a conversation with a friend,
  and its FIRST WORDS are the strangest or most shocking detail. Never a date, a year or a place name in the first 6
  words (when/where comes in scene 2). No "Welcome", no "Did you know", no "What if I told you".
- Problem by problem: every scene is one problem or step that escalates the last one (cause -> mechanism ->
  consequence). Concrete numbers and plain logic the viewer could explain back. Short spoken sentences, varied rhythm.
- No source talk ("according to", "sources say", "records show"), no lecture tone, no list of facts.
- The ending gives the viewer the floor: an open question that makes them APPLY what they just learned (a concrete
  choice, a dilemma, "what would you check first?"), never "comment below", "follow for more" or "part 2".
- {words} words in total, {scenes} scenes.
FACTS: {facts}
SAFETY: no gore, no occult symbols or rituals, adults only (never a child in danger), respectful toward real people.
Keep title, characters, locations and fact_ledger. Do not invent scenic backgrounds just to display an
action pose. Keep sfx from the same list.
Return the whole story in the SAME JSON format.

STORY:
{draft}
"""

WHO = {
    "true": 'Narrate this REAL case in natural third person. Follow the evidence step by step; never imply the viewer witnessed the case. Avoid forced phrases such as "you watch" or "you follow". Name real people clearly and preserve their actual roles.',
    "lore": "Tell the legend in natural third person, the way a storyteller tells it ('the village believed...'); "
            "use 'you' only for a direct line to the viewer, never stage directions like 'you watch'. It is folklore: "
            "supernatural claims are what people believed, never stated as fact.",
    "fiction": "Keep the story's own point of view (first, second or third person, as written); never add stage "
               "directions such as 'you watch' or 'you follow'.",
}
FACTS = {
    "true": 'This is a TRUE story. Use ONLY the facts the story already has (narration + fact_ledger): every number, '
            'name, date and place exactly as written there. Never add a new fact, quote, motive or detail. Keep the '
            'exact sentence "This is a true story." right after the hook sentence.',
    "lore": "Only the legend details already in the story; you may add sensory wording, never new lore.",
    "fiction": "Keep the plot, the clues, the twist and the ending. You may add small concrete numbers that fit the "
               "story (a clock time, a count) if they don't contradict it.",
}


def _kind(story: dict) -> str:
    if story.get("true_story"):
        return "true"
    return "lore" if story.get("mode") == "lore" else "fiction"


def adapt(story: dict) -> dict:
    """Explainer restyle of a finished story (before voicing): spoken, problem by problem, natural point of view (third
    person for true stories and legends). Never raises: a failed rewrite, or one the objective checks measure as
    worse, keeps the story as written (the render style still works on any narration)."""
    import story as st
    if story.get("explainer_adapted"):
        return story
    if story.get("mode") == "inbox-script":
        log("Explainer: owner's exact-words script, narration not rewritten")
        story["explainer_adapted"] = True
        return story
    api_key = env("GEMINI_API_KEY", required=False) or ""
    kind = _kind(story)
    verified = " ".join(sc.get("narration", "") for sc in story["scenes"]) + " " + " ".join(
        str(x) for x in story.get("fact_ledger") or [])
    draft = {k: story[k] for k in st.SCHEMA["properties"] if k in story}
    prompt = REWRITE_PROMPT.format(kind={"true": "TRUE-story", "lore": "legend", "fiction": "fiction"}[kind],
                                   who=WHO[kind], facts=FACTS[kind],
                                   words="{} to {}".format(*CONFIG.get("story_words", [138, 152])),
                                   scenes=f"{len(story['scenes'])} (6-9)",
                                   draft=json.dumps(draft, ensure_ascii=False, indent=1))
    try:
        new = st._run_models(prompt, api_key, temperature=0.6)
    except Exception as e:  # noqa: BLE001
        log(f"Explainer rewrite failed ({str(e)[:200]}); keeping the narration as written")
        story["explainer_adapted"] = True
        return story
    for k, v in story.items():
        new.setdefault(k, v)
    for k in ("characters", "locations", "fact_ledger"):
        if story.get(k) and not new.get(k):
            new[k] = story[k]
    rules = (f"EXPLAINER style: natural spoken point of view, {WHO[kind]} {FACTS[kind]} "
             "Problem by problem, concrete numbers, ends on an open question for the viewer.")
    new = st.fix_hook(new, api_key, st.sfx_names(), rules)
    if kind == "true":  # only facts the verified story already had
        new = st.fact_check(new, verified, api_key)
    st.mark_true_story(new)
    st.speak_numbers(new)
    wk = st.writing_kind(story)
    before_checks = st.writing_checks(story, wk, story.get("_fact_source"))
    after_checks = st.writing_checks(new, wk, story.get("_fact_source"))
    if st.check_score(after_checks) < st.check_score(before_checks):  # never let the restyle make it worse
        log(f"Explainer rewrite measured worse ({st.check_score(before_checks)} -> {st.check_score(after_checks)}: "
            f"{st._brief(after_checks)[:200]}); keeping the narration as written")
        story["explainer_adapted"] = True
        return story
    new["explainer_adapted"] = True
    new["explainer_before"] = [sc.get("narration", "") for sc in story["scenes"]]
    words = sum(len(s["narration"].split()) for s in new["scenes"])
    log(f"Explainer rewrite ({kind}): {len(new['scenes'])} scenes, {words} words; opens: "
        f"'{' '.join(new['scenes'][0]['narration'].split()[:14])}...'")
    return new


# ================================================================ planning

# ================================================================ graphic validation

STOP = set("a an the of in on at to and or but is was were be been it its his her their this that you your he she "
           "they them with for from by as into onto".split())
_DATE = re.compile(r"\b(1[0-9]{3}|20[0-9]{2}|january|february|march|april|may|june|july|august|september|october|"
                   r"november|december|nineteen|eighteen|seventeen|sixteen hundred|day \d+)\b", re.IGNORECASE)


def _norm_words(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9' ]+", " ", text.lower().replace("’", "'")).split()


def _plan_call(prompt: str) -> dict | None:
    import story as st
    api_key = env("GEMINI_API_KEY", required=False) or ""
    try:
        return st._json_call(prompt, api_key, temperature=0.5, light=False)
    except Exception as e:  # noqa: BLE001
        log(f"Explainer plan: LLM failed ({str(e)[:160]})")
        return None








def _number_ok(text: str, said: set) -> bool:
    """Every number on screen must be said in the narration (tiny counts <= 3 are fine)."""
    import spoken_numbers as nums
    return all(v <= 3 or v in said for v in nums.values(str(text or "")))


def _words_said(text: str, low: str) -> bool:
    """The on-screen words come from the narration (stop words aside)."""
    ws = [w for w in _norm_words(text) if w not in STOP]
    return bool(ws) and all(re.search(rf"\b{re.escape(w)}", low) for w in ws)


def _anchor(at: str, s_words: list[dict]) -> float | None:
    want = _norm_words(at)[:4]
    if not want or not s_words:
        return None
    toks = [(_norm_words(w["word"]) or [""])[0] for w in s_words]
    for k in range(len(toks)):
        n = min(len(want), len(toks) - k)
        if n and toks[k:k + n] == want[:n] and (n >= 2 or len(want) == 1):
            return s_words[k]["start"]
    return None


def _date_ok(text: str, ctx: dict) -> bool:
    """At most ONE date / year on screen in the whole video (owner, Oct 21: no year/day clutter)."""
    if not _DATE.search(text or ""):
        return True
    if ctx["dates"]:
        return False
    ctx["dates"] += 1
    return True


def _subject(name, ctx, allow_crowd=False) -> str:
    n = str(name or "").strip().lower()
    if n in ("you", "host", "the host", "narrator"):
        return "you"
    if allow_crowd and n in ("crowd", "passengers", "people", "villagers", "staff"):
        return "crowd"
    if n in ctx["cast"]:
        return n
    for k in ctx["cast"]:  # let a shortened surname match an already named person
        if n and (n in k or k.split()[-1] == n.split()[-1]):
            return k
    return ""


GRAPHIC_TEXT = {"evidence": ("text", "note"), "fact": ("label",), "filmstrip": ("text",), "quote": ("text", "by"),
                "impact": ("text",), "closing": ("text",), "photo_scan": ("text",),
                "clock_stop": ("text",), "shadow_reveal": ("text",)}


def _valid_graphic(s: dict, at, ctx: dict) -> dict | None:
    """A noir template with only the narration's own words / numbers (true stories never get invented details);
    fixed UI labels (kickers) may not carry numbers or dates."""
    import noir
    tpl = s.get("template")
    f = s.get("fields") if isinstance(s.get("fields"), dict) else {}
    if tpl not in noir.TEMPLATES or tpl in ("true_story", "title"):
        return None
    said, low = ctx["said"], ctx["low"]

    def ok(text, need=True):
        text = str(text or "").strip()
        if not text:
            return not need
        return _words_said(text, low) and _number_ok(text, said) and _date_ok(text, ctx)

    out = {"kicker": re.sub(r"[\d]", "", str(f.get("kicker") or "")).upper()[:24], "accent": str(f.get("accent") or "")}
    for k in GRAPHIC_TEXT.get(tpl, ()):
        v = re.sub(r"\s+", " ", str(f.get(k) or "")).strip()[:90]
        if k in ("text", "label") and not ok(v):
            return None
        if k in ("note", "by") and v and not ok(v):
            v = ""
        out[k] = v
    if tpl == "map_route":
        stops = [str(x)[:24] for x in f.get("stops") or [] if ok(x)][:4]
        if len(stops) < 2:
            return None
        out["stops"] = stops
    elif tpl == "connections":
        nodes = [str(x)[:30] for x in f.get("nodes") or [] if ok(x)][:4]
        if len(nodes) < 2:
            return None
        out["nodes"] = nodes
    elif tpl == "compare":
        for side in ("left", "right"):
            c = f.get(side) if isinstance(f.get(side), dict) else {}
            items = [str(x)[:40] for x in c.get("items") or [] if ok(x)][:3]
            title = str(c.get("title") or "")[:30]
            out[side] = {"title": title if ok(title) else "", "items": items}
        if not (out["left"]["items"] or out["right"]["items"]):
            return None
    elif tpl == "fact":
        try:
            v = float(f.get("value"))
        except (TypeError, ValueError):
            return None
        if not (v <= 3 or v in said) or 1000 <= v <= 2100:
            return None
        out.update(value=v, prefix=str(f.get("prefix") or "")[:2], suffix=str(f.get("suffix") or "")[:8])
    elif tpl in ("photo_scan", "clock_stop", "shadow_reveal"):
        # A named graphic is available only when the scene actually mentions the object.
        triggers = {
            "photo_scan": r"\b(photo|photograph|picture|image)\b",
            "clock_stop": r"\b(clock|midnight|timepiece)\b",
            "shadow_reveal": r"\b(shadows?|silhouettes?)\b",
        }
        if not re.search(triggers[tpl], low):
            return None
        if tpl in ("photo_scan", "shadow_reveal"):
            try:
                count = int(f.get("count") or (1 if tpl == "photo_scan" else 0))
            except (ValueError, TypeError):
                return None
            if not (1 <= count <= 4 and (tpl == "photo_scan" and count == 1 or count in said)):
                return None
            out["count"] = count
        if tpl == "clock_stop":
            # The visual must correspond to a stopped clock, not merely the
            # word midnight. Midnight implies 12:00 AM by definition.
            if not re.search(r"\b(stop|stops|stopped|froze|frozen|freeze|halt|halted|ceased)\b", low):
                return None
            shown_time = str(f.get("time") or "").strip()[:14]
            if re.search(r"\bmidnight\b", low):
                out["time"] = "12:00 AM"
            elif shown_time and shown_time.lower() in low:
                out["time"] = shown_time
            else:
                spoken = re.search(r"\b([0-2]?\d:[0-5]\d)(?:\s*(am|pm))?\b", low)
                out["time"] = spoken.group(0).upper() if spoken else ""
    elif tpl == "missing":
        word = str(f.get("word") or "").upper()
        if not re.search(r"\b(vanish|disappear|missing|gone|never seen|never arrived)", low):
            return None
        out["word"] = word if word in ("MISSING", "VANISHED", "GONE") and word.lower()[:5] in low else ""
        out["subject"] = _subject(f.get("subject"), ctx) or "you"
        ls = str(f.get("last_seen") or "")[:28]
        out["last_seen"] = ls if ls and ok(ls) else ""
    return {"type": "graphic", "at": at, "template": tpl, "fields": out}


def _closing(story: dict, narration: dict, scenes: list[dict], ctx: dict) -> None:
    """The video ends on the closing mystery card when the narration ends on a question (and no closing card was
    planned): the question itself, word-synced, from the moment it is asked."""
    if any(s.get("template") == "closing" for sc in scenes for s in sc["shots"]):
        return
    last = (story["scenes"][-1].get("narration") or "").strip()
    sents = re.split(r"(?<=[.!?])\s+", last)
    q = sents[-1] if sents and sents[-1].endswith("?") else ""
    if not q or len(q.split()) > 18:
        return
    words = [w for w in narration["words"] if w.get("scene") == len(story["scenes"]) - 1]
    at = _anchor(" ".join(q.split()[:3]), words)
    if at is None:
        return
    scenes[-1]["shots"] = [s for s in scenes[-1]["shots"] if s.get("at") is None or s["at"] < at - 0.5] or \
        scenes[-1]["shots"][:1]
    scenes[-1]["shots"].append({"type": "graphic", "at": at, "template": "closing",
                                "fields": {"kicker": "YOUR CALL", "text": q, "accent": ""}})


_EXPR_WORDS = [("shocked", r"\b(gone|vanish|disappear|impossible|never|nobody|no one|dead)"),
               ("scared", r"\b(scream|terrif|afraid|fear)"), ("worried", r"\b(missing|search|wait|worr)"),
               ("curious", r"\b(why|what|how|wonder|theor)"), ("determined", r"\b(you check|decide|first|follow)")]


def _expr_for(text: str) -> str:
    return next((e for e, rx in _EXPR_WORDS if re.search(rx, text, re.IGNORECASE)), "neutral")


def _scene_spans(story: dict, narration: dict) -> list[tuple[float, float]]:
    st = narration.get("scene_times") or []
    if len(st) == len(story["scenes"]):
        spans = [(a, b) for a, b in st]
    else:
        spans = []
        for i in range(len(story["scenes"])):
            ws = [w for w in narration["words"] if w.get("scene") == i]
            spans.append((ws[0]["start"], ws[-1]["end"]) if ws else (0.0, 0.0))
    return [(0.0 if i == 0 else a, spans[i + 1][0] if i + 1 < len(spans) else narration["duration"])
            for i, (a, b) in enumerate(spans)]


def opener_length(story: dict) -> tuple[float, float]:
    """(TRUE STORY graphic end, title end): true stories open with the TRUE STORY motion graphic, then the title;
    other stories with the title only (owner, Oct 21). The narration's hook is heard from 0.0 s under both."""
    t_true = float(CONFIG.get("explainer_true_story_seconds", 1.2)) if story.get("true_story") else 0.0
    t_title = float(CONFIG.get("explainer_title_seconds", 1.6)) if story.get("title") else 0.0
    return t_true, t_true + t_title




# ================================================================ planning: graphics

GRAPHICS_PROMPT = """You design the EXPLANATORY GRAPHICS of a vertical Night Files video. The story itself is told
with story images (archive photos, stock footage, illustrations of each moment). Your graphics explain HOW, WHERE,
WHEN or WHY between those images.
TRUE STORY: {true}

NARRATION (scene number: text):
{scenes}

FACT LEDGER: {ledger}

Return JSON {{"scenes": [{{"graphics": [GRAPHIC, ...]}}, ...]}}: one entry per narration scene, in order, 1-2
graphics each. GRAPHIC = {{"at": "<first 2-4 words where it appears, copied exactly from that scene's narration>",
"template": "<template>", "fields": {{...}}}} where template + fields is one of:
  date_stamp  {{"kicker": "<what the date is, max 3 words, e.g. DISAPPEARANCE>", "year": <a year said in this scene>, "label": "<a month and day said with it, or empty>"}}
  evidence    {{"kicker": "<max 3 words>", "text": "<the clue / record / name, max 8 words>", "accent": "<one word>", "note": "<max 5 words>"}}
  map_route   {{"kicker": "THE ROUTE", "stops": ["<2-4 place names said in THIS scene, in travel order>"]}}
  fact        {{"kicker": "<max 3 words>", "value": <a number said>, "prefix": "", "suffix": "", "label": "<max 8 words>", "accent": "<one word>"}}
  quote       {{"text": "<words someone said, exactly as in the narration>", "by": "<who said it>"}}
  connections {{"kicker": "CONNECTIONS", "nodes": ["<2-4 people / places / clues said in the narration>"]}}
  compare     {{"kicker": "TWO THEORIES", "left": {{"title": "<max 3 words>", "items": ["<max 5 words>", "..."]}}, "right": {{...}}}}
  missing     {{"subject": "", "word": "<MISSING | VANISHED | GONE: only a word the narration uses>", "last_seen": "<a place said, or empty>"}}
  photo_scan  {{"kicker": "IMAGE INSPECTION", "text": "<a short phrase said>", "count": 1}}
  clock_stop  {{"kicker": "TIME", "text": "<short clock phrase said>", "time": "<a time actually said, else empty>"}}
  closing     {{"kicker": "YOUR CALL", "text": "<the closing question, exactly as in the narration>", "accent": "<one word>"}}
RULES
- Every word and number on a graphic must be said in that scene's narration{true_rule}. Never invent dates, places,
  distances, coordinates, statistics or conclusions.
- Pick the graphic that EXPLAINS the beat: date_stamp for when, map_route only when the scene names 2+ places
  someone travels between, evidence for a clue / object / record / name, quote for words someone said, missing when
  someone vanishes, fact for a number said, compare for two explanations, closing only for the final question.
- No people drawn, nothing occult, no gore.
"""

PLAN_TEMPLATES = ("date_stamp", "evidence", "map_route", "fact", "quote", "connections", "compare", "missing",
                  "photo_scan", "clock_stop", "shadow_reveal", "closing")


def _ledger_pairs(story: dict) -> list[tuple[str, str]]:
    out = []
    for line in story.get("fact_ledger") or []:
        if isinstance(line, str) and ":" in line:
            k, v = line.split(":", 1)
            out.append((k.strip(), v.strip()))
    return out


def _ledger_text(story: dict) -> str:
    return " ".join(str(x) for x in story.get("fact_ledger") or [])


def _kicker(text: str) -> str:
    return re.sub(r"[^A-Z &/'-]", "", str(text or "").upper()).strip()[:24]


def _scene_ctx(story: dict, i: int, base: dict) -> dict:
    """Validation context of ONE scene: its own words and numbers (a graphic shows what is said in its scene)."""
    narr = story["scenes"][i].get("narration", "")
    import spoken_numbers as nums
    return {**base, "said": nums.values(narr), "low": narr.lower()}


_MONTH = re.compile(r"\b(january|february|march|april|may|june|july|august|september|october|november|december)"
                    r"(\s+(?:the\s+)?[a-z]+(?:-[a-z]+)?)?", re.IGNORECASE)
_TRAVEL = re.compile(r"\b(fl[eyi]\w*|flight|cross\w*|travel\w*|journey\w*|sail\w*|drove|drive|route|left for|"
                     r"head\w* (?:to|for)|arriv\w*|board\w*|from)\b", re.IGNORECASE)
_VANISH = re.compile(r"\b(vanish\w*|disappear\w*|missing|never (?:seen|found|arrived)|no trace|gone)\b", re.IGNORECASE)
_QUOTE = re.compile(r"(?:^|[\s,:(])[\"“'‘](.{6,120}?)[\"”'’](?=[\s.,!?;:)]|$)")
_COMMON = set("during born working declared constructing after before when while once then later her his their "
              "you every each this that these those".split())
_GEO = re.compile(r"\b(ocean|sea|atlantic|pacific|river|island|lake|bay|gulf|mountains?|desert|coast)\b", re.IGNORECASE)
_PROPER_RX = re.compile(r"\b((?:[A-Z][a-z]+)(?:\s+(?:[A-Z][a-z]+|of|the|de|van))*\s+[A-Z][a-z]+|[A-Z][a-z]{3,})\b")


def _date_graphic(story: dict, i: int, sctx: dict) -> dict | None:
    """date_stamp for a year said in this scene (true stories: the year must be in the fact ledger too); the kicker
    is the ledger key whose value holds that year ("Disappearance date" -> DISAPPEARANCE DATE)."""
    narr = story["scenes"][i].get("narration", "")
    years = sorted(int(v) for v in sctx["said"] if 1000 <= v <= 2100 and float(v).is_integer())
    if not years:
        return None
    y = years[0]
    ledger = _ledger_text(story)
    if story.get("true_story") and ledger and str(y) not in ledger:
        return None
    kick = next((_kicker(k) for k, v in _ledger_pairs(story) if str(y) in v), "") or "WHEN"
    m = _MONTH.search(narr)
    label = m.group(0) if m else ""
    return {"type": "graphic", "at": None, "template": "date_stamp", "auto": True,
            "fields": {"kicker": kick, "year": str(y), "label": label}}


def _evidence_graphics(story: dict, i: int, sctx: dict) -> list[dict]:
    """A named record / person / place said in this scene: kicker = its fact-ledger key (AWARD, NAVIGATOR...) when
    the ledger has it, else NAME / PLACE / KEY DETAIL."""
    out, low = [], sctx["low"]
    for k, v in _ledger_pairs(story):
        if re.search(r"\b(date|born|birth|year)\b", k, re.IGNORECASE):
            continue
        for part in (p.strip() for p in v.split(",")):
            if len(part) > 3 and not re.search(r"\d", part) and _words_said(part, low):
                out.append({"type": "graphic", "at": None, "template": "evidence", "auto": True,
                            "fields": {"kicker": _kicker(k) or "KEY DETAIL", "text": part, "accent": "", "note": ""}})
    if out:
        return out[:2]
    narr = story["scenes"][i].get("narration", "")
    names = {c.get("name", "").lower() for c in story.get("characters") or []}
    places = {l.get("name", "").lower().removeprefix("the ") for l in story.get("locations") or []}
    for m in _PROPER_RX.finditer(narr):
        parts = m.group(1).split()
        start = m.start() == 0 or narr[:m.start()].rstrip()[-1:] in ".!?"
        while parts and (parts[0].lower() in STOP or parts[0].lower() in _COMMON or start and parts[0].lower()
                         not in " ".join(names | places)):
            parts, start = parts[1:], False
        ph = " ".join(parts)
        low_ph = ph.lower()
        is_name = any(low_ph in n or n in low_ph for n in names if n)
        is_place = any(low_ph in p_ for p_ in places if p_) or bool(_GEO.search(ph))
        if len(ph) < 4 or (len(parts) < 2 and not is_place) or (is_name and len(parts) < 2):
            continue  # a lone first name is no evidence; a lone word only when it is a known place
        kind = "NAME" if is_name else "PLACE" if is_place else "KEY DETAIL"
        out.append({"type": "graphic", "at": None, "template": "evidence", "auto": True,
                    "fields": {"kicker": kind, "text": ph, "accent": "", "note": ""}})
    return out[:1]


def _auto_graphics(story: dict, i: int, sctx: dict) -> list[dict]:
    """Factual graphics built from this scene's own words + the fact ledger, best first. Never a fabricated value."""
    narr = story["scenes"][i].get("narration", "")
    out = []
    if _VANISH.search(narr):
        word = next((w for w in ("VANISHED", "DISAPPEARED", "MISSING", "GONE") if w.lower()[:6] in narr.lower()), "")
        places = [(l.get("name") or "") for l in story.get("locations") or []]
        place = next((m.group(1) for m in _PROPER_RX.finditer(narr) if m.start() > 0 and narr[m.start() - 2] not in ".!?"
                      and (_GEO.search(m.group(1)) or any(m.group(1) in pl for pl in places))), "")
        geo = re.search(r"\bthe\s+((?:[A-Z][a-z]+\s+)*(?:Ocean|Sea|Atlantic|Pacific|River|Island|Lake|Bay))\b", narr)
        out.append({"type": "graphic", "at": None, "template": "missing", "auto": True,
                    "fields": {"subject": "", "word": word, "last_seen": (geo.group(1) if geo else place)[:28]}})
    q = _QUOTE.search(narr)
    if q and len(q.group(1).split()) >= 3:
        who = ""
        for c in story.get("characters") or []:  # the part of the name this scene says ("Amelia")
            said_parts = [w for w in (c.get("name") or "").split() if re.search(rf"\b{re.escape(w)}\b", narr)]
            if said_parts:
                who = " ".join(said_parts)
                break
        out.append({"type": "graphic", "at": None, "template": "quote", "auto": True,
                    "fields": {"text": q.group(1).strip(), "by": who}})
    d = _date_graphic(story, i, sctx)
    if d:
        out.append(d)
    out += _evidence_graphics(story, i, sctx)
    if _TRAVEL.search(narr):
        stops = [m.group(1) for m in _PROPER_RX.finditer(narr) if not m.group(1).split()[0].lower() in STOP]
        stops = list(dict.fromkeys(s for s in stops if _GEO.search(s) or any(
            s.lower() in (l.get("name") or "").lower() for l in story.get("locations") or [])))
        if len(stops) >= 2:
            out.append({"type": "graphic", "at": None, "template": "map_route", "auto": True,
                        "fields": {"kicker": "THE ROUTE", "stops": stops[:4]}})
    small = sorted(v for v in sctx["said"] if 2 <= v < 1000 and float(v).is_integer())
    if small:
        words = narr.split()
        import spoken_numbers as nums
        for k, w in enumerate(words):
            if nums.values(w) & {small[0]}:
                label = " ".join(words[k + 1:k + 4]).strip(".,!?;:")
                out.append({"type": "graphic", "at": None, "template": "fact", "auto": True,
                            "fields": {"kicker": "THE COUNT", "value": small[0], "prefix": "", "suffix": "",
                                       "label": label, "accent": ""}})
                break
    return out


def _impact_fallback(story: dict, i: int) -> dict:
    """No factual graphic fits this beat: the scene's own key words as an impact card (reported as an exception)."""
    narr = story["scenes"][i].get("narration", "")
    words = [w.strip(".,!?;:'\"") for w in narr.split()]
    keep = [w for w in words if w and w.lower() not in STOP and len(w) > 3][:40]
    best = sorted(keep, key=lambda w: (-len(w), keep.index(w)))[:2]
    text = " ".join(sorted(best, key=keep.index)).upper()
    return {"type": "graphic", "at": None, "template": "impact", "auto": True,
            "exception": "no factual graphic fits this beat: key words of the narration",
            "fields": {"text": text, "accent": best[0] if best else ""}}


def plan_graphics(story: dict, narration: dict) -> list[list[dict]]:
    """1-2 explanatory graphics per scene, best first: the LLM's valid picks (strongest model; checked word by word),
    then factual auto graphics, then an impact card as a reported exception. The final question = closing card."""
    words = narration["words"]
    true = bool(story.get("true_story"))
    scenes_txt = "\n".join(f"{i + 1}: {sc.get('narration', '')}" for i, sc in enumerate(story["scenes"]))
    data = _plan_call(GRAPHICS_PROMPT.format(
        true="yes" if true else "no", scenes=scenes_txt, ledger="; ".join(map(str, story.get("fact_ledger") or []))
        or "none", true_rule=" (TRUE story: never invent a number)" if true else "")) or {}
    raw = data.get("scenes") if isinstance(data.get("scenes"), list) else []
    base = {"cast": {}, "dates": 0}  # date_stamp graphics are checked by _date_graphic / graphic_problem
    out = []
    for i, sc in enumerate(story["scenes"]):
        sctx = _scene_ctx(story, i, base)
        s_words = [w for w in words if w.get("scene") == i]
        picks = []
        rs = raw[i] if i < len(raw) and isinstance(raw[i], dict) else {}
        for g in (rs.get("graphics") or [])[:3]:
            if not isinstance(g, dict) or g.get("template") not in PLAN_TEMPLATES:
                continue
            if g["template"] == "closing" and i != len(story["scenes"]) - 1:
                continue
            at = _anchor(str(g.get("at") or ""), s_words)
            v = _date_graphic(story, i, sctx) if g["template"] == "date_stamp" else _valid_graphic(g, at, sctx)
            if v:
                v["at"] = at
                if v["template"] == "missing":  # nobody is drawn: the host never stands in for a real person
                    v["fields"]["subject"] = ""
                picks.append(v)
        picks += _auto_graphics(story, i, sctx)
        seen, uniq = set(), []
        for g in picks:
            key = (g["template"], json.dumps(g["fields"], sort_keys=True, default=str))
            if key not in seen and graphic_problem(story, i, g) is None:
                seen.add(key)
                uniq.append(g)
        out.append(uniq or [_impact_fallback(story, i)])
    closing = {"type": "graphic", "template": "closing"}
    shell = [{"shots": [dict(g) for g in gs]} for gs in out]
    _closing(story, narration, shell, {"cast": {}})
    last = [s for s in shell[-1]["shots"] if s.get("template") == "closing"]
    if last:
        closing = last[-1]
        out[-1] = [g for g in out[-1] if g.get("template") != "closing"] + [closing]
    return out


def graphic_problem(story: dict, i: int, g: dict) -> str | None:
    """None if every word / number on this graphic is said in its scene's narration (and, for a true story's date,
    in the fact ledger); else the reason. Used by the planner and again by the visual QA on the final shot list."""
    narr = story["scenes"][i].get("narration", "")
    low = narr.lower()
    import spoken_numbers as nums
    said = nums.values(narr)
    f = g.get("fields") or {}
    tpl = g.get("template")
    texts = []
    if tpl == "date_stamp":
        try:
            y = int(f.get("year"))
        except (TypeError, ValueError):
            return "date_stamp without a year"
        if y not in said:
            return f"year {y} is not said in scene {i + 1}"
        if story.get("true_story") and _ledger_text(story) and str(y) not in _ledger_text(story):
            return f"year {y} is not in the fact ledger"
        texts.append(f.get("label") or "")
    elif tpl == "map_route":
        texts += list(f.get("stops") or [])
    elif tpl == "connections":
        texts += list(f.get("nodes") or [])
    elif tpl == "compare":
        for side in ("left", "right"):
            c = f.get(side) or {}
            texts += [c.get("title") or ""] + list(c.get("items") or [])
    elif tpl == "fact":
        try:
            v = float(f.get("value"))
        except (TypeError, ValueError):
            return "fact without a value"
        if not (v <= 3 or v in said):
            return f"number {f.get('value')} is not said in scene {i + 1}"
        texts.append(f.get("label") or "")
    elif tpl == "missing":
        texts += [f.get("last_seen") or ""]
        if not _VANISH.search(narr):
            return "missing graphic without a disappearance in the narration"
    for k in ("text", "note", "by"):
        if f.get(k):
            texts.append(f[k])
    for txt in texts:
        txt = str(txt or "").strip()
        if not txt:
            continue
        if not _words_said(txt, low):
            return f"'{txt[:40]}' is not said in scene {i + 1}"
        if not _number_ok(txt, said):
            return f"'{txt[:40]}' has a number not said in scene {i + 1}"
    return None


# ================================================================ planning: the shot sequence

_EMOTION = re.compile(r"\b(you\b|wonder\w*|fear\w*|afraid|terrif\w*|shock\w*|strange|impossible|never|nobody|"
                      r"no one|why|what happened|gone|vanish\w*|disappear\w*|dead|declared|search\w*|dream\w*)",
                      re.IGNORECASE)


def _image_items(i: int, files: list[Path]) -> list[dict]:
    """The scene's own pictures (real media / AI / library), each once full frame and once as a detail crop."""
    full = [{"type": "image", "scene": i, "file": str(f), "crop": "full"} for f in files]
    crops = ("detail_left", "detail_right", "top", "bottom")
    detail = [{"type": "image", "scene": i, "file": str(f), "crop": crops[(i + k) % len(crops)]}
              for k, f in enumerate(files)]
    return full + detail


def _slot_lengths(n: int, kinds: list[str], span: float) -> list[float]:
    host = float(CONFIG.get("explainer_host_max_seconds", 2.0))
    fixed = [min(host, 1.8) if k == "host" else None for k in kinds]
    rest = span - sum(x for x in fixed if x)
    weights = [1.15 if k == "graphic" else 1.0 for k in kinds]
    free = sum(w for w, x in zip(weights, fixed) if x is None) or 1.0
    return [x if x is not None else rest * w / free for w, x in zip(weights, fixed)]


def sequence(story: dict, narration: dict, scene_images: list[list[Path]], graphics: list[list[dict]],
             total: float) -> list[dict]:
    """The production shot list: per scene  story image -> graphic -> second story image -> (rare host reaction),
    with varied deliberate holds and cuts on word starts. The host: max 1 shot per scene, never in two scenes in a row, never first in a
    scene, <= explainer_host_max_seconds (2 s), <= explainer_host_max_share (15%) of the runtime. The video opens on
    the TRUE STORY / title graphics and ends on the closing graphic (no end card)."""
    spans = _scene_spans(story, narration)
    t_true, t_title = opener_length(story)
    words = narration["words"]
    budget = float(CONFIG.get("explainer_host_max_share", 0.15)) * total
    host_used, last_host_scene = 0.0, -9
    prev_template = ""
    segs = []
    if t_true:
        segs.append({"start": 0.0, "end": t_true, "shot": {"type": "opener", "scene": 0}, "scene": 0})
    if t_title:
        segs.append({"start": t_true, "end": t_title, "shot": {"type": "opener_title", "scene": 0}, "scene": 0})
    n_sc = len(story["scenes"])
    for i, (a, b) in enumerate(spans):
        a = max(a, t_title) if i == 0 else a
        b = total if i == n_sc - 1 else b
        span = b - a
        if span <= 0.05:
            continue
        imgs = _image_items(i, scene_images[i])
        if not imgs:
            raise ExplainerUnavailable(f"scene {i + 1} has no image of its own (never another scene's picture)")
        gs = [dict(g, scene=i) for g in graphics[i]]
        closing = gs.pop() if i == n_sc - 1 and gs and gs[-1].get("template") == "closing" else None
        if len(gs) > 1 and gs[0]["template"] == prev_template:  # never the same template two scenes in a row
            gs.append(gs.pop(0))
        prev_template = gs[0]["template"] if gs else prev_template
        narr = story["scenes"][i].get("narration", "")
        host_ok = (i > 0 and i - last_host_scene > 1 and host_used + 1.8 <= budget
                   and (_EMOTION.search(narr) or len(scene_images[i]) < 2) and span >= 6.0)
        n = max(2 if gs else 1, min(6, round(span / 4.5)))
        order = [imgs[0]]
        if gs:
            order.append(gs[0])
        if len(scene_images[i]) > 1:
            order.append(imgs[1])
        if host_ok:
            order.append({"type": "host", "scene": i, "expression": _expr_for(narr)})
        if len(gs) > 1 and span > 9.0:
            order.append(gs[1])
        # Avoid manufacturing extra cuts by repeating crops of the same image.
        if closing:
            order.append(closing)
        while len(order) > max(1, n) and len(order) > (2 if closing else 1):
            drop = next((x for x in reversed(order[1:]) if x["type"] == "host"), None) or next((x for x in reversed(order[1:]) if x["type"] == "image"), None) or next((x for x in reversed(order[1:]) if x["type"] == "graphic" and x is not closing), None)
            if drop is None:
                break
            order.remove(drop)
        while len(order) > 2 and span / len(order) < SHOT_MIN:
            # too many cuts for a short scene: host first, then extra framings, then the second picture; the
            # scene's graphic (and its first picture) stay
            drop = next((x for x in reversed(order) if x["type"] == "host"), None) or \
                next((x for x in reversed(order) if x["type"] == "image" and x.get("crop") != "full"), None) or \
                next((x for x in reversed(order[1:]) if x["type"] == "image"), None) or \
                next((x for x in reversed(order[1:]) if x["type"] == "graphic" and x is not closing), None)
            if drop is None:
                break
            order.remove(drop)
        for k in range(1, len(order)):  # never image -> same image framing twice in a row
            if order[k]["type"] == order[k - 1]["type"] == "image" and order[k]["file"] == order[k - 1]["file"] \
                    and order[k]["crop"] == order[k - 1]["crop"]:
                order[k] = dict(order[k], crop="detail_right" if order[k]["crop"] != "detail_right" else "top")
        lens = _slot_lengths(len(order), [x["type"] for x in order], span)
        for _ in range(4):  # Avoid repeated crops except for excessively long holds
            k = next((k for k, ln in enumerate(lens) if ln > SHOT_MAX - 0.15 and order[k] is not closing), None)
            if k is None:
                break
            if order[k]["type"] == "image" or not any(x["type"] == "image" for x in order):
                src = order[k] if order[k]["type"] == "image" else imgs[0]
                order.insert(k + 1, dict(src, crop=("detail_right", "top", "detail_left", "bottom")[(k + i) % 4]))
            else:
                j = max((j for j, x in enumerate(order) if x["type"] == "image"), key=lambda j: -lens[j])
                order.insert(j + 1, dict(order[j], crop="detail_left" if order[j].get("crop") != "detail_left"
                                         else "detail_right"))
            lens = _slot_lengths(len(order), [x["type"] for x in order], span)
        t = a
        cuts = [a]
        for ln in lens[:-1]:
            t += ln
            near = [w["start"] for w in words if abs(w["start"] - t) < 0.35 and cuts[-1] + SHOT_MIN <= w["start"]
                    <= cuts[-1] + SHOT_MAX - 0.05]
            cuts.append(min(near, key=lambda x: abs(x - t)) if near else t)
        cuts.append(b)
        for k, item in enumerate(order):
            s0, s1 = cuts[k], cuts[k + 1]
            if item["type"] == "host":
                s1 = min(s1, s0 + float(CONFIG.get("explainer_host_max_seconds", 2.0)))
                if k + 1 < len(order):
                    cuts[k + 1] = s1
                host_used += s1 - s0
                last_host_scene = i
            segs.append({"start": round(s0, 3), "end": round(s1, 3), "shot": item, "scene": i})
    for k in range(1, len(segs)):  # contiguous timeline
        segs[k]["start"] = segs[k - 1]["end"]
    return segs


# ================================================================ story images

def fresh_images() -> bool:
    """buffer_fill.yml checkbox fresh_images (env FRESH_IMAGES, default ON like the checkbox).
    ON: a new story gets fresh scene-specific images (no asset-library reuse); a resumed story keeps its valid
    images and redraws ONLY missing / corrupt / rejected ones. OFF: this story's cached images, then matching
    asset-library pictures and licensed archive / stock media, then new images for what is still missing.
    The approved character art is never touched by either setting, and the checkpoint is never reset."""
    return (os.environ.get("FRESH_IMAGES") or "true").strip().lower() not in ("0", "false", "no", "off")


def valid_image(path: Path) -> bool:
    """A readable image of at least 256 px whose sidecar (if any) doesn't record a QA rejection."""
    try:
        with Image.open(path) as im:
            im.verify()
        with Image.open(path) as im:
            im.load()
            if min(im.size) < 256:
                return False
    except Exception:  # noqa: BLE001
        return False
    side = path.with_suffix(".json")
    if side.exists():
        try:
            return json.loads(side.read_text()).get("qa") != "FAIL"
        except ValueError:
            return False
    return True


def _prompt_of(story: dict, i: int, letter: str) -> str:
    import images
    return (story["scenes"][i].get(images.PROMPT_KEYS[letter]) or "").strip()


def _stale_images(story: dict, img_dir: Path) -> int:
    """An AI image is cached by story + prompt + provider + sha256 (scene_XXl.ai.json): a file whose bytes changed
    or whose shot prompt changed is deleted so it is redrawn; real media / library sidecars are checked the same
    way by the checkpoint manifest. Returns how many were dropped."""
    import hashlib
    dropped = 0
    for side in img_dir.glob("scene_*.ai.json"):
        png = img_dir / side.name.replace(".ai.json", ".png")
        try:
            meta = json.loads(side.read_text())
        except ValueError:
            meta = {}
        tag = png.stem.replace("scene_", "")
        try:
            want = _prompt_of(story, int(tag[:2]), tag[2])
        except (ValueError, IndexError, KeyError):
            want = None
        ok = png.exists() and meta.get("sha256") == hashlib.sha256(png.read_bytes()).hexdigest() \
            and (want is None or meta.get("prompt") == want) and meta.get("story_id") == story.get("story_id")
        if not ok:
            png.unlink(missing_ok=True)
            side.unlink(missing_ok=True)
            dropped += 1
    for png in img_dir.glob("scene_*.png"):
        if ".rejected" not in png.name and ".qa" not in png.name and not valid_image(png):
            png.unlink(missing_ok=True)
            dropped += 1
    return dropped


def story_images(story: dict, img_dir: Path) -> list[list[Path]]:
    """The scene-specific pictures of THIS story, through the existing media chain (same budget, QA and fallbacks
    as classic): (fresh_images OFF) asset library -> licensed real media (archive photos / prints, Pexels / Pixabay
    photos + clips) -> AI images for the rest (Cloudflare -> broker fallbacks -> local), shots_per_scene per scene
    from the story's own image_prompt / image_query fields. Returns [[scene pictures], ...] (never another scene's)."""
    import hashlib
    import checkpoint
    import images
    import library
    import media
    from common import load_history
    img_dir.mkdir(parents=True, exist_ok=True)
    fresh = fresh_images()
    for sc in story["scenes"]:  # planners sometimes put a query into image_source_3/4: keep it as the query
        for l, key in media.SRC_KEYS.items():
            v = str(sc.get(key) or "").strip()
            if v and v.lower() not in ("ai", "stock_video", "real_photo", "archive_print"):
                sc.setdefault(media.QUERY_KEYS[l], v)
                sc[key] = "ai"
    dropped = _stale_images(story, img_dir)
    history = load_history()
    if not fresh:
        library.fill_shots(story, img_dir, history)
    media.fill_shots(story, img_dir, history)
    per_scene = images.generate_images(story, img_dir)
    for f in img_dir.glob("scene_*.png"):  # cache key for AI pictures + checkpoint manifest entry for all
        if ".rejected" in f.name or ".qa" in f.name or f.name.endswith(".ai.png"):
            continue
        tag = f.stem.replace("scene_", "")
        if not f.with_suffix(".json").exists() and not f.with_suffix(".reuse.json").exists() \
                and not f.with_name(f.stem + ".ai.json").exists() and len(tag) == 3:
            prov = (story.get("_shot_provider") or {}).get(tag, "")
            f.with_name(f.stem + ".ai.json").write_text(json.dumps({
                "story_id": story.get("story_id"), "prompt": _prompt_of(story, int(tag[:2]), tag[2]),
                "provider": prov, "sha256": hashlib.sha256(f.read_bytes()).hexdigest()}))
        checkpoint.register_image(f)
    story["explainer_images"] = {"fresh_images": fresh, "dropped_stale": dropped,
                                 "per_scene": [len(x) for x in per_scene]}
    log(f"Explainer story images (fresh_images {'ON' if fresh else 'OFF'}): {sum(len(x) for x in per_scene)} "
        f"picture(s) over {len(per_scene)} scene(s), {dropped} stale/corrupt dropped")
    return [list(dict.fromkeys(x)) for x in per_scene]


# ================================================================ drawing helpers

_FONTS: dict = {}


def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    if kind.startswith("cond"):
        import noir
        return noir.font(kind, size)
    key = (kind, size)
    if key in _FONTS:
        return _FONTS[key]
    try:
        if kind == "mono":
            f = ImageFont.truetype(str(FONT_DIR / "SpaceMono-Bold.ttf"), size)
        else:
            f = ImageFont.truetype(str(FONT_DIR / "Montserrat-VF.ttf"), size)
            f.set_variation_by_name({"black": "Black", "bold": "ExtraBold", "semi": "SemiBold"}.get(kind, "Black"))
    except Exception:  # noqa: BLE001
        f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size)
    _FONTS[key] = f
    return f


def _ease(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3




def _wrap(text: str, f, width: int) -> list[list[str]]:
    d = ImageDraw.Draw(Image.new("L", (1, 1)))
    lines, cur = [], []
    for w in text.split():
        if cur and d.textlength(" ".join(cur + [w]), font=f) > width:
            lines.append(cur)
            cur = []
        cur.append(w)
    if cur:
        lines.append(cur)
    return lines






# ================================================================ renderer

CROPS = {"full": (0.5, 0.5, 1.0), "detail_left": (0.33, 0.45, 1.45), "detail_right": (0.67, 0.45, 1.45),
         "top": (0.5, 0.3, 1.35), "bottom": (0.5, 0.7, 1.35)}


class Renderer:
    def __init__(self, story: dict, narration: dict, segs: list[dict], img_dir: Path | None = None):
        self.story, self.narr, self.segs = story, narration, segs
        self.img_dir = img_dir
        self.acc = accent()
        self.cache: dict = {}
        self.layer_cache: dict = {}
        self.groups = _caption_groups(narration["words"])
        self.t_true, self.t_title = opener_length(story)
        self.used_assets: set = set()
        self.frame_log = {"image": 0, "graphic": 0, "host": 0, "opener": 0, "end_card": 0}
        self.first_image = next((s["shot"]["file"] for s in segs if s["shot"].get("type") == "image"), None)

    # ---------------------------------------------------------------- pictures
    def _cover(self, path: str, zoom: float = 1.0) -> Image.Image:
        """The picture scaled to cover 1080x1920 (x zoom headroom), lightly graded; cached."""
        key = ("cover", path, zoom)
        if key not in self.cache:
            if len(self.cache) > 40:
                self.cache = {k: v for k, v in self.cache.items() if k[0] != "cover"}
            im = Image.open(path).convert("RGB")
            scale = max(W / im.width, H / im.height) * zoom
            im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
            im = ImageEnhance.Contrast(ImageEnhance.Brightness(im).enhance(0.9)).enhance(1.05)
            self.cache[key] = im.convert("RGBA")
        return self.cache[key]

    def _clip_frame(self, path: str, t: float) -> Image.Image | None:
        """A stock clip next to the picture (scene_XXl.mp4): its frame at t (frames dumped once, 30 fps)."""
        mp4 = Path(path).with_suffix(".mp4")
        if not mp4.exists():
            return None
        import hashlib
        import tempfile  # frames stay out of the checkpoint (Actions cache size)
        d = Path(tempfile.gettempdir()) / "nf_clip_frames" / hashlib.sha1(str(mp4.resolve()).encode()).hexdigest()[:12]
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(mp4), "-t", "6", "-vf", f"fps={FPS}",
                            "-q:v", "3", str(d / "%04d.jpg")], check=False)
        frames = sorted(d.glob("*.jpg"))
        if not frames:
            return None
        f = frames[min(len(frames) - 1, int(t * FPS))]
        return self._cover(str(f), 1.0)

    def _blurred(self, path: str) -> Image.Image:
        key = ("blur", path)
        if key not in self.cache:
            base = self._crop(self._cover(path, 1.0), 0.5, 0.5, 1.0)
            bg = base.filter(ImageFilter.GaussianBlur(16)).convert("RGB")
            self.cache[key] = ImageEnhance.Brightness(bg).enhance(0.34).convert("RGBA")
        return self.cache[key]

    def image_frame(self, seg: dict, t: float) -> Image.Image:
        """A story picture: its framing (full / detail crop) with a slow push or pan; a stock clip plays."""
        s = seg["shot"]
        dur = max(0.01, seg["end"] - seg["start"])
        x = _ease(t / dur)
        cx, cy, z = CROPS.get(s.get("crop", "full"), CROPS["full"])
        clip = self._clip_frame(s["file"], t)
        base = clip if clip is not None else self._cover(s["file"], 1.08)
        k = self._index(seg) % 3
        if k == 0:
            frame = self._crop(base, cx, cy, z * (1.0 + 0.095 * x))
        elif k == 1:
            frame = self._crop(base, cx + 0.075 * (x - 0.5), cy, z * 1.03)
        else:
            frame = self._crop(base, cx, cy + 0.06 * (0.5 - x), z * (1.09 - 0.075 * x))
        frame.alpha_composite(self._vignette())
        return frame

    # ---------------------------------------------------------------- the approved host (occasional B-roll)
    def figure(self, view, facing, height):
        """The approved host (M01-M04) at `height`: placement only. Raises sprites.MissingAsset by asset ID."""
        import sprites
        im, foot = sprites.full_body(view, int(height), facing)
        self.used_assets.add(sprites.body_id(view))
        return im, foot

    def host_frame(self, seg: dict, t: float) -> Image.Image:
        """A reaction: the approved F-face (or, every third host shot, the approved M02 full body) composited over a
        blurred, darkened crop of the scene's own picture. The figure itself is never altered."""
        import sprites
        s = seg["shot"]
        scene_imgs = [x["shot"]["file"] for x in self.segs if x["shot"].get("type") == "image"
                      and x["scene"] == seg["scene"]] or [self.first_image]
        # behind the host: never an archival photo (it may show the real person); another picture of the scene
        drawn = [f for f in scene_imgs if f and provenance_of(f).get("kind") != "archival"]
        scene_imgs = drawn or [f for f in (x["shot"]["file"] for x in self.segs if x["shot"].get("type") == "image")
                               if provenance_of(f).get("kind") != "archival"][:1] or scene_imgs
        frame = self._blurred(scene_imgs[0]).copy() if scene_imgs[0] else Image.new("RGBA", (W, H), BLACK + (255,))
        n = sum(1 for x in self.segs[:self._index(seg)] if x["shot"].get("type") == "host")
        dur = max(0.01, seg["end"] - seg["start"])
        push = 1.0 + 0.025 * _ease(t / dur)
        if n % 3 == 2:
            im, (fxp, fyp) = self.figure("three_quarter", "right", int(1150 * push))
            ox, oy = int(W * 0.5 - fxp), int(1640 - fyp)
            sh = self._shadow(int(im.width * 0.9))
            self._paste(frame, sh, int(W * 0.5 - sh.width / 2), 1640 - sh.height // 2)
        else:
            im, aid = sprites.bust(s.get("expression") or "neutral")
            self.used_assets.add(aid)
            scale = min(1400 / im.width, 1250 / im.height) * push  # the bust's cut edge sits below the frame
            im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.Resampling.LANCZOS)
            ox, oy = int((W - im.width) / 2), H - im.height + 40
        self._spill(frame, im, ox, oy)
        self._paste(frame, im, ox, oy)
        frame.alpha_composite(self._vignette())
        return frame

    def _spill(self, frame: Image.Image, im: Image.Image, ox: int, oy: int) -> None:
        """Light from the figure's red aura on the picture behind it (never on the figure)."""
        key = ("spill", im.size)
        layer = self.layer_cache.get(key)
        if layer is None:
            pad = 60
            a = Image.new("L", (im.width + 2 * pad, im.height + 2 * pad), 0)
            a.paste(im.getchannel("A"), (pad, pad))
            glow = a.filter(ImageFilter.GaussianBlur(28)).point(lambda v: int(v * 0.30))
            layer = Image.new("RGBA", a.size, (205, 30, 45, 0))
            layer.putalpha(glow)
            self.layer_cache[key] = layer
        self._paste(frame, layer, ox - 60, oy - 60)

    # ---------------------------------------------------------------- frames
    def _opener_bg(self) -> Image.Image:
        if self.first_image:
            return self._blurred(self.first_image).copy()
        return Image.new("RGBA", (W, H), BLACK + (255,))

    def frame_at(self, t: float) -> Image.Image:
        """The frame at t: opener graphics, story pictures, graphics or a host reaction. There is no end card: the
        last segment (the closing graphic or the last picture) runs to the end."""
        import noir
        seg = next((s for s in self.segs if s["start"] <= t < s["end"]), self.segs[-1])
        local = t - seg["start"]
        sh = seg["shot"]
        kind = sh["type"]
        dur = seg["end"] - seg["start"]
        if kind == "opener":
            frame = noir.render("true_story", {}, local, dur, self.ctx(seg, bg=self._opener_bg()))
            self.frame_log["opener"] += 1
        elif kind == "opener_title":
            frame = noir.render("title", {"text": self.story.get("fixed_title") or self.story.get("title") or ""},
                                local, dur, self.ctx(seg, bg=self._opener_bg()))
            self.frame_log["opener"] += 1
        elif kind == "graphic":
            frame = self._slide_in(noir.render(sh["template"], sh.get("fields") or {}, local, dur, self.ctx(seg)),
                                   local)
            self.frame_log["graphic"] += 1
        elif kind == "host":
            frame = self.host_frame(seg, local)
            self.frame_log["host"] += 1
        else:
            frame = self.image_frame(seg, local)
            self.frame_log["image"] += 1
            if CONFIG.get("explainer_cinematic_camera", False):
                frame = noir.cinematic_camera(frame, "subtle_push", local, dur)
        if not (CONFIG.get("remotion_polish", False) or CONFIG.get("explainer_caption_engine") == "remotion"):
            self.captions(frame, t, "scene")
        return frame

    def _index(self, seg: dict) -> int:
        try:
            return self.segs.index(seg)
        except ValueError:
            return 0

    def ctx(self, seg: dict, bg=None) -> dict:
        """What a noir template needs: palette, the segment's words (word-synced reveals) and, as its ground, a
        darkened blur of the scene's own picture (the graphic stays in the story's world)."""
        k = self._index(seg)
        sh = seg["shot"]
        if bg is None:
            own = next((x["shot"]["file"] for x in self.segs if x["shot"].get("type") == "image"
                        and x["scene"] == seg["scene"]), self.first_image)
            bg = self._blurred(own).copy() if own else None
        c = {"accent": self.acc, "tone": __import__("noir").tone_for(k), "seed": k % 7 + 1,
             "words": [{"word": w["word"], "start": w["start"] - seg["start"]} for w in self.narr["words"]
                       if seg["start"] - 0.05 <= w["start"] < seg["end"]], "bg": bg}
        if sh.get("template") == "filmstrip":
            files = list(dict.fromkeys(x["shot"]["file"] for x in self.segs if x["shot"].get("type") == "image"))
            c["stills"] = [Image.open(p) for p in files[:4]]
        return c

    def _slide_in(self, frame: Image.Image, t: float) -> Image.Image:
        """Graphics wipe in from the right over 0.2 s."""
        k = _ease(t / 0.2)
        if k >= 1:
            return frame
        out = Image.new("RGBA", (W, H), BLACK + (255,))
        out.alpha_composite(frame, (int(W * (1 - k)), 0))
        return out

    def _vignette(self) -> Image.Image:
        if "vig" not in self.layer_cache:
            y, x = np.ogrid[:H // 8, :W // 8]
            d = np.sqrt(((x - W / 16) / (W / 16)) ** 2 + ((y - H / 16) / (H / 16)) ** 2)
            a = np.clip((d - 0.65) * 230, 0, 170).astype("uint8")
            v = Image.new("RGBA", (W // 8, H // 8), (0, 0, 0, 0))
            v.putalpha(Image.fromarray(a))
            self.layer_cache["vig"] = v.resize((W, H), Image.BICUBIC)
        return self.layer_cache["vig"]

    def _shadow(self, w: int) -> Image.Image:
        key = ("shadow", w)
        if key not in self.layer_cache:
            im = Image.new("RGBA", (w, 70), (0, 0, 0, 0))
            ImageDraw.Draw(im).ellipse((0, 10, w, 60), fill=(0, 0, 0, 120))
            self.layer_cache[key] = im.filter(ImageFilter.GaussianBlur(12))
        return self.layer_cache[key]

    @staticmethod
    def _paste(frame: Image.Image, im: Image.Image, ox: int, oy: int) -> None:
        l, t = max(0, -ox), max(0, -oy)
        r, b = min(im.width, W - ox), min(im.height, H - oy)
        if r > l and b > t:
            frame.alpha_composite(im.crop((l, t, r, b)), (max(0, ox), max(0, oy)))

    @staticmethod
    def _crop(base: Image.Image, cx: float, cy: float, z: float) -> Image.Image:
        bw, bh = base.size
        w = min(bw, bh * W / H) / max(1.0, z)
        h = w * H / W
        x0 = max(0, min(bw - w, cx * bw - w / 2))
        y0 = max(0, min(bh - h, cy * bh - h / 2))
        return base.resize((W, H), Image.BILINEAR, box=(x0, y0, x0 + w, y0 + h)).convert("RGBA")

    def captions(self, frame: Image.Image, t: float, kind: str) -> None:
        g = next((g for g in self.groups if g["start"] <= t < g["end"]), None)
        if not g:
            return
        active = max([k for k, w in enumerate(g["words"]) if w["start"] <= t + 0.03] or [0])
        key = ("cap", id(g), active, kind)
        im = self.layer_cache.get(key)
        if im is None:
            im = self._caption_image(g, active, kind)
            self.layer_cache[key] = im
        frame.alpha_composite(im, (0, CAP_Y - im.height // 2))

    def _caption_image(self, g: dict, active: int, kind: str) -> Image.Image:
        f = font("bold", 78)
        texts = [w["text"] for w in g["words"]]
        lines = _wrap(" ".join(texts), f, 860)
        hgt = len(lines) * 96 + 40
        im = Image.new("RGBA", (W, hgt), (0, 0, 0, 0))
        shadow = Image.new("RGBA", (W, hgt), (0, 0, 0, 0))
        d, ds = ImageDraw.Draw(im), ImageDraw.Draw(shadow)
        k = 0
        for li, line in enumerate(lines):
            widths = [d.textlength(w, font=f) for w in line]
            sp = d.textlength(" ", font=f)
            x = (W - (sum(widths) + sp * (len(line) - 1))) / 2
            y = 20 + li * 96
            for w, ww in zip(line, widths):
                on = k == active
                if kind == "card":
                    col = INK + (255,) if on else (INK[0], INK[1], INK[2], 105)
                else:
                    col = (255, 255, 255, 255) if on else (255, 255, 255, 120)
                    ds.text((x, y + 6), w, font=f, fill=(0, 0, 0, 200))
                d.text((x, y), w, font=f, fill=col)
                x += ww + sp
                k += 1
        if kind != "card":
            shadow = shadow.filter(ImageFilter.GaussianBlur(9))
            shadow.alpha_composite(im)
            return shadow
        return im


def _caption_groups(words: list[dict]) -> list[dict]:
    """1-3 words per caption, broken at punctuation and pauses; each shown until the next one starts."""
    groups, cur = [], []
    for k, w in enumerate(words):
        cur.append(w)
        nxt = words[k + 1] if k + 1 < len(words) else None
        end = bool(re.search(r"[.,!?;:…]$", w["word"])) or len(cur) >= 3 or not nxt or nxt["start"] - w["end"] > 0.3
        if end:
            groups.append(cur)
            cur = []
    out = []
    for k, g in enumerate(groups):
        nxt = groups[k + 1][0]["start"] if k + 1 < len(groups) else g[-1]["end"] + 0.3
        out.append({"start": g[0]["start"], "end": max(nxt, g[-1]["end"]),
                    "words": [{"start": w["start"], "text": re.sub(r"[{}\\]", "", w["word"])} for w in g]})
    return out


# ================================================================ audio + encode

def _load_sfx(name: str, sr: int) -> np.ndarray | None:
    path = ROOT / "assets" / "sfx" / f"{name}.mp3"
    if not path.exists():
        return None
    try:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                             capture_output=True, check=True).stdout
        return np.frombuffer(raw, dtype=np.float32)
    except Exception:  # noqa: BLE001
        return None


def _mix_audio(narration: dict, total: float, events: list, out: Path) -> Path:
    import soundfile as sf
    voice, sr = sf.read(str(narration["path"]), dtype="float32")
    if voice.ndim > 1:
        voice = voice.mean(axis=1)
    mix = np.zeros(int(total * sr) + sr, dtype=np.float32)
    mix[:len(voice)] += voice[:len(mix)]
    cache = {}
    for event in events:
        # Optional fourth item limits SFX duration to the visual beat.
        # The existing (time, name, volume) production events remain unchanged.
        t, name, vol = event[:3]
        clip_seconds = event[3] if len(event) >= 4 else None
        if name not in cache:
            cache[name] = _load_sfx(name, sr)
        sound = cache[name]
        if sound is None:
            continue
        at = max(0, int(t * sr))
        room = max(0, len(mix) - at)
        if clip_seconds is not None:
            room = min(room, max(0, int(float(clip_seconds) * sr)))
        sound = sound[:room].copy()
        if clip_seconds is not None and len(sound):
            # Smooth last 45 ms to avoid an audible click on a truncated effect.
            fade = min(len(sound), int(sr * 0.045))
            sound[-fade:] *= np.linspace(1.0, 0.0, fade)
        mix[at:at + len(sound)] += sound * vol
    peak = float(np.max(np.abs(mix))) or 1.0
    if peak > 0.98:
        mix *= 0.98 / peak
    sf.write(str(out), mix[: int(total * sr)], sr)
    return out


# ================================================================ render

class VisualQAFailed(RuntimeError):
    """The finished explainer doesn't tell the story visually (visual_qa.json says why): never buffered."""


def _total(narration: dict) -> float:
    from render import tail_for
    return narration["duration"] + tail_for(narration["duration"])


def render(story: dict, narration: dict, segs: list[dict], workdir: Path, img_dir: Path | None = None):
    """PIL frames -> ffmpeg (4.5 Mbps) + narration/SFX mix, then the optional Remotion editorial pass.
    Returns (mp4, renderer): the renderer's frame_log / used_assets feed the visual QA."""
    total = _total(narration)
    r = Renderer(story, narration, segs, img_dir)
    events = []
    last_whoosh, last_click = -100.0, -100.0
    for k, seg in enumerate(segs):
        shot = seg["shot"]
        at = float(seg["start"])
        if k and shot["type"] == "graphic" and segs[k - 1]["shot"]["type"] != "graphic" and at - last_whoosh >= 5.0:
            events.append((max(0.0, at - 0.12), "whoosh", 0.18, 0.6))
            last_whoosh = at
        if shot.get("template") in ("date_stamp", "evidence", "missing") and at - last_click >= 3.5:
            events.append((at + 0.35, "ui_click", 0.35, 0.4))
            last_click = at
    t_true, t_title = opener_length(story)
    if t_true:
        events.append((0.18, "ui_click", 0.55))
    if t_title and t_true - last_whoosh >= 5.0:
        events.append((max(0.0, t_true - 0.1), "whoosh", 0.2))
    audio = _mix_audio(narration, total, events, workdir / "explainer_audio.wav")
    out = workdir / "explainer.mp4"
    n = int(round(total * FPS))
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
           "-i", "-", "-i", str(audio), "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast",
           "-b:v", "4500k", "-maxrate", "6500k", "-bufsize", "9000k", "-pix_fmt", "yuv420p", "-c:a", "aac",
           "-b:a", "192k", "-ar", "48000", "-shortest", "-movflags", "+faststart", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    import time
    t0 = time.time()
    try:
        for i in range(n):
            proc.stdin.write(r.frame_at(i / FPS).convert("RGB").tobytes())
            if i and i % 300 == 0:
                log(f"Explainer render: {i}/{n} frames ({time.time() - t0:.0f}s)")
    finally:
        proc.stdin.close()
        proc.wait()
    if proc.returncode or not out.exists():
        raise RuntimeError(f"explainer encode failed (ffmpeg exit {proc.returncode})")
    counts = {}
    for s in segs:
        counts[s["shot"]["type"]] = counts.get(s["shot"]["type"], 0) + 1
    secs = {}
    for s in segs:
        sh = s["shot"]
        key = f"image:{Path(sh['file']).name}:{sh.get('crop')}" if sh["type"] == "image" else f"{sh['type']}:{s['start']:.1f}"
        secs[key] = secs.get(key, 0.0) + s["end"] - s["start"]
    top = max(secs, key=secs.get)
    story["_visuals"] = {"distinct": len(secs), "longest_s": round(secs[top], 1),
                         "longest_share": round(secs[top] / total, 3), "longest_name": top}
    lens = [s["end"] - s["start"] for s in segs]
    story["explainer_character_assets"] = sorted(r.used_assets)
    story["explainer_render"] = {"segments": len(segs), "counts": counts, "shot_len_min": round(min(lens), 2),
                                 "shot_len_max": round(max(lens), 2), "shot_len_avg": round(sum(lens) / len(lens), 2),
                                 "render_seconds": round(time.time() - t0), "frames": n}
    log(f"Explainer render: {len(segs)} shots {counts}, {min(lens):.1f}-{max(lens):.1f}s (avg "
        f"{sum(lens) / len(lens):.1f}s), {n} frames in {time.time() - t0:.0f}s")
    if CONFIG.get("remotion_polish", False):
        from remotion_post import polish
        out = polish(out, workdir / "explainer_polished.mp4", segs, narration, FPS, n)
        story["explainer_render"]["remotion_polish"] = True
    return out, r


# ================================================================ visual QA, shot manifest, provenance

def _license_valid(meta: dict) -> str | None:
    """None if the external asset's recorded licence allows reuse in a monetized video, else why not."""
    import media
    src = meta.get("source")
    lic = meta.get("license") or ""
    if not meta.get("url"):
        return "no source URL"
    if src == "wikimedia":
        return None if media.license_ok(lic) else f"Wikimedia licence '{lic}' not allowed"
    if src == "loc":
        return None if media.loc_rights_ok(meta.get("rights") or lic) else "LOC rights not cleared"
    if src == "openverse":
        return None if re.match(r"(public domain mark|cc0|cc by( \d(\.\d)?)?)$", lic.lower()) else \
            f"Openverse licence '{lic}' not allowed"
    if src == "smithsonian":
        return None if lic.upper() == "CC0" else "Smithsonian item is not CC0"
    if src == "pexels":
        return None if lic == "Pexels License" else "unknown Pexels licence"
    if src == "pixabay":
        return None if lic == "Pixabay Content License" else "unknown Pixabay licence"
    return f"unknown provider '{src}'"


def provenance_of(path: str) -> dict:
    """Where a picture came from: real media sidecar (.json), asset library (.reuse.json), AI (.ai.json), or a
    virtual crop (.origin) of one of those. Always has filename + sha256."""
    import hashlib
    p = Path(path)
    out = {"file": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else ""}
    origin = p.with_suffix(".origin")
    if origin.exists():
        src = p.with_name(origin.read_text().strip())
        out["virtual_crop_of"] = src.name
        p = src if src.exists() else p
    if p.with_suffix(".json").exists():
        meta = json.loads(p.with_suffix(".json").read_text())
        kind = {"real_photo": "archival", "archive_print": "archival", "stock_video": "stock"}.get(meta.get("type"),
                                                                                                   "stock")
        out.update({"kind": kind, "provider": meta.get("source"), "url": meta.get("url"), "asset_id": meta.get("id"),
                    "creator": meta.get("author"), "license": meta.get("license"),
                    "license_url": meta.get("license_url"), "rights": meta.get("rights"), "query": meta.get("query"),
                    "title": meta.get("title"), "media": meta.get("kind"), "qa": meta.get("qa"),
                    "license_problem": _license_valid(meta)})
    elif p.with_suffix(".reuse.json").exists():
        meta = json.loads(p.with_suffix(".reuse.json").read_text())
        out.update({"kind": "library", "provider": "asset library", "asset_id": meta.get("asset"),
                    "license": meta.get("license") or "library asset (recorded at first use)"})
    elif p.with_name(p.stem + ".ai.json").exists():
        meta = json.loads(p.with_name(p.stem + ".ai.json").read_text())
        out.update({"kind": "ai_reconstruction", "provider": meta.get("provider") or "ai", "prompt": meta.get("prompt"),
                    "license": "AI-generated for Night Files (illustration, not historical evidence)"})
    else:
        out.update({"kind": "unknown", "license_problem": "no provenance record"})
    return out


def _rail_in_video(video: Path, n: int = 5) -> int:
    """Rendered-output check: in how many sampled frames a thin full-width horizontal rail sits in the top band
    (the removed Remotion progress bar was 3 px at y 93, x 70-906)."""
    from common import media_duration
    try:
        dur = media_duration(video)
    except Exception:  # noqa: BLE001
        return 0
    hits = 0
    for k in range(n):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{dur * (k + 1) / (n + 1):.2f}", "-i", str(video),
                              "-frames:v", "1", "-vf", "crop=840:40:80:74,format=gray", "-f", "rawvideo", "-"],
                             capture_output=True).stdout
        if len(raw) < 840 * 40:
            continue
        a = np.frombuffer(raw[:840 * 40], dtype=np.uint8).reshape(40, 840).astype(float)
        rows = a.mean(axis=1)
        flat = a.std(axis=1)
        for y in range(2, 38):
            if flat[y] < 7 and abs(rows[y] - (rows[y - 2] + rows[y + 2]) / 2) > 9:
                hits += 1
                break
    return hits


def visual_qa(story: dict, segs: list[dict], ren: "Renderer", video: Path | None, total: float) -> dict:
    """Hard checks on the FINAL shot list and the rendered output (frame log of the encoder + sampled frames).
    Returns the machine-readable report; report["failures"] empty = pass."""
    import sprites
    fails, exceptions, per_scene = [], [], []
    body = [s for s in segs if s["shot"]["type"] not in ("opener", "opener_title")]
    dur = lambda s: s["end"] - s["start"]  # noqa: E731
    secs = {"image": 0.0, "graphic": 0.0, "host": 0.0, "opener": 0.0}
    for s in segs:
        k = "opener" if s["shot"]["type"].startswith("opener") else s["shot"]["type"]
        secs[k] = secs.get(k, 0.0) + dur(s)
    share = {k: round(v / total, 3) for k, v in secs.items()}
    max_share = float(CONFIG.get("explainer_host_max_share", 0.15))
    max_host = float(CONFIG.get("explainer_host_max_seconds", 2.0))
    if share["host"] > max_share + 1e-6:
        fails.append(f"character runtime {share['host']:.0%} > {max_share:.0%}")
    frames = sum(ren.frame_log.values()) or 1
    if ren.frame_log["host"] / frames > max_share + 0.005:
        fails.append(f"rendered character frames {ren.frame_log['host'] / frames:.0%} > {max_share:.0%}")
    if ren.frame_log.get("end_card"):
        fails.append("a promotional end card was rendered")
    for a, b in zip(body, body[1:]):
        if a["shot"]["type"] == b["shot"]["type"] == "host":
            fails.append(f"consecutive character shots at {a['start']:.1f}s")
    for s in body:
        if s["shot"]["type"] == "host" and dur(s) > max_host + 0.05:
            fails.append(f"character shot of {dur(s):.1f}s at {s['start']:.1f}s (max {max_host:.0f}s)")
        if dur(s) > SHOT_MAX + 0.05 and s is not segs[-1]:
            fails.append(f"{s['shot']['type']} held {dur(s):.1f}s at {s['start']:.1f}s (max {SHOT_MAX:g} s)")
    by_scene = {}
    for s in body:
        by_scene.setdefault(s["scene"], []).append(s)
    for i, sc in enumerate(story["scenes"]):
        mine = by_scene.get(i, [])
        imgs = [s for s in mine if s["shot"]["type"] == "image"]
        own = [s for s in imgs if Path(s["shot"]["file"]).name.startswith(f"scene_{i:02d}")]
        grs = [s for s in mine if s["shot"]["type"] == "graphic"]
        if mine and not own:
            fails.append(f"scene {i + 1}: no narration-matched picture of its own")
        if any(not Path(s["shot"]["file"]).name.startswith(f"scene_{i:02d}") for s in imgs):
            fails.append(f"scene {i + 1}: shows another scene's picture (generic fallback)")
        for s in imgs:
            if not Path(s["shot"]["file"]).exists() or not valid_image(Path(s["shot"]["file"])):
                fails.append(f"scene {i + 1}: picture {Path(s['shot']['file']).name} missing or corrupt")
        # Do not require a graphic in every scene; only factual, purposeful graphics are valid.
        for g in grs:
            p = graphic_problem(story, i, g["shot"]) if g["shot"].get("template") != "closing" else None
            if p:
                fails.append(f"scene {i + 1}: graphic {g['shot']['template']}: {p}")
            if g["shot"].get("exception"):
                exceptions.append(f"scene {i + 1}: {g['shot']['exception']} ({g['shot']['fields'].get('text')})")
        per_scene.append({
            "scene": i + 1, "narration": sc.get("narration", ""),
            "pictures": [{"file": Path(s["shot"]["file"]).name, "crop": s["shot"].get("crop"),
                          "shot_prompt": _prompt_of(story, i, Path(s["shot"]["file"]).stem[-1])
                          if Path(s["shot"]["file"]).stem[-1] in "abcd" else "",
                          "source": provenance_of(s["shot"]["file"]).get("kind")} for s in imgs],
            "graphics": [{"template": g["shot"]["template"], "fields": g["shot"].get("fields"),
                          "auto": bool(g["shot"].get("auto"))} for g in grs],
            "host": [s["shot"].get("expression") for s in mine if s["shot"]["type"] == "host"]})
    prov = {}
    for s in body:
        if s["shot"]["type"] == "image" and s["shot"]["file"] not in prov:
            prov[s["shot"]["file"]] = provenance_of(s["shot"]["file"])
    for p in prov.values():
        if p.get("license_problem"):
            fails.append(f"{p['file']}: {p['license_problem']}")
    approved = {r["id"] for r in sprites.approved_registry().get("approved", [])}
    bad = sorted(set(ren.used_assets) - approved)
    if bad:
        fails.append(f"unapproved character assets: {bad}")
    rail = _rail_in_video(video) if video and Path(video).exists() else 0
    if rail >= 3:
        fails.append(f"a top progress rail is visible in {rail} sampled frames")
    if (ROOT / "remotion" / "src" / "polish.jsx").exists() and \
            "<TimelineRail" in (ROOT / "remotion" / "src" / "polish.jsx").read_text():
        fails.append("Remotion polish still draws the progress rail")
    kinds = [p.get("kind") for p in prov.values()]
    providers = [p.get("provider") for p in prov.values()]
    ai_prov = story.get("_shot_provider") or {}
    rejected = len([f for f in (ren.img_dir.glob("scene_*.rejected*.png") if ren.img_dir else [])])
    ai_ok = sum(1 for v in ai_prov.values() if v in ("cloudflare", "hf_space", "local_sd", "nvidia", "modelscope",
                                                    "pollinations"))
    report = {
        "story_id": story.get("story_id"), "title": story.get("title"), "mode": story.get("mode"),
        "runtime_s": round(total, 2), "segments": len(segs),
        "shots": {k: sum(1 for s in segs if (s["shot"]["type"].startswith("opener") and k == "opener")
                         or s["shot"]["type"] == k) for k in ("image", "graphic", "host", "opener")},
        "runtime_share": share, "rendered_frames": ren.frame_log,
        "ai_images": {"requests": ai_ok + rejected, "successful": ai_ok, "rejected": rejected,
                      "by_provider": {p: list(ai_prov.values()).count(p) for p in set(ai_prov.values())},
                      "cloudflare_neurons": round(float(__import__("images")._STATE.get("cf_neurons") or 0))},
        "media_used": {"pexels": providers.count("pexels"), "pixabay": providers.count("pixabay"),
                       "wikimedia": providers.count("wikimedia"), "loc": providers.count("loc"),
                       "openverse": providers.count("openverse"), "smithsonian": providers.count("smithsonian"),
                       "library_reused": kinds.count("library"), "archival": kinds.count("archival"),
                       "stock": kinds.count("stock"), "ai_reconstruction": kinds.count("ai_reconstruction")},
        "character_assets": sorted(ren.used_assets), "per_scene": per_scene,
        "provenance": list(prov.values()), "failures": fails, "exceptions": exceptions,
        "fresh_images": (story.get("explainer_images") or {}).get("fresh_images"),
    }
    return report


def shot_manifest(segs: list[dict]) -> list[dict]:
    out = []
    for k, s in enumerate(segs):
        sh = s["shot"]
        row = {"n": k + 1, "start": round(s["start"], 2), "end": round(s["end"], 2),
               "seconds": round(s["end"] - s["start"], 2), "scene": s["scene"] + 1, "type": sh["type"]}
        if sh["type"] == "image":
            row.update(file=Path(sh["file"]).name, crop=sh.get("crop"))
        elif sh["type"] == "graphic":
            row.update(template=sh["template"], fields=sh.get("fields"), auto=bool(sh.get("auto")))
        elif sh["type"] == "host":
            row.update(expression=sh.get("expression"))
        out.append(row)
    return out


def write_reports(workdir: Path, report: dict, segs: list[dict]) -> None:
    (workdir / "visual_qa.json").write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str))
    (workdir / "shot_manifest.json").write_text(json.dumps(shot_manifest(segs), indent=1, ensure_ascii=False,
                                                           default=str))
    (workdir / "provenance.json").write_text(json.dumps(report["provenance"], indent=1, ensure_ascii=False,
                                                        default=str))


def build(story: dict, narration: dict, img_dir: Path, workdir: Path) -> Path:
    """approved-asset check -> the story's own pictures (story_images) -> graphics (plan_graphics; saved in the
    checkpoint, same narration = no new LLM call) -> shot sequence -> render -> visual QA (hard). Music is added
    after by main.py like for classic."""
    import hashlib
    import checkpoint
    import sprites
    sprites.require_all()  # missing / changed approved art: fail by asset ID, never substitute
    scene_images = story_images(story, img_dir)
    key = hashlib.sha1(json.dumps([w["word"] for w in narration["words"]]).encode()).hexdigest()[:16]
    saved = img_dir / "explainer_storyboard.json"
    graphics = None
    try:
        old = json.loads(saved.read_text())
        if old.get("key") == key and old.get("version") == 2:
            graphics = old["graphics"]
            log("Explainer graphics: reused from the earlier try (same narration)")
    except (OSError, ValueError, KeyError):
        graphics = None
    if graphics is None:
        graphics = plan_graphics(story, narration)
        checkpoint.write_atomic(saved, json.dumps({"key": key, "version": 2, "graphics": graphics},
                                                  ensure_ascii=False, default=str))
        checkpoint.register_image(saved, stage="shot_list")
    total = _total(narration)
    segs = sequence(story, narration, scene_images, graphics, total)
    story["render_style"] = "explainer"
    video, ren = render(story, narration, segs, workdir, img_dir)
    report = visual_qa(story, segs, ren, video, total)
    write_reports(workdir, report, segs)
    story["explainer_plan"] = {"shots": report["shots"], "runtime_share": report["runtime_share"],
                               "media_used": report["media_used"]}
    log(f"Visual QA: shots {report['shots']}, runtime {report['runtime_share']}, media {report['media_used']}, "
        f"AI {report['ai_images']}" + (f"; exceptions: {report['exceptions']}" if report["exceptions"] else ""))
    if report["failures"]:
        raise VisualQAFailed("; ".join(report["failures"])[:900])
    return video


def frame_sheet(video: Path, dest: Path, n: int = 8) -> Path | None:
    """n frames spread over the video (end card excluded), labelled with their time: the review sheet."""
    import cutout
    from common import media_duration
    dur = media_duration(video)
    tmp = dest.parent / "sheet_frames"
    tmp.mkdir(parents=True, exist_ok=True)
    items = []
    for k in range(n):
        t = 0.3 + (dur - 4.5) * k / max(1, n - 1)
        f = tmp / f"f{k}.png"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
                        str(f)], check=False)
        items.append((f, f"{t:.1f}s"))
    return cutout.sheet(items, dest, "frames", cols=4, cell=(270, 480))
