"""Render style "explainer" (default for every mode): the story is told with STORY PICTURES, explained by graphics,
with the approved host as occasional B-roll (owner, Oct 24):
  story picture -> explanatory graphic -> second story picture -> (rare host reaction), a new visual every 1.5-3 s.
(a) story pictures: each scene's own image_prompt / image_query shots, through the existing media chain (asset
    library when fresh_images is OFF, licensed archive photos / prints and Pexels / Pixabay photos + clips, then AI
    images: images.generate_images, same budget / QA / fallbacks as classic). Never another scene's picture.
(b) graphics: noir.py templates (evidence, map_route, fact, quote, missing, closing...), LLM-picked or
    built from the narration + fact ledger; every word / number on screen is said in that scene (graphic_problem).
(c) the host: ONLY the approved M01-M04 / F01-F22 art (sprites.py): max 1 shot per scene, never in two scenes in a
    row, <= 2 s, <= 15% of the runtime, mostly F-face reactions over a blurred crop of the scene's picture.
No progress rail, no corner label, no end card: the video ends on the closing graphic / last picture.

Flow (main.py): adapt(story) -> fit_duration -> build(): story_images -> plan_graphics -> sequence -> render ->
visual_qa (hard: visual_qa.json, shot_manifest.json, provenance.json in the workdir). Music is added after.
"""
import json
import math
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
CAP_Y = 1205  # Pillow captions (only when Remotion polish is off): above the TikTok / Shorts caption + button UI


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
    out["accent"] = _meaningful_accent(out["accent"], [out.get(k, "") for k in GRAPHIC_TEXT.get(tpl, ())])
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


def _card_text(g: dict) -> str:
    f = g.get("fields") or {}
    return re.sub(r"\W+", " ", " ".join(str(f.get(k) or "") for k in ("text", "left", "right", "label"))).strip().lower()


def _meaningful_accent(accent: str, texts: list[str]) -> str:
    """An accent only on a word that is ON the graphic and carries meaning (word_score >= 1): never
    'mysterious', 'wearing' or a filler verb."""
    a = str(accent or "").strip()
    if not a or len(a.split()) != 1 or word_score(a) < 1.0:
        return ""
    return a if any(re.search(rf"\b{re.escape(a)}\b", str(t), re.IGNORECASE) for t in texts if t) else ""


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
- Never a date / year card: spoken dates get their own animated year reel over the picture automatically.
- Pick the graphic that EXPLAINS the beat: map_route only when the scene names 2+ places
  someone travels between, evidence for a clue / object / record / name, quote for words someone said, missing when
  someone vanishes, fact for a number said, compare for two explanations, closing only for the final question.
- Follow Walter Murch's Rule of Six priority for editorial decisions: EMOTION first, STORY second,
  then RHYTHM, EYE TRACE, 2D SCREEN PLANE, and 3D SPACE. Murch's illustrative weights are 51/23/10/7/5/4,
  but they are NOT a numeric grading formula. Only create a graphic if it clarifies an important story beat
  or strengthens the intended feeling; use a calm image or held shot where another card would interrupt suspense.
- Graphic emphasis MUST be a meaningful, contiguous expression from the narration, not unrelated keywords.
  Underline or accent only the key choice, consequence, evidence or reveal. Don't overuse transitions, whooshes,
  stamps, giant text or repeated templates. Keep a clear focal point and respect captions in vertical framing.
- Think about how the gaze moves from the preceding story image to this graphic and from the graphic back to
  the next story image. Maintain comprehensible screen direction and subject position when possible; preserving
  story emotion is more important than mechanically matching geometry.
- No people drawn, nothing occult, no gore.
"""

PLAN_TEMPLATES = ("evidence", "map_route", "fact", "quote", "connections", "compare", "missing",
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
_MESSAGE = re.compile(r"\b(text(?:ed|s)?|messag\w*|notification|dm|sms|phone (?:lit|buzz\w*|screen))\b",
                      re.IGNORECASE)
_QUOTE = re.compile(r"(?:^|[\s,:(])[\"“'‘](.{6,120}?)[\"”'’](?=[\s.,!?;:)]|$)")
_COMMON = set("during born working declared constructing after before when while once then later her his their "
              "you every each this that these those".split())
_GEO = re.compile(r"\b(ocean|sea|atlantic|pacific|river|island|lake|bay|gulf|mountains?|desert|coast)\b", re.IGNORECASE)
_PROPER_RX = re.compile(r"\b((?:[A-Z][a-z]+)(?:\s+(?:[A-Z][a-z]+|of|the|de|van))*\s+[A-Z][a-z]+|[A-Z][a-z]{3,})\b")


_MONTH_DAY = re.compile(
    r"\b(?P<month>january|february|march|april|may|june|july|august|september|october|november|december)"
    r"\s+(?:the\s+)?(?P<day>[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?\b|"
    r"\b(?P<word_month>january|february|march|april|may|june|july|august|september|october|november|december)"
    r"\s+(?:the\s+)?(?P<word_day>first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|"
    r"eleventh|twelfth|thirteenth|fourteenth|fifteenth|sixteenth|seventeenth|eighteenth|nineteenth|"
    r"twentieth|twenty[- ]first|twenty[- ]second|twenty[- ]third|twenty[- ]fourth|twenty[- ]fifth|"
    r"twenty[- ]sixth|twenty[- ]seventh|twenty[- ]eighth|twenty[- ]ninth|thirtieth|thirty[- ]first)\b",
    re.IGNORECASE)
_SPOKEN_DAYS = dict(zip(
    ("first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth "
     "fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth twentieth").split(), range(1, 21)))
_SPOKEN_DAYS.update({f"twenty-{w}": 20 + n for w, n in list(_SPOKEN_DAYS.items())[:9]})
_SPOKEN_DAYS.update({"thirtieth": 30, "thirty-first": 31})


def _tok(w: str) -> str:
    return re.sub(r"[^a-z0-9-]", "", str(w).lower())


def _find_tokens(toks: list[str], seq: list[str], frm: int = 0) -> int:
    for k in range(frm, len(toks) - len(seq) + 1):
        if toks[k:k + len(seq)] == seq:
            return k
    return -1


def date_mentions(story: dict, narration: dict) -> list[dict]:
    """Every spoken year / calendar date, in spoken order, from the narration's word timings: {"word": index of
    the first spoken word of the date (the reel lands on its start), "kind": "year" | "day", "target", "label"
    (the full date when a month + day is said with it), "kicker" (its fact-ledger key, else WHEN)}. A true story's
    date must be in the fact ledger (never a guessed year); each year / date is shown once."""
    import spoken_numbers as nums
    words = narration["words"]
    toks = [_tok(w["word"]) for w in words]
    ledger = _ledger_text(story)
    true = bool(story.get("true_story"))
    out, seen = [], set()
    for i, sc in enumerate(story["scenes"]):
        idx = [k for k, w in enumerate(words) if w.get("scene") == i]
        if not idx:
            continue
        narr = sc.get("narration", "")
        lo = idx[0]
        stoks = toks[lo:idx[-1] + 1]
        for y in sorted(v for v in nums.values(narr) if 1000 <= v <= 2100 and float(v).is_integer()):
            y = int(y)
            pos = min((p for p in (_find_tokens(stoks, [str(y)]), _find_tokens(stoks, nums.year(y).split()),
                                   _find_tokens(stoks, nums.year(y).replace("-", " ").split())) if p >= 0),
                      default=-1)
            if pos < 0 or ("year", y) in seen or (true and ledger and str(y) not in ledger):
                continue
            label = ""
            before = " ".join(stoks[max(0, pos - 4):pos])
            m = _MONTH_DAY.search(before) if before else None
            if m:
                raw = m.group("day") or m.group("word_day") or ""
                day = int(raw) if raw.isdigit() else _SPOKEN_DAYS.get(raw.lower().replace(" ", "-"))
                month = m.group("month") or m.group("word_month")
                if day and month:
                    label = f"{month.upper()} {day}"
                    pos = max(0, pos - len(m.group(0).split()))  # the reel lands as the date starts
            seen.add(("year", y))
            kick = next((_kicker(k) for k, v in _ledger_pairs(story) if str(y) in v), "") or "WHEN"
            out.append({"word": lo + pos, "kind": "year", "target": y, "label": label, "kicker": kick, "scene": i})
        for m in _MONTH_DAY.finditer(narr):
            raw = m.group("day") or m.group("word_day") or ""
            day = int(raw) if raw.isdigit() else _SPOKEN_DAYS.get(raw.lower().replace(" ", "-"))
            month = m.group("month") or m.group("word_month")
            if not day or not month or ("day", month.lower(), day) in seen:
                continue
            seq = [_tok(x) for x in m.group(0).split()]
            pos = _find_tokens(stoks, seq)
            if pos < 0 or any(o["scene"] == i and o["label"] and lo <= o["word"] <= lo + pos + len(seq)
                              for o in out):
                continue  # already part of a year reel ("July second, nineteen thirty-seven")
            if true and ledger and m.group(0).lower() not in ledger.lower() and \
                    f"{month} {day}".lower() not in ledger.lower():
                continue
            seen.add(("day", month.lower(), day))
            out.append({"word": lo + pos, "kind": "day", "target": day, "label": month.upper(), "kicker": "WHEN",
                        "scene": i})
    out.sort(key=lambda d: d["word"])
    return out


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
    opts = choice_options(narr)
    if opts:  # a binary choice the narration offers: the approved P08 viewer surrogate holds both options
        out.append({"type": "graphic", "at": None, "template": "choice", "auto": True,
                    "fields": {"left": opts[0], "right": opts[1]}})
    msg = _QUOTE.search(narr)
    if msg and _MESSAGE.search(narr) and len(msg.group(1).split()) >= 2:  # a stated message on a phone screen
        sender = re.search(r"\bfrom ([A-Z][a-z]+)\b", narr)
        out.append({"type": "graphic", "at": None, "template": "phone", "auto": True,
                    "fields": {"text": msg.group(1).strip(), "from": sender.group(1) if sender else ""}})
    if _VANISH.search(narr):
        word = next((w for w in ("VANISHED", "DISAPPEARED", "MISSING", "GONE") if w.lower()[:6] in narr.lower()), "")
        places = [(l.get("name") or "") for l in story.get("locations") or []]
        place = next((m.group(1) for m in _PROPER_RX.finditer(narr) if m.start() > 0 and narr[m.start() - 2] not in ".!?"
                      and (_GEO.search(m.group(1)) or any(m.group(1) in pl for pl in places))), "")
        geo = re.search(r"\bthe\s+((?:[A-Z][a-z]+\s+)*(?:Ocean|Sea|Atlantic|Pacific|River|Island|Lake|Bay))\b", narr)
        out.append({"type": "graphic", "at": None, "template": "missing", "auto": True,
                    "fields": {"subject": "", "word": word, "last_seen": (geo.group(1) if geo else place)[:28]}})
    q = _QUOTE.search(narr)
    if q and len(q.group(1).split()) >= 3 and not any(g["template"] == "phone" for g in out):
        who = ""
        for c in story.get("characters") or []:  # the part of the name this scene says ("Amelia")
            said_parts = [w for w in (c.get("name") or "").split() if re.search(rf"\b{re.escape(w)}\b", narr)]
            if said_parts:
                who = " ".join(said_parts)
                break
        out.append({"type": "graphic", "at": None, "template": "quote", "auto": True,
                    "fields": {"text": q.group(1).strip(), "by": who}})
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


def _impact_fallback(story: dict, i: int) -> dict | None:
    """No factual graphic fits this beat: the beat's strongest COMPLETE phrases (key_phrases, at most two,
    in spoken order) as an impact card, the payoff word accented. None when no phrase would add meaning: a clean
    story picture beats a card of random words (the old version glued the two longest words: "CHOOSE COVERED")."""
    phrases = [p for p in key_phrases(story["scenes"][i].get("narration", ""), limit=2, min_score=3.0)
               if len(p["text"].split()) >= 2 or re.match(r"\d", p["text"]) or p["first"][:1].isupper()
               and p["first"].lower() not in FUNCTION]  # one generic word ("ENDS", "FATE") is not a card
    if not phrases or all(len(p["text"].split()) < 2 for p in phrases) and not re.match(r"\d", phrases[0]["text"]):
        return None
    payoff = max(phrases, key=lambda p: word_score(p["accent"]))
    return {"type": "graphic", "at": None, "template": "impact", "auto": True,
            "fields": {"lines": [p["text"] for p in phrases], "text": " ".join(p["text"] for p in phrases),
                       "accent": payoff["accent"]}}


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
    base = {"cast": {}, "dates": 0}
    out = []
    used_texts = set()  # the same card text never twice in one video ("AKA MANTO" name card in scenes 2 and 7)
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
            v = _valid_graphic(g, at, sctx)
            if v:
                v["at"] = at
                if v["template"] == "missing":  # nobody is drawn: the host never stands in for a real person
                    v["fields"]["subject"] = ""
                picks.append(v)
        picks += _auto_graphics(story, i, sctx)
        if not true:  # a legend / fiction: the beat's own strong phrase beats a generic ledger card
            imp = _impact_fallback(story, i)
            if imp and max(word_score(w) for w in imp["fields"]["text"].split()) >= 2.5 \
                    and not any(g["template"] in ("choice", "phone", "quote") for g in picks):
                picks = [imp] + [g for g in picks if g["template"] != "evidence" or not g.get("auto")]
        seen, uniq = set(), []
        for g in picks:
            key = (g["template"], json.dumps(g["fields"], sort_keys=True, default=str))
            shown = _card_text(g)
            if key not in seen and shown not in used_texts and graphic_problem(story, i, g) is None:
                seen.add(key)
                uniq.append(g)
        if not uniq:
            imp = _impact_fallback(story, i)
            uniq = [imp] if imp and graphic_problem(story, i, imp) is None and _card_text(imp) not in used_texts else []
        used_texts.update(_card_text(g) for g in uniq[:1] if _card_text(g))  # the card this scene will show
        out.append(uniq)
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
    if tpl == "date_stamp":  # retired: dates are year reels over the picture (plan_effects), never a card
        return "date cards are retired (year reel overlay)"
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
    elif tpl == "choice":
        if not (f.get("left") and f.get("right")):
            return "choice graphic without two options"
        texts += [f.get("left"), f.get("right")]
    elif tpl == "impact":
        texts += list(f.get("lines") or [])
    if tpl == "phone":
        texts.append(f.get("from") or "")
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


# ================================================================ editorial intelligence (owner, Oct 25)
# The ONE universal editor's judgement, story-agnostic and deterministic (no LLM call, nothing for one legend):
#   key_phrases      complete meaningful phrases ("CHOOSE RED", "COVERED IN BLOOD"), never two unrelated words glued
#                    together ("CHOOSE COVERED"); the accent is the payoff word INSIDE its phrase
#   choice_options   a binary choice the narration really offers ("red or blue?") -> the P08 viewer surrogate
#   viewer_beat      choice / warning / decision / reaction beats aimed at the viewer (host mood)
#   plan_transitions cut / dissolve / slide / pop / swoosh per cut by context, with repetition avoidance
#   plan_motion      push / pan / pull / still for story pictures (stillness allowed)
#   event_sfx        sounds only for events the narration describes, timed to the word, rationed
#   caption_accents  the few spoken words the captions (Pillow + Remotion) may accent, never every word
# Priorities: docs/WALTER_MURCH_RULE_OF_SIX.md (emotion > story > rhythm > eye trace > 2D plane > 3D space).


# words that never start or end an on-screen phrase and never carry an accent
FUNCTION = set("""a an the of in on at to and or but is was were be been being am are it its it's his her hers their
theirs this that these those you your you'll you're you'd yours he she they them him we us our i me my mine with
from by for as if then than so because while when where who whom whose which what there here into onto over under
about up down out off just also too very really quite will would shall should can could may might must do does did
done has have had having not no nor one ones some any each every all both either neither own same such only own
says said say tells told goes went comes came gets got like let lets how why ever always being become became
becomes grow grows grew making make makes made hear hears heard see sees saw watch watches watched witness witnessed
follow follows listen listens during toward towards offering offer offers try tries trying asking ask asks keep keeps
another other""".split())
# generic adjectives / filler verbs: weak on screen ("MYSTERIOUS", "WEARING", "APPEARS")
WEAK = set("""mysterious strange unsettling eerie creepy scary terrifying frightening unknown certain famous little
big small old new wearing appears appear appeared seems seem seemed story legend legends version versions people
someone something somebody thing things way ways time times figure place kind sort lot bit really actually
especially simply suddenly slowly quickly""".split())
THREAT = set("""blood bloody bleed bleeding drained drain dead death die dies died dying kill killed kills killer
murder murdered body bodies corpse grave graves buried bones skull vanish vanished vanishes disappear disappeared
missing gone trapped cursed curse scream screamed screams drown drowned drowning choke choked strangled poison
poisoned fire burned burning knife blade shot severed throat neck heart eyes face mask fate end ends ending never
nobody alone dark darkness monster demon ghost spirit shadow""".split())
CHOICE = set("""choose chose choice choices pick picked decide decided decision refuse refused refusal answer answered
answering select option options either whether which""".split())
CONTRAST = set("but only never nobody nothing none don't doesn't didn't won't can't isn't wasn't".split())
COLOURS = {"red": (200, 30, 45), "blue": (40, 90, 200), "yellow": (230, 190, 40), "green": (40, 150, 80),
           "black": (20, 20, 24), "white": (235, 235, 235), "purple": (120, 50, 160), "white's": (235, 235, 235)}
# attribution / framing that should not be on screen: "the legend says you'll be covered in blood" -> the payoff
ATTRIBUTION = re.compile(
    r"^(?:(?:and|but|so|because|then|yet|or)\s+)?(?:(?:the\s+)?(?:legend|story|stories|tale|myth|rumou?r)s?\s+"
    r"(?:says?|goes|claims?|tells?)(?:\s+that)?\s+|(?:people|they|some|many|locals|villagers)\s+(?:say|said|believe|"
    r"claim)(?:\s+that)?\s+|it\s+is\s+said(?:\s+that)?\s+|according\s+to\s+\w+(?:\s+\w+)?\s+|in\s+some\s+versions\s+)?"
    r"(?:you(?:'ll| will| would|'d)\s+be\s+|you(?:'re| are)\s+|you(?:'ll| will)\s+)?", re.IGNORECASE)
_WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*|\d[\d,.]*")


def _bare(w: str) -> str:
    return re.sub(r"[^a-z0-9']", "", w.lower().replace("’", "'"))


def word_score(w: str, prev: str = "") -> float:
    """How much a single spoken word matters on screen."""
    b = _bare(w)
    if not b or b in FUNCTION:
        return 0.0
    if b in WEAK:
        return -1.0
    s = 0.5
    if b in THREAT:
        s = 3.0
    elif b in CHOICE:
        s = 2.0
    elif b in CONTRAST:
        s = 1.0
    elif b in COLOURS or _bare(prev) in CHOICE:  # the option itself ("choose RED")
        s = 2.5
    elif re.match(r"\d", b):
        s = 2.0
    if w[:1].isupper() and prev and not re.search(r"[.!?]$", prev):  # a name mid-sentence
        s = max(s, 2.0)
    return s


def clauses(text: str) -> list[str]:
    """Sentence -> clause pieces at punctuation, quotes and dashes (an on-screen phrase never crosses them)."""
    parts = re.split(r"[.!?;:,—–\"“”…()]+|\s-\s", text)
    return [p.strip() for p in parts if p and p.strip()]


def _trim(clause: str, option: bool = False) -> list[str]:
    """Attribution / framing and edge function words removed: 'and the legend says you'll be covered in blood'
    -> ['covered', 'in', 'blood']."""
    c = ATTRIBUTION.sub("", clause.strip(), count=1)
    words = _WORD.findall(c)
    while words and (_bare(words[0]) in FUNCTION or _bare(words[0]) in WEAK) and not _keep_edge(words[0]):
        words.pop(0)
    while words and (_bare(words[-1]) in FUNCTION or _bare(words[-1]) in WEAK or
                     (_keep_edge(words[-1]) and not (option and len(words) == 1))):
        words.pop()
    return words


def _keep_edge(w: str) -> bool:
    """A negation may OPEN a phrase ("DON'T PICK A COLOR"), never close one ("MANTO ISN'T")."""
    return _bare(w) in CONTRAST and _bare(w).endswith("n't")


def _candidates(words: list[str]):
    """Contiguous windows (1-4 words) of one trimmed clause whose edges are content words."""
    n = len(words)
    for i in range(n):
        if word_score(words[i]) <= 0 and not _keep_edge(words[i]):
            continue
        for j in range(i, min(n, i + 4)):
            if word_score(words[j], words[j - 1] if j else "") <= 0 or (j > i and _keep_edge(words[j])):
                continue
            yield i, j + 1


def key_phrases(text: str, limit: int = 2, min_score: float = 2.5) -> list[dict]:
    """The strongest complete phrases of a narration beat, in spoken order: [{"text", "accent", "score", "first"}].
    Each phrase comes from ONE clause (never two distant words glued together); "accent" is its payoff word.
    Empty when nothing on screen would add meaning (then a clean picture is better than an impact card)."""
    found = []
    sent_of = []
    for si, sentence in enumerate(re.split(r"(?<=[.!?…])\s+", text)):
        sent_of += [si] * len(clauses(sentence))
    for k, clause in enumerate(clauses(text)):
        words = _trim(clause)
        if not words:
            continue
        best = None
        whole = len(words) <= 4
        for i, j in _candidates(words):
            win = words[i:j]
            sc = [word_score(w, win[m - 1] if m else (words[i - 1] if i else "")) for m, w in enumerate(win)]
            if min(sc) < 0:
                continue  # a weak word inside the phrase ("MYSTERIOUS FIGURE") is not an accent-worthy beat
            # a complete short clause earns a bonus; generic words at the edges ("CENTER OF AKA MANTO") cost
            edges = 0.8 if len(win) > 1 and 0 < sc[0] <= 0.5 else 0.0  # a generic opening word
            if _bare(win[-1]) in CONTRAST and j < len(words):  # "...AND NEVER" left hanging before its verb
                edges += 1.5
            score = sum(sc) + (1.0 if (i, j) == (0, len(words)) and whole else 0.0) - 0.35 * max(0, len(win) - 3) \
                - edges
            if best is None or score > best[0] + 1e-9:
                best = (score, win, sc)
        if best and best[0] >= min_score:
            score, win, sc = best
            accent = win[max(range(len(win)), key=lambda m: (sc[m], m))]
            found.append({"text": " ".join(win).upper(), "accent": accent.upper(), "score": round(score, 2),
                          "first": win[0], "order": k, "sentence": sent_of[k] if k < len(sent_of) else k})
    if not found:
        return []
    best = max(found, key=lambda p: p["score"])
    # a second line only from the SAME sentence ("CHOOSE RED" / "COVERED IN BLOOD"): phrases of two different
    # sentences on one card read as one false statement ("FATE / ISN'T ALWAYS AN OPTION")
    same = sorted((p for p in found if p is not best and p["sentence"] == best["sentence"]),
                  key=lambda p: -p["score"])[:max(0, limit - 1)]
    return sorted([best] + same, key=lambda p: p["order"])


_OPTION = r"((?:[A-Za-z’'-]+\s+){0,2}?[A-Za-z’'-]+)"
CHOICE_RX = re.compile(r"(?:^|[\"“,:;]\s*|\b(?:choose|pick|select|between|either|whether|answer)\s+)" + _OPTION +
                       r"\s*,?\s+or\s+" + _OPTION + r"\s*(?=[?\"”.,!]|$)", re.IGNORECASE)


def choice_options(text: str) -> tuple[str, str] | None:
    """('RED', 'BLUE') when the narration offers a real either/or ('Red or blue?', 'open the door or don't'):
    both options short, said, and in a question / choice context. Never invented."""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        for m in CHOICE_RX.finditer(sentence):
            a, b = _trim(m.group(1), option=True), _trim(m.group(2), option=True)
            if not a or not b or len(a) > 3 or len(b) > 3:
                continue
            context = "?" in sentence or re.search(r"\b(choose|pick|choice|decide|either|whether|which)\b",
                                                   sentence, re.IGNORECASE)
            if not context:
                continue
            return " ".join(a).upper(), " ".join(b).upper()
    return None


_WARNING = re.compile(r"\b(don't|do not|never|if you (?:ever|hear|see)|whatever you do|stay away|run)\b",
                      re.IGNORECASE)
_DECISION = re.compile(r"\b(refuse\w*|walk away|decide\w*|chose|choose|pick|only one way|outsmart)\b", re.IGNORECASE)
_REACTION = re.compile(r"\b(imagine|what if|wonder|why|how could|would you)\b", re.IGNORECASE)


def viewer_beat(text: str) -> tuple[str, str] | None:
    """(kind, mood) when a beat speaks to the viewer: 'choice' (thinking), 'warning' (worried), 'decision'
    (serious: F19 'determined' grins, wrong for dread) or 'reaction' (curious). The mood names an approved host
    expression (sprites.FACES)."""
    if choice_options(text):
        return "choice", "thinking"
    if _WARNING.search(text) and re.search(r"\byou\b|^\s*don't|^\s*never", text, re.IGNORECASE):
        return "warning", "worried"
    if _DECISION.search(text):
        return "decision", "serious"
    if _REACTION.search(text):
        return "reaction", "curious"
    return None


# ---------------------------------------------------------------- transitions + motion

TIME_CUE = re.compile(r"\b(later|that night|years?|decades?|centur\w+|hours?|morning|dawn|dusk|meanwhile|"
                      r"long ago|once|since|by the time|slowly|fog|mist|dream\w*|memory|remember\w*|"
                      r"the story goes|the legend says|in some versions|they say)\b", re.IGNORECASE)
MOVE_CUE = re.compile(r"\b(ran|run|runs|running|walk\w*|fled|flee\w*|bolt\w*|rush\w*|drove|drive|travel\w*|"
                      r"cross\w*|chase\w*|toward|towards|follow\w*|route|journey\w*|escape\w*)\b", re.IGNORECASE)
SUDDEN = re.compile(r"\b(suddenly|burst\w*|slam\w*|snap\w*|strike\w*|struck|lunge\w*|grab\w*)\b", re.IGNORECASE)
POP_TEMPLATES = {"evidence", "fact", "missing", "phone", "photo_scan", "clock_stop"}
SLIDE_TEMPLATES = {"map_route", "connections", "filmstrip"}
CUT_TEMPLATES = {"impact", "quote", "choice", "closing", "compare", "shadow_reveal"}
EFFECTS = ("cut", "dissolve", "slide", "pop", "swoosh")


def _seg_text(seg: dict, words: list[dict]) -> str:
    return " ".join(w["word"] for w in words if seg["start"] - 0.05 <= w["start"] < seg["end"])


TIME_PASSAGE_CUE = re.compile(
    r"\b(?:years?|months?|weeks?|days?|hours?|decades?)\s+(?:earlier|later)\b|"
    r"\b(?:later|afterwards?|meanwhile|eventually|previously|flashback|back then|by the time)\b|"
    r"\b(?:the next|the following|the previous)\s+(?:morning|day|night|week|month|year)\b",
    re.IGNORECASE,
)


def plan_transitions(segs: list[dict], words: list[dict], max_swoosh: int = 2) -> list[str]:
    """Plan purposeful punctuation between shots; preserve max_swoosh only for caller compatibility.

    A hard cut is always the default, including graphics, locations, ideas and sudden beats.
    A short dissolve is allowed only at a NEW scene with explicit narrated passage of time; a whip pan (max 2 per
    video) only at a new scene whose narration jumps to another place ("meanwhile", "flew to", "miles away").
    Fade to black is reserved for a terminal outro, never a scene boundary.
    """
    out = []
    for k, seg in enumerate(segs):
        kind = (seg.get("shot") or {}).get("type")
        new_scene = k > 0 and seg.get("scene") != segs[k - 1].get("scene")
        text = _seg_text(seg, words) if new_scene else ""
        want = "dissolve" if kind == "image" and new_scene and TIME_PASSAGE_CUE.search(text) else "cut"
        if want == "dissolve" and out and out[-1] == "dissolve":
            want = "cut"
        if want == "cut" and kind == "image" and new_scene and WHIP_CUE.search(text) and out.count("whip") < 2 \
                and (not out or out[-1] != "whip"):
            want = "whip"
        out.append(want)
        seg["transition"] = want
    return out

REVEAL = re.compile(r"\b(reveal\w*|face|mask|eyes|blood|dead|body|grave|still|silence|waiting|watch\w*|stare\w*)\b",
                    re.IGNORECASE)


def plan_motion(segs: list[dict], words: list[dict]) -> list[str]:
    """Camera motion per story picture (seg['motion']): push / pan / pull, or 'still' on a reveal beat that should
    land without movement (never two stills in a row, never the same move twice in a row)."""
    out, last = [], ""
    cycle = ("push", "pan", "pull")
    n = 0
    for seg in segs:
        if (seg.get("shot") or {}).get("type") != "image":
            out.append("")
            continue
        text = _seg_text(seg, words)
        if REVEAL.search(text) and last != "still":
            m = "still"
        else:
            m = cycle[n % 3]
            n += 1
            if m == last:
                m = cycle[n % 3]
                n += 1
        seg["motion"] = m
        out.append(m)
        last = m
    return out


# ---------------------------------------------------------------- event-matched sound

# (event regex, sfx file in assets/sfx, volume) - only literal events; a mood is never a sound
SFX_EVENTS = [
    (r"\b(footsteps?|walk(?:ed|ing|s)?|stepp?(?:ed|ing)|ran|running|bolt(?:s|ed)?|fled|chas(?:ed|ing))\b", "footsteps_wood", 0.32),
    (r"\b(slam(?:s|med)?\s+shut|door\s+slam\w*|slammed)\b", "door_slam", 0.4),
    (r"\b(door\s+(?:creak\w*|open\w*|swung)|creak(?:s|ed|ing)?\s+open)\b", "door_creak", 0.35),
    (r"\b(unlock\w*|turned the key)\b", "door_unlock", 0.35),
    (r"\b(knock(?:s|ed|ing)?)\b", "knocking", 0.35),
    (r"\b(text(?:ed)?\s+(?:message|from)|a\s+(?:text|message)\s+(?:arrived|came|popped)|notification)\b",
     "phone_notification", 0.38),
    (r"\b(phone\s+(?:buzz\w*|vibrat\w*|rang|ring\w*)|buzz(?:ed|ing)\b)", "phone_buzz", 0.35),
    (r"\b(thunder\w*|lightning)\b", "thunder", 0.35),
    (r"\b(wind\s+(?:howl\w*|blew|blow\w*|whistl\w*)|gust\w*)\b", "wind", 0.3),
    (r"\b(clock\s+(?:tick\w*|struck|chimed)|ticking)\b", "clock_ticking", 0.3),
    (r"\b(whisper(?:s|ed|ing)?)\b", "whispers", 0.3),
    (r"\b(laugh(?:s|ed|ing)?|giggl\w*)\b", "creepy_laugh", 0.3),
    (r"\b(glass\s+shatter\w*|shatter(?:s|ed)|smashed the window)\b", "glass_break", 0.35),
    (r"\b(heart\s+(?:pound\w*|rac\w*|thump\w*)|heartbeat)\b", "heartbeat", 0.35),
    (r"\b(owl\w*\s+(?:hoot\w*|call\w*)|hoot(?:s|ed|ing))\b", "owl", 0.3),
    (r"\b(church\s+bells?|bell\s+(?:rang|tolled|toll\w*))\b", "church_bell", 0.3),
    (r"\b(camera\s+(?:click\w*|flash\w*)|snapped a (?:photo|picture))\b", "camera_shutter", 0.35),
    (r"\b(static|radio\s+crackl\w*)\b", "radio_static", 0.28),
]
# What each licensed SFX file should sound like (CLAP text side). sfx_index() checks the AUDIO against these
# descriptions once (laion/clap-htsat-unfused, Apache-2.0, local, free) and stores assets/sfx/clap_index.json.
SFX_LABELS = {
    "footsteps_wood": "footsteps on a wooden floor", "footsteps_gravel": "footsteps on gravel",
    "footsteps_grass": "footsteps on grass", "footsteps_leaves": "footsteps on dry leaves",
    "footsteps_mud": "footsteps in mud", "footsteps_snow": "footsteps in snow", "door_slam": "a door slamming shut",
    "door_creak": "a creaking door opening", "door_unlock": "a key unlocking a door", "knocking": "knocking on a door",
    "phone_notification": "a phone message notification chime", "phone_buzz": "a phone vibrating",
    "thunder": "thunder rumbling", "wind": "wind howling", "clock_ticking": "a clock ticking",
    "whispers": "people whispering", "creepy_laugh": "a creepy laugh", "glass_break": "glass shattering",
    "heartbeat": "a heartbeat", "owl": "an owl hooting", "church_bell": "a church bell ringing",
    "camera_shutter": "a camera shutter click", "radio_static": "radio static", "whoosh": "a fast whoosh",
    "ui_click": "a soft click", "doorbell": "a doorbell", "keys_jingle": "keys jingling",
    "twigs_snap": "twigs snapping", "floor_creak": "a wooden floor creaking", "breathing_calm": "calm breathing",
    "ghost_presence": "an eerie ghostly drone",
}
SURFACE = {"gravel": "footsteps_gravel", "grass": "footsteps_grass", "field": "footsteps_grass",
           "leaves": "footsteps_leaves", "forest": "footsteps_leaves", "woods": "footsteps_leaves",
           "mud": "footsteps_mud", "swamp": "footsteps_mud", "snow": "footsteps_snow", "ice": "footsteps_snow"}
SFX_INDEX = ROOT / "assets" / "sfx" / "clap_index.json"


def sfx_index(rebuild: bool = False) -> dict:
    """{file: {"label", "best", "rank", "similarity", "verified"}}: CLAP's check that each licensed SFX recording
    sounds like its label (verified = its own label is among CLAP's top 3 of all labels). Built once offline:
    python -c "import explainer; explainer.sfx_index(rebuild=True)"; production only READS the committed json (no
    model load). A missing index = every known file allowed (the old behaviour)."""
    if not rebuild:
        try:
            return json.loads(SFX_INDEX.read_text())
        except (OSError, ValueError):
            return {}
    import torch
    from transformers import ClapModel, ClapProcessor
    model = ClapModel.from_pretrained("laion/clap-htsat-unfused").eval()
    proc = ClapProcessor.from_pretrained("laion/clap-htsat-unfused")
    names = [n for n in SFX_LABELS if (ROOT / "assets" / "sfx" / f"{n}.mp3").is_file()]
    labels = [SFX_LABELS[n] for n in names]
    with torch.no_grad():
        t = _emb(model.get_text_features(**proc(text=labels, return_tensors="pt", padding=True)))
        out = {}
        for n in names:
            wav = _load_sfx(n, 48000)
            if wav is None or not len(wav):
                continue
            a = _emb(model.get_audio_features(**proc(audio=[wav[:48000 * 8]], sampling_rate=48000,
                                                      return_tensors="pt")))
            sims = (a @ t.T)[0].tolist()
            order = sorted(range(len(names)), key=lambda k: -sims[k])
            rank = order.index(names.index(n)) + 1
            out[n] = {"label": SFX_LABELS[n], "best": names[order[0]], "rank": rank,
                      "similarity": round(sims[names.index(n)], 3), "verified": rank <= 3}
    SFX_INDEX.write_text(json.dumps({"model": "laion/clap-htsat-unfused", "files": out}, indent=1))
    log(f"SFX CLAP index: {sum(v['verified'] for v in out.values())}/{len(out)} recordings match their label")
    return json.loads(SFX_INDEX.read_text())


def _emb(x):
    """A unit-length embedding from a transformers features call (a tensor, or an output with pooler_output)."""
    x = getattr(x, "pooler_output", x)
    return x / x.norm(dim=-1, keepdim=True)


def _sfx_ok(name: str) -> bool:
    files = (sfx_index() or {}).get("files") or {}
    return name not in files or bool(files[name].get("verified"))


HYPOTHETICAL = re.compile(r"\b(if|might|would|could|imagine|don't|do not|never|isn't|try to|whether|without)\b",
                          re.IGNORECASE)


def event_sfx(narration: dict, max_total: int = 4, cooldown: float = 8.0, hook_guard: float = 1.5) -> list[tuple]:
    """(time, sfx, volume, seconds) for sounds of events the narration DESCRIBES, timed to the word that names them.
    Hypothetical / negated lines ("walk away without answering", "if you hear knocking") and the first 1.5 s stay
    silent; one sound per sentence, the same sound not within 8 s, at most 4 per video. Silence is a valid result."""
    words = narration.get("words") or []
    if not words:
        return []
    sentences, cur = [], []
    for w in words:
        cur.append(w)
        if re.search(r"[.!?]$", w["word"]):
            sentences.append(cur)
            cur = []
    if cur:
        sentences.append(cur)
    events, last = [], {}
    for si, sent in enumerate(sentences):
        text = " ".join(w["word"] for w in sent)
        context = " ".join(w["word"] for w in sum(sentences[max(0, si - 1):si + 1], []))
        if HYPOTHETICAL.search(text):
            continue
        for rx, name, vol in SFX_EVENTS:
            m = re.search(rx, text, re.IGNORECASE)
            if not m:
                continue
            if name == "footsteps_wood":  # the surface the narration names (gravel, snow, leaves...)
                surf = next((f for w, f in SURFACE.items() if re.search(rf"\b{w}\b", context, re.IGNORECASE)), None)
                name = surf or name
            if not _sfx_ok(name):  # CLAP says this recording doesn't sound like its label: silence instead
                continue
            first = len(text[:m.start()].split())
            at = sent[min(first, len(sent) - 1)]["start"]
            if at < hook_guard or at - last.get(name, -99.0) < cooldown:
                continue
            events.append((round(at, 3), name, vol, 1.6))
            last[name] = at
            break  # one sound per sentence: never stacked effects
        if len(events) >= max_total:
            break
    return events


def caption_accents(story: dict, narration: dict, per_scene: int = 1) -> set[int]:
    """Indexes (into narration['words']) of the few spoken words the caption track may accent: the payoff word of
    each scene's strongest phrase, at most per_scene per scene. Everything else is captioned plainly."""
    words = narration.get("words") or []
    out = set()
    for i, sc in enumerate(story.get("scenes") or []):
        phrases = [p for p in key_phrases(sc.get("narration", ""), limit=per_scene, min_score=3.0)
                   if len(p["text"].split()) >= 2 or p["first"][:1].isupper() or re.match(r"\d", p["text"])]
        idx = [k for k, w in enumerate(words) if w.get("scene") == i]
        for p in phrases:
            target = _bare(p["accent"])
            hit = next((k for k in idx if _bare(words[k]["word"]) == target), None)
            if hit is not None:
                out.add(hit)
    return out


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
    weights = [0.9 if k == "graphic" else 1.0 for k in kinds]  # a graphic is read in a beat; pictures carry the story
    free = sum(w for w, x in zip(weights, fixed) if x is None) or 1.0
    return [x if x is not None else rest * w / free for w, x in zip(weights, fixed)]


def sequence(story: dict, narration: dict, scene_images: list[list[Path]], graphics: list[list[dict]],
             total: float) -> list[dict]:
    """The production shot list: per scene  story image -> graphic -> second story image -> (rare host reaction),
    with varied deliberate holds and cuts on word starts. The host: max 1 shot per scene, never in two scenes in a row, never first in a
    scene, <= explainer_host_max_seconds (2 s), <= explainer_host_max_share (15%) of the runtime. The video opens
    straight on the first story picture (the cover frame is laid over its first cover_seconds; the title is a
    kinetic overlay, plan_effects) and ends on the closing graphic (no end card)."""
    spans = _scene_spans(story, narration)
    words = narration["words"]
    budget = float(CONFIG.get("explainer_host_max_share", 0.15)) * total
    host_used, last_host_scene = 0.0, -9
    prev_template = ""
    segs = []
    n_sc = len(story["scenes"])
    for i, (a, b) in enumerate(spans):
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
        beat = viewer_beat(narr)  # a warning / decision / reaction aimed at the viewer
        has_choice = any(g.get("template") == "choice" for g in gs)  # the P08 surrogate already plays this beat
        import sprites
        owner_pose = sprites.owner_pose_for(narr)  # the owner's own pose set, when the line says its action / prop
        host_ok = (i > 0 and i - last_host_scene > 1 and host_used + 1.8 <= budget and not has_choice
                   and (owner_pose or beat or _EMOTION.search(narr) or len(scene_images[i]) < 2) and span >= 6.0)
        # room for picture -> graphic -> second picture from ~6 s (cuts stay >= SHOT_MIN): the scene's second
        # picture is no longer dropped for its graphic (the Aka Manto preview had one picture + one card per scene)
        n = max(2 if gs else 1, min(6, round(span / 3.0)))
        order = [imgs[0]]
        if gs:
            order.append(gs[0])
        if len(scene_images[i]) > 1:
            order.append(imgs[1])
        if host_ok and owner_pose:  # preferred over a second AI / stock picture of the same line
            order.insert(1, {"type": "host", "scene": i, "expression": "pose", "asset_id": f"pose:{owner_pose}",
                             "beat": "owner_pose"})
            if len(order) > 3:
                order.remove(next(x for x in reversed(order) if x["type"] == "image"))
        elif host_ok:
            # the viewer beat (warning -> worried, decision -> serious...) gives the deterministic expression; the
            # shared local CLIP (sprites.select_for_beat) may pick a better APPROVED asset, never new art
            expression = beat[1] if beat else _expr_for(narr)
            selected = sprites.select_for_beat(narr, expression, allow_poses=bool(beat and beat[0] == "choice"))
            asset_id = selected if selected != sprites.face_id(expression) else None
            order.append({"type": "host", "scene": i, "expression": expression, "asset_id": asset_id,
                          "beat": beat[0] if beat else ""})
        if len(gs) > 1 and span > 9.0:
            order.append(gs[1])
        # Avoid manufacturing extra cuts by repeating crops of the same image.
        if closing:
            order.append(closing)
        while len(order) > max(1, n) and len(order) > (2 if closing else 1):
            drop = next((x for x in reversed(order[1:]) if x["type"] == "host" and x.get("beat") != "owner_pose"), None) \
                or next((x for x in reversed(order[1:]) if x["type"] == "image"), None) or next((x for x in reversed(order[1:]) if x["type"] == "graphic" and x is not closing), None)
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
    plan_transitions(segs, words)  # hard cut by default; dissolve only when narrated time passes
    plan_motion(segs, words)  # push / pan / pull / still per story picture
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
    # Semantic selection after the *existing* licensed-library -> real-media -> AI generation chain.
    # All hard QA/rights/scene-specific constraints remain intact; only order surviving shots.
    for i, picture_paths in enumerate(per_scene):
        if not picture_paths:
            continue
        ranked = library.rank_images(story["scenes"][i].get("narration", ""),
                                     list(picture_paths), source="scene_final")
        if ranked:
            primary = ranked[0]
            story.setdefault("_clip_scene_matches", {})[str(i)] = {
                "chosen": Path(primary["path"]).name, "score": round(primary["score"], 4),
                "runner_up": round(ranked[1]["score"], 4) if len(ranked) > 1 else None}
            if len(ranked) > 1 and i != 0 and primary["score"] - ranked[1]["score"] >= float(
                    CONFIG.get("clip_reorder_min_margin", 0.02)):
                by_name = {str(p): p for p in picture_paths}
                per_scene[i] = [by_name[item["path"]] for item in ranked if item["path"] in by_name]
            log(f"CLIP scene {i:02d}: chosen={primary['path']}, score={primary['score']:.3f}, "
                f"runner_up={ranked[1]['score']:.3f}" if len(ranked) > 1 else
                f"CLIP scene {i:02d}: chosen={primary['path']}, score={primary['score']:.3f}")
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
        self.accents = caption_accents(story, narration)  # the few payoff words captions may accent
        self.groups = _caption_groups(narration["words"], self.accents)
        self.used_assets: set = set()
        self.frame_log = {"image": 0, "graphic": 0, "host": 0, "end_card": 0}
        self.effects: list = []  # plan_effects(): overlays + in-shot moves, set by render()
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

    def _foreground(self, path: str) -> Image.Image | None:
        """The picture's near layer for depth parallax: the cover image with alpha = feathered Depth Anything V2
        nearness (effects.depth_map, the classic renderer's model, local CPU). None when depth can't run, the flag
        explainer_depth_parallax is off, or the picture has no clear foreground."""
        key = ("fg", path)
        if key in self.cache:
            return self.cache[key]
        fg = None
        if CONFIG.get("explainer_depth_parallax", True):
            import effects
            d = effects.depth_map(Path(path))
            if d is not None:
                near = np.clip((d - 0.6) / 0.2, 0, 1)
                if 0.05 < float(near.mean()) < 0.55:  # a real foreground, not the whole frame or nothing
                    base = self._cover(path, 1.08)
                    m = Image.fromarray((near * 255).astype("uint8")).resize(base.size, Image.BILINEAR)
                    fg = base.copy()
                    fg.putalpha(m.filter(ImageFilter.GaussianBlur(6)))
        self.cache[key] = fg
        return fg

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
        # plan_motion: push toward a clue, pan along the scene, pull back for isolation, or hold still so
        # a reveal lands (older shot lists without "motion" keep the index rotation)
        move = seg.get("motion") or ("push", "pan", "pull")[self._index(seg) % 3]
        if move == "still":
            frame = self._crop(base, cx, cy, z * 1.03)
        elif move == "push":
            frame = self._crop(base, cx, cy, z * (1.0 + 0.095 * x))
        elif move == "pan":
            frame = self._crop(base, cx + 0.075 * (x - 0.5), cy, z * 1.03)
        else:
            frame = self._crop(base, cx, cy + 0.06 * (0.5 - x), z * (1.09 - 0.075 * x))
        fg = self._foreground(s["file"]) if clip is None and move in ("push", "pan") else None
        if fg is not None:  # 2.5D: the near layer (Depth Anything V2) moves a little more than the background
            if move == "push":
                frame.alpha_composite(self._crop(fg, cx, cy, z * (1.0 + 0.135 * x)))
            else:
                frame.alpha_composite(self._crop(fg, cx + 0.105 * (x - 0.5), cy, z * 1.03))
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
        selected = s.get("asset_id")
        if selected and selected.startswith("pose:"):  # the owner's own pose (assets/poses), verified, unchanged
            im = sprites.owner_pose_image(selected[5:])
            self.used_assets.add(selected)
            scale = min(900 / im.width, 1250 / im.height) * push
            im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))),
                           Image.Resampling.LANCZOS)
            ox, oy = (W - im.width) // 2, 1300 - im.height  # feet above the captions
        elif selected and selected.startswith("P"):  # optional approved full pose, never a generated replacement
            im = sprites.approved_image(selected)
            self.used_assets.add(selected)
            scale = min(930 / im.width, 1450 / im.height) * push
            im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))),
                           Image.Resampling.LANCZOS)
            ox, oy = (W - im.width) // 2, H - im.height + 25
        elif n % 3 == 2 and not selected:
            im, (fxp, fyp) = self.figure("three_quarter", "right", int(1150 * push))
            ox, oy = int(W * 0.5 - fxp), int(1640 - fyp)
            sh = self._shadow(int(im.width * 0.9))
            self._paste(frame, sh, int(W * 0.5 - sh.width / 2), 1640 - sh.height // 2)
        else:
            im, aid = (sprites.approved_image(selected), selected) if selected else sprites.bust(
                s.get("expression") or "neutral")
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
    def frame_at(self, t: float) -> Image.Image:
        """The frame at t: a story picture, a graphic or a host reaction, then the planned motion effects (zoom
        punch / flicker / stamp shake, overlays). There is no end card: the last segment runs to the end."""
        seg = next((s for s in self.segs if s["start"] <= t < s["end"]), self.segs[-1])
        local = t - seg["start"]
        frame = self._shot_frame(seg, local)
        frame = self._transition(seg, frame, local)
        frame = self.apply_effects(frame, t)
        if not (CONFIG.get("remotion_polish", False) or CONFIG.get("explainer_caption_engine") == "remotion"):
            self.captions(frame, t, "scene", high=seg["shot"]["type"] == "host")
        return frame

    # transition lengths (s); plan_transitions chose one per cut ("cut" = none)
    TRANSITION_S = {"dissolve": 0.45, "slide": 0.28, "swoosh": 0.24, "pop": 0.18, "whip": 0.24}

    def _transition(self, seg: dict, frame: Image.Image, local: float) -> Image.Image:
        """Into this segment: dissolve (cross-fade from the previous shot's last frame), slide / swoosh (push: the
        previous frame leaves left as this one enters), pop (a quick scale-up fade, UI-like graphics) or a hard cut."""
        tr = seg.get("transition", "cut")
        dur = self.TRANSITION_S.get(tr)
        k = self._index(seg)
        if not dur or k == 0 or local >= dur:
            return frame
        key = ("prev", k)
        prev = self.layer_cache.get(key)
        if prev is None:
            p = self.segs[k - 1]
            prev = self._shot_frame(p, max(0.0, p["end"] - p["start"] - 1.0 / FPS))
            self.layer_cache = {kk: v for kk, v in self.layer_cache.items() if kk[0] != "prev"}
            self.layer_cache[key] = prev
        a = _ease(local / dur)
        if tr == "dissolve":
            return Image.blend(prev.convert("RGBA"), frame.convert("RGBA"), a)
        if tr in ("slide", "swoosh", "whip"):
            out = Image.new("RGBA", (W, H), BLACK + (255,))
            off = int(W * a)
            out.alpha_composite(prev, (-off, 0))
            out.alpha_composite(frame, (W - off, 0))
            if tr == "whip":  # motion blur along the pan, strongest mid-move
                blur = int(2 + 46 * math.sin(math.pi * a))
                out = out.resize((max(1, W // blur), H), Image.BILINEAR).resize((W, H), Image.BILINEAR)
            return out
        sc = 0.94 + 0.06 * a  # pop
        small = frame.resize((int(W * sc), int(H * sc)), Image.BILINEAR)
        lay = prev.copy()
        top = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        top.alpha_composite(small, ((W - small.width) // 2, (H - small.height) // 2))
        return Image.blend(lay, Image.alpha_composite(lay, top), a)

    def _shot_frame(self, seg: dict, local: float) -> Image.Image:
        """One segment's own frame at local time (no transition, no captions)."""
        import noir
        sh = seg["shot"]
        kind = sh["type"]
        dur = seg["end"] - seg["start"]
        if kind == "graphic":  # its entrance is the planned transition (no automatic wipe on every card)
            frame = noir.render(sh["template"], sh.get("fields") or {}, local, dur, self.ctx(seg))
            self.frame_log["graphic"] += 1
        elif kind == "host":
            frame = self.host_frame(seg, local)
            self.frame_log["host"] += 1
        else:
            frame = self.image_frame(seg, local)
            self.frame_log["image"] += 1
            if CONFIG.get("explainer_cinematic_camera", False):
                frame = noir.cinematic_camera(frame, "subtle_push", local, dur)
        return frame

    def apply_effects(self, frame: Image.Image, t: float) -> Image.Image:
        """The plan_effects layer at t: in-shot moves first (zoom punch on a payoff word, light flicker, the short
        shake after a stamp lands), then the overlay templates (noir.overlay) on top."""
        import noir
        for e in self.effects:
            local = t - e["start"]
            if not 0 <= local <= e["dur"]:
                continue
            k = e["kind"]
            if k == "zoom_punch":
                z = 1.0 + 0.06 * (noir.back(local / 0.12) if local < 0.12 else 1 - noir.ease((local - 0.12) / 0.33))
                if z > 1.002:
                    frame = self._crop(frame, 0.5, 0.42, z)
            elif k == "flicker":
                lvl = (1.0, 0.55, 0.95, 0.4, 1.0, 0.7, 1.0, 0.85)[min(7, int(local / 0.1))]
                frame = Image.blend(Image.new("RGBA", (W, H), BLACK + (255,)), frame, lvl)
            else:
                if k == "stamp":
                    q = local - e["fields"].get("land", 0.2)
                    if 0 <= q < 0.16:
                        dx, dy = int(9 * math.sin(q * 140)), int(6 * math.cos(q * 110))
                        moved = Image.new("RGBA", (W, H), BLACK + (255,))
                        moved.alpha_composite(frame, (dx, dy))
                        frame = moved
                ctx = self.overlay_ctx
                frame.alpha_composite(noir.overlay(k, e["fields"], local, e["dur"], ctx))
        return frame

    @property
    def overlay_ctx(self) -> dict:
        if not hasattr(self, "_octx"):
            self._octx = {"accent": self.acc}
        return self._octx

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
                       if seg["start"] - 0.05 <= w["start"] < seg["end"]], "bg": bg, "used_assets": self.used_assets}
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

    def captions(self, frame: Image.Image, t: float, kind: str, high: bool = False) -> None:
        """high: a host bust fills the lower frame, so the caption sits in the top safe area (never over a face)."""
        g = next((g for g in self.groups if g["start"] <= t < g["end"]), None)
        if not g:
            return
        active = max([k for k, w in enumerate(g["words"]) if w["start"] <= t + 0.03] or [0])
        key = ("cap", id(g), active, kind)
        im = self.layer_cache.get(key)
        if im is None:
            im = self._caption_image(g, active, kind)
            self.layer_cache[key] = im
        frame.alpha_composite(im, (0, (330 if high else CAP_Y) - im.height // 2))

    def _caption_image(self, g: dict, active: int, kind: str) -> Image.Image:
        f = font("bold", 78)
        texts = [w["text"] for w in g["words"]]
        lines = _wrap(" ".join(texts), f, 860)
        hgt = len(lines) * 96 + 40
        im = Image.new("RGBA", (W, hgt), (0, 0, 0, 0))
        shadow = Image.new("RGBA", (W, hgt), (0, 0, 0, 0))
        d, ds = ImageDraw.Draw(im), ImageDraw.Draw(shadow)
        k = 0
        flags = [w.get("accent") for w in g["words"]]
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
                    if k < len(flags) and flags[k] and on:
                        col = self.acc + (255,)
                    ds.text((x, y + 6), w, font=f, fill=(0, 0, 0, 200))
                d.text((x, y), w, font=f, fill=col)
                x += ww + sp
                k += 1
        if kind != "card":
            shadow = shadow.filter(ImageFilter.GaussianBlur(9))
            shadow.alpha_composite(im)
            return shadow
        return im


def _caption_groups(words: list[dict], accents: set | None = None) -> list[dict]:
    """1-3 words per caption, broken at punctuation and pauses; each shown until the next one starts. Words whose
    index is in `accents` (caption_accents) are drawn in the accent colour; nothing else is accented."""
    groups, cur = [], []
    accents = accents or set()
    for k, w in enumerate(words):
        w = dict(w, accent=k in accents)
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
                    "words": [{"start": w["start"], "text": re.sub(r"[{}\\]", "", w["word"]),
                               "accent": bool(w.get("accent"))} for w in g]})
    return out


# ================================================================ audio + encode

# effect sounds fetched from Freesound (CC0) on first use; until then (no FREESOUND_API_KEY) the effect uses the
# library's own CC0 click, re-pitched, or stays silent
SFX_FALLBACK = {"reel_tick": ("ui_click", 3), "typing_click": ("ui_click", 6), "reel_land": ("ui_click", -7)}


def _load_sfx(name: str, sr: int) -> np.ndarray | None:
    path = ROOT / "assets" / "sfx" / f"{name}.mp3"
    if not path.exists():
        try:
            import get_sfx
            path = get_sfx.ensure(name) or path
        except Exception as e:  # noqa: BLE001
            log(f"SFX {name}: not available ({e})")
    if not path.exists():
        if name in SFX_FALLBACK:
            base, semis = SFX_FALLBACK[name]
            snd = _load_sfx(base, sr)
            return _pitch(snd, semis) if snd is not None else None
        return None
    try:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                             capture_output=True, check=True).stdout
        snd = np.frombuffer(raw, dtype=np.float32)
        loud = np.flatnonzero(np.abs(snd) > 0.02 * (float(np.max(np.abs(snd))) or 1.0))
        return snd[max(0, int(loud[0]) - int(0.004 * sr)):] if len(loud) else snd  # no leading silence
    except Exception:  # noqa: BLE001
        return None


def _pitch(snd: np.ndarray, semis: float) -> np.ndarray:
    """Re-pitch by resampling (shorter + higher for semis > 0): the year reel's rising ticks."""
    if not semis or snd is None or not len(snd):
        return snd
    rate = 2 ** (semis / 12)
    x = np.arange(0, len(snd) - 1, rate)
    return np.interp(x, np.arange(len(snd)), snd).astype(np.float32)


def _mix_audio(narration: dict, total: float, events: list, out: Path) -> Path:
    import soundfile as sf
    voice, sr = sf.read(str(narration["path"]), dtype="float32")
    if voice.ndim > 1:
        voice = voice.mean(axis=1)
    mix = np.zeros(int(total * sr) + sr, dtype=np.float32)
    mix[:len(voice)] += voice[:len(mix)]
    win = int(0.03 * sr)  # voice loudness envelope (30 ms RMS) for ducking effect sounds under word peaks
    env_ = np.sqrt(np.convolve(voice ** 2, np.ones(win) / win, mode="same")) if len(voice) > win else np.zeros(1)
    peak_v = float(np.percentile(env_, 95)) or 1.0
    cache = {}
    for event in events:
        # (time, name, volume[, clip seconds[, opts]]): opts pitch = semitones, duck = softer on a voice peak
        t, name, vol = event[:3]
        clip_seconds = event[3] if len(event) >= 4 else None
        opts = event[4] if len(event) >= 5 else {}
        if name not in cache:
            cache[name] = _load_sfx(name, sr)
        sound = cache[name]
        if sound is None:
            continue
        if opts.get("pitch"):
            sound = _pitch(sound, opts["pitch"])
        at = max(0, int(t * sr))
        if opts.get("duck") and at < len(env_) and env_[at] > 0.6 * peak_v:
            vol *= 0.45
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


# ================================================================ motion effects (overlay templates)
# One reusable vocabulary for every story (owner, Oct 31): the opening title, a year reel per spoken date, counters,
# stamps, redaction, a polaroid, typed text, kinetic phrases, zoom punch, light flicker, film burn and whip pans.
# The planner picks each by MEANING from the narration's own words, times it to the spoken word and keeps at most ONE
# big effect per 3 s; overlays are drawn only over story pictures (never over the host's face or a graphic card),
# inside the safe area above the captions. Effect sounds are quiet and ducked under the voice.

EFFECT_GAP = 3.0  # s between two big effects (start to start, and they never overlap)
STAMP_CUES = (
    ("UNSOLVED", re.compile(r"\b(unsolved|never (?:been )?solved|never (?:found|identified|caught)|"
                            r"remains? (?:a )?mystery|no one knows)\b", re.IGNORECASE)),
    ("CASE CLOSED", re.compile(r"\b(case (?:was )?closed|convicted|confess\w*|(?<!never )(?<!never been )solved)\b",
                               re.IGNORECASE)),
    ("CLASSIFIED", re.compile(r"\b(classified|top secret|sealed (?:files?|records?)|redacted)\b", re.IGNORECASE)),
    ("MISSING", re.compile(r"\b(vanish\w*|disappear\w*|went missing|missing)\b", re.IGNORECASE)),
)
COUNT_UNITS = re.compile(r"^(people|persons|men|women|children|kids|victims|bodies|days|nights|weeks|months|years|hours|"
                         r"minutes|miles|kilometers|kilometres|feet|meters|metres|dollars|pounds|times|letters|calls|"
                         r"witnesses|passengers|soldiers|sailors|officers|homes|houses|graves|shots|steps)$")
PHOTO_CUE = re.compile(r"\b(photo\w*|snapshot|polaroid|camera|portrait)\b", re.IGNORECASE)
REVEAL_CUE = re.compile(r"\b(?:real name|true name|identity|known as|name was|named|called)\s+(?:was\s+)?"
                        r"((?:[A-Z][\w'’-]+\s?){1,3})")
STRIKE_CUE = re.compile(r"\b(ruled out|debunked|disproved|a hoax|was false|never happened)\b", re.IGNORECASE)
GLITCH_CUE = re.compile(r"\b(static|glitch\w*|signal|radio|transmission|broadcast|screen|footage|tape|recording)\b",
                        re.IGNORECASE)
LIGHT_CUE = re.compile(r"\b(lights?|lamps?|lanterns?|candles?|bulbs?|flicker\w*|flashlight|torch|power (?:went|cut))\b",
                       re.IGNORECASE)
BURN_CUE = re.compile(r"\b(?:years|decades|centur(?:y|ies)|generations?)\s+(?:later|earlier|ago|passed)\b|"
                      r"\bby the time\b", re.IGNORECASE)
WHIP_CUE = re.compile(r"\b(?:meanwhile|miles away|across (?:the|town|the country|the ocean)|back in|"
                      r"(?:flew|drove|sailed|travel(?:l)?ed|headed|went) (?:to|back to|across))\b", re.IGNORECASE)
CLAIMABLE = {"impact", "evidence", "fact", "missing"}
PHRASE_MODES = ("highlight", "underline", "circle", "pop", "stagger")


def _scene_text(narration: dict, i: int) -> tuple[list[int], str, list[int]]:
    """(word indexes, the scene's spoken words joined by spaces, each word's character offset) for regex -> word."""
    idx = [k for k, w in enumerate(narration["words"]) if w.get("scene") == i]
    text, offs = "", []
    for k in idx:
        offs.append(len(text))
        text += narration["words"][k]["word"] + " "
    return idx, text, offs


def _word_at(idx: list[int], offs: list[int], char: int) -> int:
    import bisect
    return idx[max(0, bisect.bisect_right(offs, char) - 1)]


def _sentence_of(text: str, char: int) -> str:
    a = max(text.rfind(c, 0, char) for c in ".!?") + 1
    b = min([x for x in (text.find(c, char) for c in ".!?") if x >= 0] or [len(text)])
    return text[a:b]


def _counter_at(words: list[dict], idx: list[int]) -> list[tuple[int, int, str]]:
    """(first word index, value, unit) for every '<number> <unit>' the scene says ("six people", "1,200 miles")."""
    import spoken_numbers as nums
    out = []
    toks = [_tok(words[k]["word"]) for k in idx]
    for u, t in enumerate(toks):
        if not COUNT_UNITS.match(t) or u == 0:
            continue
        for ln in range(min(6, u), 0, -1):
            span = " ".join(words[k]["word"] for k in idx[u - ln:u]).strip(",.")
            first = toks[u - ln]
            if not (first[:1].isdigit() or first in nums.WORD_VAL or first in nums.SCALE_VAL):
                continue
            vals = nums.values(span)
            if len(vals) == 1:
                v = int(next(iter(vals)))
                if 2 <= v <= 1_000_000_000 and not (1000 <= v <= 2100 and ln <= 2 and t in ("years",)):
                    out.append((idx[u - ln], v, t))
                break
    return out


def _seg_at(segs: list[dict], t: float) -> dict | None:
    return next((s for s in segs if s["start"] <= t < s["end"]), None)


def _picture_instead(segs: list[dict], seg: dict) -> bool:
    """Turn a graphic segment into another framing of its scene's own picture (so the title / a year reel sits on
    the story image, not on a card). False when the scene has no picture or it is the closing card."""
    if seg["shot"].get("template") == "closing":
        return False
    pics = [s["shot"] for s in segs if s["scene"] == seg["scene"] and s["shot"].get("type") == "image"]
    if not pics:
        return False
    k = segs.index(seg)
    prev = segs[k - 1]["shot"] if k else {}
    src = next((p for p in pics if p.get("file") != prev.get("file")), pics[0])
    crop = next(c for c in ("detail_right", "detail_left", "top", "full") if not (
        prev.get("file") == src.get("file") and prev.get("crop") == c))
    seg["shot"] = dict(src, crop=crop, replaced_graphic=seg["shot"].get("template"))
    seg["transition"] = "cut"
    return True


def plan_effects(story: dict, narration: dict, segs: list[dict], cover: float | None = None) -> list[dict]:
    """The video's overlay effects: [{"kind", "start", "dur", "anchor", "fields", "big", "sfx": [(t, name, vol, clip,
    opts)]}], start-sorted. Candidates come from the narration's own words (dates, counts, stamps, photos, quotes,
    name reveals, debunks, screens, lights, time jumps); then, by priority, every big effect must sit >= EFFECT_GAP
    from the last one, over a story picture (not a graphic card, never during a host shot)."""
    import noir
    words = narration["words"]
    cover = float(CONFIG.get("cover_seconds", 0.8)) if cover is None else cover
    cands = []
    title = str(story.get("fixed_title") or story.get("title") or "").strip()
    if title:
        cands.append({"kind": "title", "start": cover, "dur": noir.title_seconds(title), "anchor": cover,
                      "prio": 0, "big": True, "fields": {"text": title,
                                                         "kicker": "TRUE STORY" if story.get("true_story") else ""}})
    for n, d in enumerate(date_mentions(story, narration)):
        if n >= int(CONFIG.get("year_reel_max_per_video", 4)):
            break
        land_t = words[d["word"]]["start"]
        vals = noir.reel_values(d["target"], d["kind"])
        start = max(0.0, land_t - noir.REEL_TRAVEL)
        land = land_t - start
        hold = 1.5 + 0.06 * len(d["label"])
        show = str(d["target"]) if d["kind"] == "year" else f"{d['label'][:3]} {d['target']}"
        cands.append({"kind": "year_reel", "start": start, "dur": land + hold, "anchor": land_t, "prio": 1,
                      "big": True, "date": d, "show": show,
                      "fields": {"values": vals, "land": land, "label": d["label"] if d["kind"] == "year"
                                 else d["label"] + f" {d['target']}", "kicker": d["kicker"]}})
    graphics_by_scene = {}
    for sg in segs:
        if sg["shot"].get("type") == "graphic":
            graphics_by_scene.setdefault(sg["scene"], set()).add(sg["shot"].get("template"))
    stamps_used = set()
    for i, sc in enumerate(story["scenes"]):
        idx, text, offs = _scene_text(narration, i)
        if not idx:
            continue
        mine = graphics_by_scene.get(i, set())
        for label, rx in STAMP_CUES:
            m = rx.search(text)
            if not m or label in stamps_used or (label == "MISSING" and "missing" in mine) \
                    or HYPOTHETICAL.search(_sentence_of(text, m.start()).replace("never solved", "")
                                           .replace("never found", "").replace("never been", "")):
                continue
            if label == "CASE CLOSED" and re.search(r"\bnever\b", _sentence_of(text, m.start()), re.IGNORECASE):
                continue
            t = words[_word_at(idx, offs, m.start())]["start"]
            stamps_used.add(label)
            cands.append({"kind": "stamp", "start": t - 0.2, "dur": 2.2, "anchor": t, "prio": 2, "big": True,
                          "fields": {"text": label, "land": 0.2}})
            break
        for k, v, unit in _counter_at(words, idx)[:1]:
            t = words[k]["start"]
            cands.append({"kind": "counter", "start": max(0.0, t - 1.0), "dur": 1.0 + 1.6, "anchor": t, "prio": 3,
                          "big": True, "fields": {"value": v, "unit": unit, "land": min(1.0, t)}})
        m = PHOTO_CUE.search(text)
        if m and not HYPOTHETICAL.search(_sentence_of(text, m.start())):
            t = words[_word_at(idx, offs, m.start())]["start"]
            cands.append({"kind": "polaroid", "start": t - 0.45, "dur": 2.4, "anchor": t, "prio": 4, "big": True,
                          "fields": {"land": 0.45, "caption": ""}})
        q = _QUOTE.search(text)
        if q and len(q.group(1).split()) >= 2 and not mine & {"quote", "phone"}:
            t = words[_word_at(idx, offs, q.start(1))]["start"]
            body = q.group(1).strip()[:60]
            dur = 0.15 + len(body) / noir.TYPE_CPS + 1.2
            cands.append({"kind": "typewriter", "start": t, "dur": dur, "anchor": t, "prio": 5, "big": True,
                          "fields": {"text": body, "start": 0.15, "kicker": ""}})
        m = REVEAL_CUE.search(text)
        if m:
            name = m.group(1).strip(" ,.")
            t = words[_word_at(idx, offs, m.start(1))]["start"]
            cands.append({"kind": "redaction", "start": t - 0.7, "dur": 2.3, "anchor": t, "prio": 5, "big": True,
                          "fields": {"text": name, "land": 0.7, "kicker": "NAME"}})
        for rx, mode, prio in ((STRIKE_CUE, "strike", 6), (GLITCH_CUE, "glitch", 7)):
            m = rx.search(text)
            if not m:
                continue
            clause = _sentence_of(text, m.start())
            ph = key_phrases(clause, limit=1, min_score=2.0)
            if not ph:
                continue
            t = words[_word_at(idx, offs, m.start())]["start"]
            cands.append({"kind": "phrase", "start": t - 0.3, "dur": 2.0, "anchor": t, "prio": prio, "big": True,
                          "fields": {"text": ph[0]["text"], "accent": ph[0]["accent"], "mode": mode, "land": 0.3}})
        m = LIGHT_CUE.search(text)
        if m and not HYPOTHETICAL.search(_sentence_of(text, m.start())):
            t = words[_word_at(idx, offs, m.start())]["start"]
            cands.append({"kind": "flicker", "start": t, "dur": 0.8, "anchor": t, "prio": 9, "big": True,
                          "fields": {}})
    accents = sorted(caption_accents(story, narration))
    phrase_n = 0
    for n, k in enumerate(accents):  # payoff words: a zoom punch, and a few kinetic key phrases
        t = words[k]["start"]
        cands.append({"kind": "zoom_punch", "start": t, "dur": 0.45, "anchor": t, "prio": 10, "big": True,
                      "fields": {}})
        sc = words[k].get("scene", 0)
        ph = key_phrases(story["scenes"][sc].get("narration", ""), limit=1, min_score=3.0)
        if ph and len(ph[0]["text"].split()) >= 2 and phrase_n < int(CONFIG.get("phrase_overlay_max", 3)):
            phrase_n += 1
            cands.append({"kind": "phrase", "start": t - 0.35, "dur": 2.0, "anchor": t, "prio": 8, "big": True,
                          "fields": {"text": ph[0]["text"], "accent": ph[0]["accent"],
                                     "mode": PHRASE_MODES[n % len(PHRASE_MODES)], "land": 0.35}})
    for k, sg in enumerate(segs):  # film burn over a narrated time jump at a scene change
        if k and sg["scene"] != segs[k - 1]["scene"] and BURN_CUE.search(_seg_text(sg, words)):
            cands.append({"kind": "film_burn", "start": sg["start"], "dur": 0.55, "anchor": sg["start"],
                          "prio": 6, "big": True, "fields": {}})
    chosen, skipped = [], []
    for c in sorted(cands, key=lambda c: (c["prio"], c["anchor"])):
        c["start"] = max(0.0, c["start"])
        c["skip"] = ""
        end = c["start"] + c["dur"]
        if c["start"] < cover - 1e-6 or _seg_at(segs, c["anchor"] + 0.05) is None:
            continue
        under = [s for s in segs if s["start"] < end and c["start"] < s["end"]]
        if any(s["shot"].get("type") == "host" for s in under):
            skipped.append(f"{c['kind']}@{c['anchor']:.1f}s host")
            continue  # never over the host's face
        if any(abs(o["anchor"] - c["anchor"]) < EFFECT_GAP or (o["start"] < end and c["start"] < o["start"] + o["dur"])
               for o in chosen if o["big"]):
            skipped.append(f"{c['kind']}@{c['anchor']:.1f}s spacing")
            continue
        cards = [s for s in under if s["shot"].get("type") == "graphic"]
        if cards and (c["prio"] > 3 or c["prio"] > 1 and any(s["shot"].get("template") not in CLAIMABLE
                                                               for s in cards)):
            skipped.append(f"{c['kind']}@{c['anchor']:.1f}s on a card")
            continue  # an overlay never sits on a graphic card
        # the title / a year reel (any card but the closing one), a stamp or a counter (only a card that says the
        # same thing less well: impact / evidence / fact / missing) claims its window: the card becomes the picture
        for s in cards:
            if not _picture_instead(segs, s):
                break
        else:
            cards = []
        if cards:
            continue
        at = _seg_at(segs, c["anchor"] + 0.05)
        if at is None or at["shot"].get("type") != "image":
            continue
        if c["kind"] == "polaroid":
            c["fields"]["image"] = at["shot"]["file"]
        chosen.append(c)
    chosen.sort(key=lambda c: c["start"])
    prev = None  # the first date of the video scrolls in on the reel; every later one is a line from the last date
    for c in chosen:
        if c["kind"] != "year_reel":
            continue
        if prev is not None:
            d, pd = c["date"], prev["date"]
            years = d["kind"] == pd["kind"] == "year"
            c["kind"] = "year_line"
            c["fields"] = {"from": prev["show"], "to": c["show"], "land": c["fields"]["land"],
                           "label": c["fields"]["label"] if d["label"] and d["kind"] == "year" else "",
                           "kicker": c["fields"]["kicker"],
                           "bumps": abs(d["target"] - pd["target"]) - 1 if years else 0,
                           "backwards": bool(years and d["target"] < pd["target"])}
        prev = c
    for c in chosen:
        c.pop("date", None)
        c.pop("show", None)
    if skipped:
        log("Motion effects skipped: " + ", ".join(skipped))
    for c in chosen:
        c["sfx"] = effect_sfx(c)
        c.pop("prio", None)
        c.pop("skip", None)
    story["explainer_effects"] = [{"kind": c["kind"], "start": round(c["start"], 2), "anchor": round(c["anchor"], 2),
                                   "dur": round(c["dur"], 2), "fields": {k: v for k, v in c["fields"].items()
                                                                         if k != "image"}} for c in chosen]
    return chosen


def effect_sfx(c: dict) -> list[tuple]:
    """The effect's own quiet sounds, absolute times: reel ticks rising in pitch + a clunk on the landing, counter
    ticks, a stamp thud, the polaroid shutter, typing clicks per typed character. opts duck = softened when the
    voice is loud at that instant (never on a spoken-word peak)."""
    import noir
    s, f, out = c["start"], c["fields"], []
    duck = {"duck": True}
    if c["kind"] == "year_reel":
        land = f["land"]
        ticks = noir.reel_ticks(len(f["values"]), land)
        for k, tt in enumerate(ticks[:-1]):
            out.append((s + tt, "reel_tick", 0.16, 0.12, dict(duck, pitch=k)))
        out.append((s + land, "reel_land", 0.3, 0.6, duck))
        out += [(s + tt, "typing_click", 0.09, 0.08, dict(duck, pitch=(k % 3) - 1))
                for k, tt in enumerate(noir.type_times(f.get("label") or "", land + 0.18))]
    elif c["kind"] == "year_line":
        ticks = noir.line_ticks(noir.line_bumps(f.get("bumps") or 0), f["land"])
        out += [(s + tt, "reel_tick", 0.1, 0.1, dict(duck, pitch=k)) for k, tt in enumerate(ticks)]
        out.append((s + f["land"], "reel_land", 0.26, 0.6, duck))
        out += [(s + tt, "typing_click", 0.09, 0.08, dict(duck, pitch=(k % 3) - 1))
                for k, tt in enumerate(noir.type_times(f.get("label") or "", f["land"] + 0.18))]
    elif c["kind"] == "counter":
        ticks = noir.counter_ticks(f["land"])
        out += [(s + tt, "reel_tick", 0.12, 0.1, dict(duck, pitch=k)) for k, tt in enumerate(ticks[:-1])]
        out.append((s + f["land"], "reel_land", 0.24, 0.5, duck))
    elif c["kind"] == "stamp":
        out.append((s + f["land"], "stamp_thud", 0.38, 0.8, duck))
    elif c["kind"] == "polaroid":
        out.append((s + f["land"] - 0.05, "camera_shutter", 0.28, 0.7, duck))
    elif c["kind"] == "typewriter":
        out += [(s + tt, "typing_click", 0.09, 0.08, dict(duck, pitch=(k % 3) - 1))
                for k, tt in enumerate(noir.type_times(f["text"], f.get("start", 0.15)))]
    return out


def sound_plan(story: dict, narration: dict, segs: list[dict], effects: list[dict] | None = None) -> list[tuple]:
    """Every SFX event of the video: a whoosh ONLY on a planned swoosh transition, a soft click on a UI-like pop
    (dates / evidence / missing), the phone notification when a stated message appears, and event sounds the
    narration describes (event_sfx: footsteps when someone runs, a door when it slams...). Never two
    effects within 1 s of each other; silence is allowed. Music is added later, under the voice."""
    events = []
    last_click, clicks = -100.0, 0
    for k, seg in enumerate(segs):
        shot, at = seg["shot"], float(seg["start"])
        tr = seg.get("transition", "cut")
        if k and tr in ("swoosh", "whip"):
            events.append((max(0.0, at - 0.12), "whoosh", 0.18 if tr == "swoosh" else 0.14, 0.6, {"duck": True}))
        if shot.get("template") == "phone":
            events.append((at + 0.55, "phone_notification", 0.34, 1.2))  # when the bubble lands
        elif tr == "pop" and shot.get("template") in ("evidence", "missing") \
                and at - last_click >= 10.0 and clicks < 3:  # a click on every card is a loop, not a cue
            events.append((at + 0.2, "ui_click", 0.3, 0.4))
            last_click, clicks = at, clicks + 1
    for ev in event_sfx(narration):
        if all(abs(ev[0] - e[0]) >= 1.0 for e in events):
            events.append(ev)
    for e in effects or []:  # the effects' own quiet sounds (ticks, clunk, thud, shutter, typing)
        events += e.get("sfx") or []
    events.sort(key=lambda e: e[0])
    story["explainer_sound_plan"] = [{"at": e[0], "sfx": e[1]} for e in events]
    return events


def render(story: dict, narration: dict, segs: list[dict], workdir: Path, img_dir: Path | None = None):
    """PIL frames -> ffmpeg (4.5 Mbps) + narration/SFX mix, then the optional Remotion editorial pass.
    Returns (mp4, renderer): the renderer's frame_log / used_assets feed the visual QA."""
    total = _total(narration)
    r = Renderer(story, narration, segs, img_dir)
    r.effects = plan_effects(story, narration, segs)
    log("Motion effects: " + (", ".join(f"{e['kind']}@{e['anchor']:.1f}s" for e in r.effects) or "none"))
    events = sound_plan(story, narration, segs, r.effects)
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
        out = polish(out, workdir / "explainer_polished.mp4", segs, narration, FPS, n, accents=r.accents)
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
        # images._virtual_shot stores an absolute origin, not just a filename.
        # Crops and their source are always in the same checkpoint image directory.
        # Resolve by basename to survive checkpoint cache moves between runner workspaces.
        source_name = Path(origin.read_text().strip()).name
        if source_name:
            src = p.with_name(source_name)
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
    body = segs
    dur = lambda s: s["end"] - s["start"]  # noqa: E731
    secs = {"image": 0.0, "graphic": 0.0, "host": 0.0}
    for s in segs:
        secs[s["shot"]["type"]] = secs.get(s["shot"]["type"], 0.0) + dur(s)
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
            "host": [s["shot"].get("asset_id") or s["shot"].get("expression") for s in mine
                     if s["shot"]["type"] == "host"]})
    prov = {}
    for s in body:
        if s["shot"]["type"] == "image" and s["shot"]["file"] not in prov:
            prov[s["shot"]["file"]] = provenance_of(s["shot"]["file"])
    for p in prov.values():
        if p.get("license_problem"):
            fails.append(f"{p['file']}: {p['license_problem']}")
    approved = {r["id"] for r in sprites.approved_registry().get("approved", [])}
    bad = sorted(a for a in set(ren.used_assets) - approved
                 if not (a.startswith("pose:") and sprites.owner_pose_ok(a[5:])))
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
        "shots": {k: sum(1 for s in segs if s["shot"]["type"] == k) for k in ("image", "graphic", "host")},
        "effects": story.get("explainer_effects") or [],
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
        "owner_assets_used": sorted(a[5:] for a in ren.used_assets if a.startswith("pose:")),
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
        if old.get("key") == key and old.get("version") == 3:  # 3 = phrase-aware impact cards, choice, phone
            graphics = old["graphics"]
            log("Explainer graphics: reused from the earlier try (same narration)")
    except (OSError, ValueError, KeyError):
        graphics = None
    if graphics is None:
        graphics = plan_graphics(story, narration)
        checkpoint.write_atomic(saved, json.dumps({"key": key, "version": 3, "graphics": graphics},
                                                  ensure_ascii=False, default=str))
        checkpoint.register_image(saved, stage="shot_list")
    # Older saved plans may hold date cards: dates are now year reels over the picture (plan_effects)
    graphics = [[g for g in gs if g.get("template") != "date_stamp"] for gs in graphics]
    total = _total(narration)
    segs = sequence(story, narration, scene_images, graphics, total)
    story["render_style"] = "explainer"
    video, ren = render(story, narration, segs, workdir, img_dir)
    report = visual_qa(story, segs, ren, video, total)
    if CONFIG.get("whisper_narration_check", False):  # diagnostics only; do not block a complete valid video
        try:
            result = verify_narration(video, narration)
            result["status"] = "checked"
        except Exception as exc:  # missing local model, network, unavailable CPU, FFmpeg/ASR error
            log(f"WHISPER narration check unavailable ({type(exc).__name__}: {str(exc)[:220]}); "
                "continuing the normal production QA and publication")
            result = {"status": "unavailable", "model": "openai/whisper-base",
                      "reason": f"{type(exc).__name__}: {str(exc)[:220]}"}
        report["narration_check"] = story["narration_check"] = result
    write_reports(workdir, report, segs)
    story["explainer_plan"] = {"shots": report["shots"], "runtime_share": report["runtime_share"],
                               "media_used": report["media_used"]}
    log(f"Visual QA: shots {report['shots']}, runtime {report['runtime_share']}, media {report['media_used']}, "
        f"AI {report['ai_images']}" + (f"; exceptions: {report['exceptions']}" if report["exceptions"] else ""))
    if report["failures"]:
        raise VisualQAFailed("; ".join(report["failures"])[:900])
    return video


def verify_narration(video: Path, narration: dict, model: str = "openai/whisper-base") -> dict:
    """What a listener actually hears, checked against the caption words: local Whisper (MIT, free, CPU) transcribes
    the finished video's audio with word timestamps; the narration words are aligned to it. Returns coverage (share
    of caption words heard), timing offsets (heard - captioned start, s) and the caption words that were not heard.
    Report-only (config whisper_narration_check); never blocks a video."""
    import difflib
    from transformers import pipeline as hf_pipeline
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    audio = np.frombuffer(raw, dtype=np.float32)
    asr = hf_pipeline("automatic-speech-recognition", model=model, device="cpu")
    out = asr({"raw": audio, "sampling_rate": 16000}, return_timestamps="word", chunk_length_s=30, batch_size=4)
    heard = [(_bare(c["text"]), float((c.get("timestamp") or (0, 0))[0] or 0.0)) for c in out.get("chunks") or []]
    heard = [h for h in heard if h[0]]
    said = [(_bare(w["word"]), float(w["start"])) for w in narration.get("words") or [] if _bare(w["word"])]
    sm = difflib.SequenceMatcher(a=[w for w, _ in said], b=[w for w, _ in heard], autojunk=False)
    matched, offsets = set(), []
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            matched.add(blk.a + k)
            offsets.append(heard[blk.b + k][1] - said[blk.a + k][1])
    offsets.sort()
    med = offsets[len(offsets) // 2] if offsets else None
    rep_ = {"model": model, "caption_words": len(said), "heard_words": len(heard),
            "coverage": round(len(matched) / max(1, len(said)), 3),
            "median_offset_s": round(med, 3) if med is not None else None,
            "max_abs_offset_s": round(max(abs(o) for o in offsets), 3) if offsets else None,
            "late_or_early_over_0_3s": sum(1 for o in offsets if abs(o) > 0.3),
            "not_heard": [said[k][0] for k in range(len(said)) if k not in matched][:40],
            "transcript": " ".join(c["text"].strip() for c in out.get("chunks") or [])[:2000]}
    log(f"Narration check (Whisper): {rep_['coverage']:.0%} of caption words heard, median offset "
        f"{rep_['median_offset_s']}s, {rep_['late_or_early_over_0_3s']} word(s) off by > 0.3 s")
    return rep_


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
