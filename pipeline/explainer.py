"""EXPERIMENTAL render style "explainer": second-person, problem-by-problem videos with quick cuts between
(a) painted scenes: a moody FLUX background plate (one per location, reused with push-in / pan / close-up crops)
    with the recurring stick-figure "you" cut out on top (assets/character, drawn once: explainer_character.py),
(b) info cards: beige paper, mono kicker, big bold text with ONE accent word and one build-up (counting grid, bars
    against a dashed threshold, counter, arrow, stamp, list), drawn by code (0 neurons),
(c) title cards: black, big white text with one accent word (code).
A HUD (3 stat boxes + an accent chapter chip) sits on painted shots; karaoke captions (1-3 words) in the lower third.

Flow (main.py when render_style is explainer, or explainer_test.py):
  adapt(story)   second-person rewrite of the finished story (true stories: only facts the verified story already
                 has, re-checked with story.fact_check; hook rule; TRUE STORY line)
  fit_duration   (main.py, unchanged)
  build(...)     plan(story, narration) -> painted assets (<= explainer_max_images FLUX images, Cloudflare ledger) ->
                 frame-by-frame render (PIL -> ffmpeg) + narration/SFX mix. Music is added after, as for classic.
Switch: config render_style / explainer_for_modes, or env RENDER_STYLE=explainer. Config stays "classic" until the
owner approves.
"""
import json
import math
import os
import random
import re
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from common import CONFIG, ROOT, env, log

W, H, FPS = 1080, 1920, 30
FONT_DIR = ROOT / "assets" / "fonts" / "explainer"
SHOT_MIN, SHOT_MAX = 1.3, 3.0
# Dark Editorial Noir (Oct 21): INK = bone text on dark grounds, MUTED = parchment labels, BLACK = midnight
PAPER, INK, MUTED, BLACK = (169, 158, 144), (236, 230, 221), (169, 158, 144), (16, 20, 25)
CAP_Y = 1565  # captions are in a reserved strip below the character action stage
BUILD_KINDS = ("grid", "bars", "counter", "arrow", "stamp", "list", "none")


class ExplainerUnavailable(RuntimeError):
    """The explainer style can't run (no character set, nothing planned...)."""


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
- Second person: the viewer is "you". {who}
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
    "true": 'You stand in the shoes of the investigator, the detective or a witness of this REAL case: you see what they '
            'saw, step by step. You are never the victim or a suspect; real people stay third person, by name.',
    "lore": "You are an adult villager or traveller inside the legend as it is told. It is folklore: supernatural claims "
            "are what people believed ('the village believed...'), never stated as fact.",
    "fiction": "You are the adult main character living this story.",
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
    """Second-person explainer rewrite of a finished story (before voicing). Never raises: a failed rewrite keeps
    the story as written (the render style still works on any narration)."""
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
    rules = (f"EXPLAINER style: second person ('you'), {WHO[kind]} {FACTS[kind]} "
             "Problem by problem, concrete numbers, ends on an open question for the viewer.")
    new = st.fix_hook(new, api_key, st.sfx_names(), rules)
    if kind == "true":  # only facts the verified story already had
        new = st.fact_check(new, verified, api_key)
    st.mark_true_story(new)
    st.speak_numbers(new)
    new["explainer_adapted"] = True
    new["explainer_before"] = [sc.get("narration", "") for sc in story["scenes"]]
    words = sum(len(s["narration"].split()) for s in new["scenes"])
    log(f"Explainer rewrite ({kind}): {len(new['scenes'])} scenes, {words} words; opens: "
        f"'{' '.join(new['scenes'][0]['narration'].split()[:14])}...'")
    return new


# ================================================================ planning

PLAN_PROMPT = """You are the storyboard artist of a vertical explainer video for the Night Files channel. Our host
"you" uses the approved round-white-headed, black-suited character with a red tie. People and props
must be grounded in the story, and the character should not change identity between shots. Backgrounds are mostly blank, not forced scenic photographs. Characters act out narration with a single static pose per beat. Turn narration into LITERAL story
beats, like a storyboard: every shot shows exactly WHO does WHAT, WHERE, at that moment.
TRUE STORY: {true}

NARRATION (scene number: text, seconds):
{scenes}

PEOPLE ALREADY KNOWN (name: look): {cast}
PLACES ALREADY KNOWN: {locs}

Return JSON:
{{"cast": [{{"name": "<an adult the narration names>", "look": "<props: hat type, beard, dress, coat colour; max 12 words>"}}],
 "locations": [{{"name": "<short name>", "look": "<18-28 words: the EMPTY place, era, light, mood; no people, no text>"}}],
 "inserts": [{{"name": "<short name>", "prompt": "<one object close-up, no people, no text, max 15 words>"}}],
 "scenes": [{{"shots": [SHOT, ...]}}]}}
one "scenes" entry per narration scene, in order. SHOT is one of:
{{"type": "scene", "at": "<first 2-4 words where this shot starts, copied exactly from the narration>",
  "location": "<a locations name>",
  "primary_subject": "you | <cast name> | none", "primary_action": "<{actions}>", "expression": "<{expressions}>",
  "view": "front | three_quarter | side | back", "facing": "left | right",
  "secondary_subject": "<cast name> | crowd | none", "secondary_action": "<{actions}>",
  "shot_type": "wide | medium | close | over_shoulder",
  "background_motion": "none | subtle_push | subtle_pan | parallax_light",
  "insert": "<an inserts name to show that object close-up instead, or empty>",
  "prop": "none | document | photograph | suitcase | camera | film | map | phone | clock | magnifier | flashlight | key | money | aircraft | vehicle | folder | door",
  "text_mode": "none | location | name | punch | evidence | quote | stamp", "text": "<max 5 words>", "accent": "<one word of text>"}}
{{"type": "card", "at": "...", "kicker": "<MONO KICKER, max 26 chars>", "text": "<max 7 words>", "accent": "<one word>",
  "build": BUILD}}
{{"type": "title", "at": "...", "text": "<max 6 words>", "accent": "<one word of text>"}}
{{"type": "graphic", "at": "...", "template": "<template>", "fields": {{...}}}} where template + fields is one of:
  evidence    {{"kicker": "EXHIBIT A", "text": "<the clue, max 8 words>", "accent": "<one word>", "note": "<max 5 words>"}}
  map_route   {{"kicker": "THE ROUTE", "stops": ["<2-4 place names said in the narration, in travel order>"]}}
  fact        {{"kicker": "<max 3 words>", "value": <a number said>, "prefix": "", "suffix": "", "label": "<max 8 words>", "accent": "<one word>"}}
  filmstrip   {{"kicker": "ARCHIVE", "text": "<max 7 words about film / photos / footage / records>", "accent": "<one word>"}}
  quote       {{"text": "<words someone said, exactly as in the narration>", "by": "<who said it>"}}
  impact      {{"text": "<1-3 words>", "accent": "<one word>"}}
  connections {{"kicker": "CONNECTIONS", "nodes": ["<2-4 people / places / clues said in the narration>"]}}
  compare     {{"kicker": "TWO THEORIES", "left": {{"title": "<max 3 words>", "items": ["<max 5 words>", "..."]}}, "right": {{...}}}}
  missing     {{"subject": "<cast name or you>", "word": "<MISSING | VANISHED | GONE: only a word the narration uses>", "last_seen": "<a place said, or empty>"}}
  closing     {{"kicker": "YOUR CALL", "text": "<the closing question, exactly as in the narration>", "accent": "<one word>"}}
BUILD is one of: {{"kind": "grid", "total": <4-60>, "filled": <n>, "label": "<max 4 words>"}} |
{{"kind": "bars", "bars": [{{"label": "<max 2 words>", "value": <number>}}, ...2-4], "threshold": <number>, "threshold_label": "<max 3 words>"}} |
{{"kind": "counter", "from": <number>, "to": <number>, "prefix": "", "suffix": ""}} |
{{"kind": "arrow", "from": "<max 3 words>", "to": "<max 3 words>"}} | {{"kind": "stamp", "word": "<ONE WORD>"}} |
{{"kind": "list", "items": ["<max 4 words>", "..."]}} | {{"kind": "none"}}
RULES
- STORYBOARD, not decoration. Split every sentence with two actions or two people into separate shots. Example:
  "You notice someone reaching for a folder" = (1) you observing (medium, three_quarter),
  (2) the named person reaching for a document (medium, side), (3) you reacting (close).
- The host ACTS what the words say in STATIC action poses (pointing, inspecting, holding, reacting), never just stands
  around. Vary view (front, three_quarter, side, back) and shot_type. close only for emotional beats (max 1 in 4
  shots); over_shoulder when you watch someone (you seen from behind, they in front of you).
- 3-5 shots per scene, a cut every 1.5-3 s. The first shot of scene 1 is a scene shot.
- background_motion is ALWAYS "none": the blank character stage does not move.
- The prop field is optional. Use a prop only when its object is expressly mentioned or confirmed in the
  narration; use "none" otherwise. Never infer a case-specific object from a vague emotion or setting.
- text_mode on at most 1 shot in 3, words taken from the narration: location = the place name the first time it
  appears; name = a person's name the first time they appear; punch = a key phrase; evidence = a clue; quote = words
  someone said; stamp = 1-2 words. NO dates, years or day counters on scene shots; at most ONE card in the whole
  video may show a date.
- Motion graphics (graphic / card / title) for key numbers, clues, routes, theories and turns: about one shot in three,
  never two in a row. Prefer graphic templates; map_route when people travel between named places; evidence for a
  clue or object; compare when the narration weighs two explanations; missing only when someone vanishes; closing
  only for the final question. Every number and name on a graphic, card or title must be said in the
  narration{true_rule}.
- People: only adults the narration names (or "crowd"); never a real victim's death, body or remains.
- At most {max_locs} locations and {max_inserts} inserts in total; no people, no text, nothing occult, no gore.
"""

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


def plan(story: dict, narration: dict) -> dict:
    """Storyboard on the FINAL narration: literal beats per scene (who does what, where, view, framing), cast with
    props, locations, inserts, text overlays. Invalid pieces are repaired; nothing usable = keyword storyboard."""
    import stickman as sm
    words = narration["words"]
    spans = _scene_spans(story, narration)
    max_locs = int(CONFIG.get("explainer_max_plates", 6))
    max_ins = int(CONFIG.get("explainer_max_inserts", 4))
    narr_all = " ".join(sc.get("narration", "") for sc in story["scenes"])
    scenes_txt = "\n".join(f"{i + 1}: {sc.get('narration', '')} ({spans[i][1] - spans[i][0]:.1f}s)"
                           for i, sc in enumerate(story["scenes"]))
    known = "; ".join(f"{c['name']}: {c.get('look', '')[:80]}" for c in story.get("characters") or [] if c.get("name"))
    true = bool(story.get("true_story"))
    data = _plan_call(PLAN_PROMPT.format(
        true="yes" if true else "no", scenes=scenes_txt, cast=known or "none",
        locs="; ".join(l["name"] for l in story.get("locations") or [] if l.get("name")) or "none",
        actions="|".join(_actions()), expressions="|".join(_expressions()), max_locs=max_locs, max_inserts=max_ins,
        true_rule=" (TRUE story: never invent a number)" if true else "")) or {}
    said = _said_values(story)
    low_all = narr_all.lower()
    cast = {}
    sheet = {c["name"].lower(): c.get("look", "") for c in story.get("characters") or [] if c.get("name")}
    for c in (data.get("cast") or []) + [{"name": n, "look": l} for n, l in sheet.items()]:
        if not isinstance(c, dict) or not c.get("name"):
            continue
        name = str(c["name"]).strip()[:40]
        key = name.lower()
        first = key.split()[-1] if key.split() else key
        if key in cast or key == "you" or _CHILD.search(f"{name} {c.get('look', '')}"):
            continue
        if first not in low_all:  # only people the narration actually names
            continue
        cast[key] = sm.look_for(name, f"{c.get('look', '')} {sheet.get(key, '')}")
    locs = []
    for l in data.get("locations") or []:
        if isinstance(l, dict) and l.get("name") and l.get("look") and len(locs) < max_locs:
            locs.append({"name": str(l["name"])[:40], "look": _clean_visual(str(l["look"]))})
    if not locs:
        locs = [{"name": l["name"], "look": _clean_visual(l.get("look") or l["name"])}
                for l in (story.get("locations") or [])[:max_locs] if l.get("name")]
    if not locs:
        locs = [{"name": "the place", "look": _clean_visual(story.get("setting") or "a dark empty room at night")}]
    loc_names = {l["name"].lower(): l["name"] for l in locs}
    inserts = []
    for x in data.get("inserts") or []:
        if isinstance(x, dict) and x.get("name") and x.get("prompt") and len(inserts) < max_ins:
            inserts.append({"name": str(x["name"])[:40], "prompt": _clean_visual(str(x["prompt"]))[:160]})
    ins_names = {x["name"].lower(): x["name"] for x in inserts}
    raw_scenes = data.get("scenes") if isinstance(data.get("scenes"), list) else []
    ctx = {"said": said, "low": low_all, "cast": cast, "locs": locs, "loc_names": loc_names, "ins": ins_names,
           "dates": 0}
    out_scenes = []
    for i, sc in enumerate(story["scenes"]):
        rs = raw_scenes[i] if i < len(raw_scenes) and isinstance(raw_scenes[i], dict) else {}
        s_words = [w for w in words if w.get("scene") == i]
        shots = [v for v in (_valid_shot(s, s_words, ctx) for s in (rs.get("shots") or [])[:6]) if v]
        if not shots:
            shots = _keyword_shots(sc.get("narration", ""), s_words, ctx, i)
        if i == 0 and shots[0]["type"] != "scene":
            shots.insert(0, _keyword_shots(sc.get("narration", ""), s_words, ctx, i)[0])
        out_scenes.append({"shots": shots})
    _balance(out_scenes)
    _closing(story, narration, out_scenes, ctx)
    p = {"cast": cast, "locations": locs, "inserts": inserts, "scenes": out_scenes}
    used_locs = {s.get("location") for sc in out_scenes for s in sc["shots"] if s["type"] == "scene"}
    used_ins = {s.get("insert") for sc in out_scenes for s in sc["shots"] if s.get("insert")}
    p["locations"] = [l for l in locs if l["name"] in used_locs] or locs[:1]
    p["inserts"] = [x for x in inserts if x["name"] in used_ins]
    counts = {"scene": 0, "card": 0, "title": 0, "graphic": 0}
    for sc in out_scenes:
        for s in sc["shots"]:
            counts[s["type"]] += 1
    log(f"Explainer storyboard ({'LLM' if raw_scenes else 'keyword fallback'}): {counts}, cast "
        f"{[c['name'] for c in cast.values()] or 'host only'}, {len(p['locations'])} location(s), "
        f"{len(p['inserts'])} insert(s)")
    return p


_CHILD = re.compile(r"\b(child|children|kid|kids|boy|girl|baby|toddler|teen\w*|\d{1,2}-year-old)\b", re.IGNORECASE)


def _clean_visual(text: str) -> str:
    import images
    t = images._no_text(re.sub(r"\s+", " ", text)).strip().rstrip(".")
    return re.sub(r"\b(pentagram|sigil|occult|ritual|all-seeing eye|eye of providence|blood|gore|corpse|body)\b",
                  "", t, flags=re.IGNORECASE)


def _said_values(story: dict) -> set:
    import spoken_numbers as nums
    return nums.values(" ".join(sc.get("narration", "") for sc in story["scenes"]))


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


STAGE_PROPS = frozenset(("none", "document", "photograph", "suitcase", "camera", "film",
                         "map", "phone", "clock", "magnifier", "flashlight", "key", "money",
                         "aircraft", "vehicle", "folder", "door"))


def _valid_shot(s, s_words, ctx) -> dict | None:
    import stickman as sm
    if not isinstance(s, dict):
        return None
    kind = str(s.get("type") or "").lower()
    at = _anchor(str(s.get("at") or ""), s_words)
    said, low = ctx["said"], ctx["low"]
    if kind == "scene":
        prim = _subject(s.get("primary_subject"), ctx) if str(s.get("primary_subject") or "").lower() != "none" \
            else ""
        sec = _subject(s.get("secondary_subject"), ctx, allow_crowd=True)
        if sec == prim:
            sec = ""
        acts = set(_actions())
        act = s.get("primary_action") if s.get("primary_action") in acts else "standing"
        act2 = s.get("secondary_action") if s.get("secondary_action") in acts else "standing"
        text_mode = s.get("text_mode") if s.get("text_mode") in ("location", "name", "punch", "evidence", "quote",
                                                                 "stamp") else "none"
        text = re.sub(r"\s+", " ", str(s.get("text") or "")).strip()[:40]
        if text_mode != "none" and not (text and _words_said(text, low) and _number_ok(text, said)
                                        and not _DATE.search(text)):
            text_mode, text = "none", ""
        return {"type": "scene", "at": at,
                "location": ctx["loc_names"].get(str(s.get("location") or "").lower()) or ctx["locs"][0]["name"],
                "insert": ctx["ins"].get(str(s.get("insert") or "").lower(), ""),
                "prop": str(s.get("prop") or "none").lower() if str(s.get("prop") or "none").lower() in STAGE_PROPS else "none",
                "primary": prim, "action": act,
                "expression": s.get("expression") if s.get("expression") in _expressions() else "neutral",
                "view": s.get("view") if s.get("view") in sm.VIEWS else "three_quarter",
                "facing": "left" if s.get("facing") == "left" else "right",
                "secondary": sec, "action2": act2,
                "shot_type": s.get("shot_type") if s.get("shot_type") in ("wide", "medium", "close",
                                                                          "over_shoulder") else "wide",
                "motion": s.get("background_motion") if s.get("background_motion") in (
                    "subtle_push", "subtle_pan", "parallax_light") else "none",
                "text_mode": text_mode, "text": text, "accent": str(s.get("accent") or "")}
    if kind == "graphic":
        return _valid_graphic(s, at, ctx)
    if kind == "title":
        text = str(s.get("text") or "").strip()[:48]
        if not text or not _number_ok(text, said) or not _date_ok(text, ctx):
            return None
        return {"type": "title", "at": at, "text": text, "accent": str(s.get("accent") or "")}
    if kind != "card":
        return None
    text = str(s.get("text") or "").strip()[:60]
    kicker = str(s.get("kicker") or "").strip().upper()[:28]
    if not text or not _number_ok(text + " " + kicker, said) or not _date_ok(f"{text} {kicker}", ctx):
        return None
    b = s.get("build") if isinstance(s.get("build"), dict) else {}
    return {"type": "card", "at": at, "kicker": kicker, "text": text, "accent": str(s.get("accent") or ""),
            "build": _valid_build(b, said)}


def _actions() -> list[str]:
    import sprites
    import stickman as sm
    return sorted(set(sm.ACTIONS) | set(sprites.actions()))


def _expressions() -> list[str]:
    import sprites
    import stickman as sm
    return sorted(set(sm.EXPRESSIONS) | set(sprites.expressions()))


GRAPHIC_TEXT = {"evidence": ("text", "note"), "fact": ("label",), "filmstrip": ("text",), "quote": ("text", "by"),
                "impact": ("text",), "closing": ("text",)}


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


def _balance(scenes: list[dict]) -> None:
    """Close-ups max 1 in 4 scene shots, background motion max 1 in 4 (the rest stays still)."""
    shots = [s for sc in scenes for s in sc["shots"] if s["type"] == "scene"]
    closes = moving = 0
    for k, s in enumerate(shots):
        if s["shot_type"] == "close":
            closes += 1
            if closes > max(1, (k + 1) // 4):
                s["shot_type"] = "medium"
        if s["motion"] != "none":
            moving += 1
            if moving > max(1, (k + 1) // 4):
                s["motion"] = "none"
    for a, b in zip(shots, shots[1:]):  # never the same framing of the same person twice in a row
        if (a["primary"], a["view"], a["shot_type"]) == (b["primary"], b["view"], b["shot_type"]):
            b["view"] = {"front": "three_quarter", "three_quarter": "side", "side": "front",
                         "back": "three_quarter"}[b["view"]]


def _valid_build(b: dict, said: set) -> dict:
    def num(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    def ok(v):
        return v is not None and (v <= 3 or v in said)
    kind = b.get("kind") if b.get("kind") in BUILD_KINDS else "none"
    if kind == "grid":
        total, filled = num(b.get("total")), num(b.get("filled"))
        if total and 4 <= total <= 60 and filled is not None and 0 <= filled <= total and (ok(total) or ok(filled)):
            return {"kind": "grid", "total": int(total), "filled": int(filled), "label": str(b.get("label") or "")[:28]}
    elif kind == "bars":
        bars = [{"label": str(x.get("label") or "")[:14], "value": num(x.get("value"))}
                for x in b.get("bars") or [] if isinstance(x, dict)]
        bars = [x for x in bars if x["value"] is not None and x["value"] >= 0 and ok(x["value"])][:4]
        thr = num(b.get("threshold"))
        if len(bars) >= 2:
            return {"kind": "bars", "bars": bars, "threshold": thr if ok(thr) else None,
                    "threshold_label": str(b.get("threshold_label") or "")[:20]}
    elif kind == "counter":
        a, z = num(b.get("from")) or 0.0, num(b.get("to"))
        if ok(z) and (a <= 3 or ok(a)) and not (z and 1000 <= z <= 2100):  # a year is not a counter
            return {"kind": "counter", "from": a, "to": z, "prefix": str(b.get("prefix") or "")[:2],
                    "suffix": str(b.get("suffix") or "")[:8]}
    elif kind == "arrow" and b.get("from") and b.get("to"):
        if _number_ok(f"{b['from']} {b['to']}", said):
            return {"kind": "arrow", "from": str(b["from"])[:24], "to": str(b["to"])[:24]}
    elif kind == "stamp" and b.get("word"):
        w = re.sub(r"[^A-Za-z!?'-]", "", str(b["word"])).upper()[:16]
        if w:
            return {"kind": "stamp", "word": w}
    elif kind == "list":
        items = [str(x)[:30] for x in b.get("items") or [] if str(x).strip()][:3]
        if items and _number_ok(" ".join(items), said):
            return {"kind": "list", "items": items}
    return {"kind": "none"}


_ACTION_WORDS = [("running", r"\b(run|ran|running|chase|flee|fled|escape)"), ("walking", r"\b(walk|follow|head|went|go)"),
                 ("boarding", r"\b(board|boarded|boards|embark)"), ("pointing", r"\b(look at|there|this|clue|notice)"),
                 ("observing", r"\b(watch|see|saw|look|stare)"), ("reaching", r"\b(find|found|pick|grab|open)"),
                 ("thinking", r"\b(think|wonder|why|theor|question|what would)"), ("waiting", r"\b(wait|hours|days)"),
                 ("holding", r"\b(hold|holding|carry|carried|grip|grasp)"), ("reacting", r"\b(gone|vanish|disappear|never)"),
                 ("seated", r"\b(sit|sat|desk|court)")]
_EXPR_WORDS = [("shocked", r"\b(gone|vanish|disappear|impossible|never|nobody|no one|dead)"),
               ("scared", r"\b(scream|terrif|afraid|fear)"), ("worried", r"\b(missing|search|wait|worr)"),
               ("curious", r"\b(why|what|how|wonder|theor)"), ("determined", r"\b(you check|decide|first|follow)")]


def _action_for(text: str) -> str:
    return next((a for a, rx in _ACTION_WORDS if re.search(rx, text, re.IGNORECASE)), "observing")


def _expr_for(text: str) -> str:
    return next((e for e, rx in _EXPR_WORDS if re.search(rx, text, re.IGNORECASE)), "neutral")


def _keyword_shots(narr: str, s_words: list[dict], ctx: dict, i: int) -> list[dict]:
    loc = ctx["locs"][i % len(ctx["locs"])]["name"]
    first = " ".join(re.split(r"[.,!?;:]", narr)[0].split()[:6])
    half = narr[len(narr) // 2:]
    other = next((k for k in ctx["cast"] if k.split()[-1] in narr.lower()), "")
    base = {"type": "scene", "location": loc, "insert": "", "prop": "none", "secondary": "", "action2": "standing", "motion": "none",
            "text_mode": "none", "text": "", "accent": ""}
    shots = [dict(base, at=s_words[0]["start"] if s_words else None, primary="you", action=_action_for(narr),
                  expression=_expr_for(narr), view="three_quarter", facing="right", shot_type="wide")]
    if other:
        shots.append(dict(base, at=None, primary=other, action=_action_for(half), expression="neutral", view="side",
                          facing="left", shot_type="wide"))
    elif _number_ok(first, ctx["said"]) and _date_ok(first, ctx):
        shots.append({"type": "title", "at": None, "text": first, "accent": ""})
    shots.append(dict(base, at=None, primary="you", action=_action_for(half), expression=_expr_for(half),
                      view="front", facing="left", shot_type="medium"))
    return shots


# ================================================================ timeline

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


def timeline(story: dict, narration: dict, p: dict) -> list[dict]:
    """Segments {start, end, shot, scene}: the opener, then the storyboard shots at their anchor words, every
    segment 1.3-3 s (long beats are split into the next beat / framing)."""
    spans = _scene_spans(story, narration)
    words = narration["words"]
    segs = []
    for i, (a, b) in enumerate(spans):
        shots = p["scenes"][i]["shots"]
        n = len(shots)
        times = []
        for k, s in enumerate(shots):
            t = s.get("at")
            if k == 0:
                t = a
            elif t is None or not a < t < b:
                t = a + (b - a) * k / n
            times.append(t)
        order = sorted(range(n), key=lambda k: times[k])
        merged = []
        for t, s in [(times[k], shots[k]) for k in order]:
            if merged and t - merged[-1][0] < SHOT_MIN:
                continue
            merged.append((t, s))
        if len(merged) > 1 and b - merged[-1][0] < SHOT_MIN:
            merged.pop()
        for k, (t, s) in enumerate(merged):
            end = merged[k + 1][0] if k + 1 < len(merged) else b
            segs.extend(_split(t, end, s, i, words, p))
    t_true, t_title = opener_length(story)
    if t_title:
        segs = [s for s in segs if s["end"] - t_title >= SHOT_MIN or s["start"] >= t_title]
        for s in segs:
            s["start"] = max(s["start"], t_title)
        head = []
        if t_true:
            head.append({"start": 0.0, "end": t_true, "shot": {"type": "opener"}, "scene": 0})
        head.append({"start": t_true, "end": t_title, "shot": {"type": "opener_title"}, "scene": 0})
        segs = head + segs
    return segs


def _split(t0: float, t1: float, shot: dict, scene: int, words: list[dict], p: dict) -> list[dict]:
    if t1 - t0 <= SHOT_MAX + (1.4 if shot.get("type") == "graphic" else 0.2):  # a graphic may hold ~4 s
        return [{"start": t0, "end": t1, "shot": shot, "scene": scene}]
    n = math.ceil((t1 - t0) / SHOT_MAX)
    cuts = [t0]
    for k in range(1, n):  # snap to a word start near the even split
        want = t0 + (t1 - t0) * k / n
        near = [w["start"] for w in words if t0 + SHOT_MIN < w["start"] < t1 - SHOT_MIN]
        cuts.append(min(near, key=lambda x: abs(x - want)) if near else want)
    cuts = sorted(set(cuts)) + [t1]
    return [{"start": cuts[k], "end": cuts[k + 1], "shot": shot if k == 0 else _variant(shot, k, scene, p),
             "scene": scene} for k in range(len(cuts) - 1)]


def _variant(shot: dict, k: int, scene: int, p: dict) -> dict:
    """The next beat of a long moment: the other person's side of it, or the host from another angle; after a card
    or title, the scene's host shot again."""
    if shot["type"] == "scene" and not shot.get("insert"):
        if shot.get("secondary") and shot["secondary"] != "crowd" and k % 2:
            return dict(shot, primary=shot["secondary"], action=shot.get("action2", "standing"), secondary="",
                        view="side" if shot["view"] != "side" else "three_quarter", shot_type="wide",
                        text_mode="none", variant=k)
        nxt = {"wide": "medium", "medium": "close" if k % 3 == 2 else "wide", "close": "medium",
               "over_shoulder": "medium"}[shot["shot_type"]]
        view = {"front": "three_quarter", "three_quarter": "front", "side": "three_quarter",
                "back": "three_quarter"}[shot["view"]]
        return dict(shot, shot_type=nxt, view=view, motion="none", text_mode="none", variant=k)
    base = next((s for s in p["scenes"][scene]["shots"] if s["type"] == "scene" and not s.get("insert")), None)
    if base:
        return dict(base, shot_type="medium", view="front", text_mode="none", motion="none", variant=k)
    return {"type": "scene", "location": p["locations"][0]["name"], "insert": "", "primary": "you",
            "action": "thinking", "expression": "curious", "view": "front", "facing": "right", "secondary": "",
            "action2": "standing", "shot_type": "medium", "motion": "none", "text_mode": "none", "text": "",
            "accent": "", "variant": k}


# ================================================================ painted assets

class Budget:
    """Cloudflare images for ONE video, counted across retries (img_dir/explainer_images.json): `soft` new images
    by default (config explainer_new_images, 2), never more than `hard` calls incl. QA redraws (explainer_max_images,
    4). Everything else comes from the asset library, this story's earlier plates or local noir grounds."""

    def __init__(self, img_dir: Path):
        self.path = img_dir / "explainer_images.json"
        try:
            self.state = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.state = {"new": 0, "calls": 0}
        self.soft = int(CONFIG.get("explainer_new_images", 2))
        self.hard = max(self.soft, int(CONFIG.get("explainer_max_images", 4)))

    def can_start(self) -> bool:
        return self.state["new"] < self.soft and self.state["calls"] < self.hard

    def can_retry(self) -> bool:
        return self.state["calls"] < self.hard

    def call(self) -> None:
        self.state["calls"] += 1
        self.save()

    def drawn(self) -> None:
        self.state["new"] += 1
        self.save()

    def save(self) -> None:
        self.path.write_text(json.dumps(self.state))


def _draw(prompt: str, dest: Path, budget: Budget) -> Path | None:
    import cf_budget
    import images
    if images._STATE.get("cf_out") or not env("CLOUDFLARE_API_TOKEN", required=False):
        return None
    if images.test_mode() and not cf_budget.test_allowed():
        log(f"Explainer: today's Cloudflare test share is used up ({cf_budget.line()}); {dest.name} not drawn")
        return None
    budget.call()
    try:
        images._save_valid(images._cloudflare(prompt[:2000], random.randint(1, 10 ** 6)), dest)
        return dest
    except Exception as e:  # noqa: BLE001
        log(f"Explainer: {dest.name} draw failed ({str(e)[:160]})")
        return None


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:40] or "x"


def _overlap(a: str, b: str) -> float:
    wa = {w for w in _norm_words(a) if w not in STOP and len(w) > 2}
    wb = {w for w in _norm_words(b) if w not in STOP and len(w) > 2}
    return len(wa & wb) / max(1, min(len(wa), len(wb)))


def _from_library(story: dict, look: str, dest: Path, taken: set) -> str:
    """A painted place from the asset library (earlier videos' QA-passed pictures) that matches this location:
    not character-specific, same interior/exterior and era, CLIP similarity >= asset_min_similarity, then an
    'empty place, no people' check. Returns the asset id or ''. Never raises."""
    if not CONFIG.get("asset_library", True):
        return ""
    try:
        import images
        import library
        idx = library.load_index()
        era = library.era_of(story)
        inside = "exterior" if library._OUTDOOR.search(look) else "interior"
        pool = [a for a in idx.get("assets", []) if a.get("style") == "painted" and not a.get("character_specific")
                and a.get("kind") == "image" and a["id"] not in taken and a.get("setting") == inside
                and (a.get("era") == era or "any" in (a.get("era"), era)) and a.get("embedding")]
        if not pool:
            return ""
        q = library.embed_text(look)
        thr = float(CONFIG.get("asset_min_similarity", 0.27))
        for sim, a in sorted(((float(q @ library._unpack(a["embedding"])), a) for a in pool), key=lambda x: -x[0])[:3]:
            if sim < thr:
                break
            raw = library.LOCAL / a["file"]
            if not raw.exists() and not library._store().get(a["file"], raw):
                continue
            used = a.get("uses", [])
            grade = next((g for g in library.GRADES if g not in {u.get("grade") for u in used}), "base")
            library._variant(raw, dest, "center", grade, False)
            v, why = images.check_image(dest, f"{look}; an EMPTY place: NO if any person or figure is visible")
            if v is False:
                dest.unlink(missing_ok=True)
                continue
            taken.add(a["id"])
            return a["id"]
    except Exception as e:  # noqa: BLE001
        log(f"Explainer: asset library not used ({type(e).__name__}: {str(e)[:120]})")
    return ""


def make_assets(story: dict, p: dict, img_dir: Path) -> dict:
    """Backgrounds for the storyboard's places, cheapest first: (1) this story's own plates from an earlier try
    (a text-only or animation-only retry never redraws), (2) the asset library, (3) a NEW Cloudflare image while the
    per-video budget allows (Budget), (4) another plate of this video, flipped and regraded, (5) a local noir ground.
    Inserts (object close-ups) only from what's left of the budget; without one the shot shows the host instead."""
    import images
    img_dir.mkdir(parents=True, exist_ok=True)
    if CONFIG.get("explainer_character_stage", True):
        # Character-first stage never pays for or forces AI location paintings.
        story["explainer_assets"] = {"new": 0, "story_reused": 0, "library": 0, "shared": 0,
                                      "local": 1, "cloudflare_calls": 0, "new_total": 0}
        log("Explainer: static character action on blank stage, zero Cloudflare images")
        return {"plates": {}, "inserts": {}}
    budget = Budget(img_dir)
    style = CONFIG.get("explainer_plate_style") or (
        "moody cinematic digital painting, dark noir palette, deep shadows, muted desaturated colours, soft "
        "painterly brushwork, atmospheric haze, empty scene, no people, no text, no signs, no letters")
    era = (story.get("setting") or "")[:80]
    plates, inserts = {}, {}
    stats = {"new": 0, "story_reused": 0, "library": 0, "shared": 0, "local": 0}
    usage = {}
    for sc in p["scenes"]:
        for s in sc["shots"]:
            if s.get("type") == "scene":
                usage[s.get("location")] = usage.get(s.get("location"), 0) + 1
    locs = sorted(p["locations"], key=lambda l: -usage.get(l["name"], 0))
    mine = {f: json.loads(f.with_suffix(".json").read_text()).get("look", "")
            for f in img_dir.glob("x_plate_*.png") if f.with_suffix(".json").exists()}
    taken: set = set()
    for l in locs:
        name, look = l["name"], l["look"]
        dest = img_dir / f"x_plate_{_slug(name)}.png"
        if dest.exists():
            plates[name] = dest
            stats["story_reused"] += 1
            continue
        best = max(mine, key=lambda f: _overlap(look, mine[f]), default=None)
        if best is not None and best not in plates.values() and _overlap(look, mine[best]) >= 0.34:
            plates[name] = best  # same story, the storyboard renamed the place: never redraw it
            stats["story_reused"] += 1
            continue
        if _from_library(story, look, dest, taken):
            plates[name] = dest
            stats["library"] += 1
            dest.with_suffix(".json").write_text(json.dumps({"look": look, "source": "library"}))
            continue
        prompt = f"{style}, {look}" + (f", {era}" if era else "") + ", wide establishing view, vertical composition"
        got = None
        attempt = 0
        while (budget.can_start() if attempt == 0 else budget.can_retry()) and attempt < 2:
            if not _draw(prompt, dest, budget):
                break
            v, why = images.check_image(dest, f"{name}: {look[:200]}; NO if any people, letters, words or writing "
                                              "are visible")
            log(f"Explainer plate '{name}' (draw {attempt + 1}): QA {'YES' if v else 'NO' if v is False else 'skipped'}"
                + (f" ({why})" if why else ""))
            attempt += 1
            if v is not False:
                got = dest
                break
            dest.rename(dest.with_suffix(f".rejected{attempt}.png"))
        if got:
            budget.drawn()
            plates[name] = got
            stats["new"] += 1
            dest.with_suffix(".json").write_text(json.dumps({"look": look, "source": "cloudflare",
                                                             "qa": "PASS" if v else "SKIPPED"}))
            continue
        looks = {**mine, **{f: x["look"] for f, x in ((plates[n], l) for l in locs for n in [l["name"]]
                                                          if n in plates)}}
        other = max((f for f in plates.values() if "_local" not in f.name), key=lambda f: _overlap(look, looks.get(f, "")),
                    default=None)
        if other is not None and _overlap(look, looks.get(other, "")) >= 0.25:  # only a place that fits  # another place of this video, mirrored + regraded so it reads as a new angle
            var = img_dir / f"x_plate_{_slug(name)}_shared.png"
            im = ImageOps.mirror(Image.open(other).convert("RGB"))
            ImageEnhance.Brightness(ImageEnhance.Color(im).enhance(0.7)).enhance(0.85).save(var)
            plates[name] = var
            stats["shared"] += 1
        else:
            plates[name] = _local_plate(img_dir / f"x_plate_{_slug(name)}_local.png", len(plates))
            stats["local"] += 1
    for x in p["inserts"]:
        dest = img_dir / f"x_insert_{_slug(x['name'])}.png"
        if dest.exists():
            inserts[x["name"]] = dest
            continue
        if not budget.can_start():
            continue
        prompt = f"{style}, close-up of {x['prompt']}, shallow depth of field, no hands, no people"
        if _draw(prompt, dest, budget):
            v, why = images.check_image(dest, f"{x['prompt']}; NO if any people, letters or writing are visible")
            if v is False:
                dest.unlink(missing_ok=True)
                continue
            budget.drawn()
            inserts[x["name"]] = dest
            stats["new"] += 1
    stats["cloudflare_calls"] = budget.state["calls"]
    stats["new_total"] = budget.state["new"]
    story["explainer_assets"] = stats
    log(f"Explainer images: {budget.state['new']} new (cap {budget.soft}, {budget.state['calls']}/{budget.hard} "
        f"Cloudflare calls), {stats['library']} from the asset library, {stats['story_reused']} kept from an earlier "
        f"try, {stats['shared']} shared, {stats['local']} local noir")
    return {"plates": plates, "inserts": inserts}


def _local_plate(dest: Path, k: int) -> Path:
    """No image budget left: a local noir ground (dark paper, soft light, a faint horizon of fog)."""
    import noir
    im = noir.ground(noir.tone_for(k), 11 + k).convert("RGB")
    d = ImageDraw.Draw(im, "RGBA")
    for j in range(6):  # low fog bands
        y = 1250 + j * 70
        d.rectangle((0, y, W, y + 60), fill=(200, 200, 210, 6 + 3 * j))
    im.filter(ImageFilter.GaussianBlur(2)).save(dest)
    return dest


def record_plates(story: dict, img_dir: Path) -> None:
    """After the video entered the buffer: its NEW, QA-passed Cloudflare plates go into the asset library so later
    videos reuse them instead of spending neurons. Never raises."""
    if not CONFIG.get("asset_library", True):
        return
    try:
        import hashlib
        import library
        idx = library.load_index()
        if library._STATE.get("readonly"):
            return
        have = {a["id"] for a in idx.get("assets", [])}
        added = 0
        for f in img_dir.glob("x_plate_*.png"):
            side = f.with_suffix(".json")
            meta = json.loads(side.read_text()) if side.exists() else {}
            if meta.get("source") != "cloudflare" or meta.get("qa") != "PASS":
                continue
            aid = hashlib.sha1(f.read_bytes()).hexdigest()[:16]
            if aid in have:
                continue
            jpg = library.LOCAL / f"{aid}.jpg"
            Image.open(f).convert("RGB").save(jpg, quality=90)
            library._store().put(f"{aid}.jpg", jpg)
            look = meta.get("look", "")
            idx.setdefault("assets", []).append({
                "id": aid, "file": f"{aid}.jpg", "poster": f"{aid}.jpg", "kind": "image", "source": "cloudflare",
                "license": "AI-generated (Night Files)", "description": look, "tags": _norm_words(look)[:12],
                "style": "painted", "setting": "exterior" if library._OUTDOOR.search(look) else "interior",
                "era": library.era_of(story), "subjects": [], "character_specific": False,
                "story_id": story.get("story_id", ""), "mode": story.get("mode"),
                "embedding": library._pack(library.embed_image(f)), "times_used": 1, "last_used_video":
                story.get("story_id", ""), "last_used_seq": idx.get("seq", 0), "uses": [], "explainer_plate": True})
            added += 1
        if added:
            library.save_index()
            log(f"Asset library: +{added} explainer plate(s) for later videos")
    except Exception as e:  # noqa: BLE001
        log(f"Asset library not updated with explainer plates ({type(e).__name__}: {str(e)[:160]})")


def _gradient_plate(dest: Path) -> Path:
    y = np.linspace(0, 1, 1024)[:, None]
    top, bot = np.array([18, 30, 40]), np.array([6, 8, 12])
    arr = (top * (1 - y) + bot * y)[:, None, :].repeat(1024, axis=1)
    Image.fromarray(arr.astype("uint8").reshape(1024, 1024, 3)).save(dest)
    return dest


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


def _back(x: float) -> float:
    """Ease-out with a small overshoot (pop)."""
    x = max(0.0, min(1.0, x))
    c = 1.9
    return 1 + (c + 1) * (x - 1) ** 3 + c * (x - 1) ** 2


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


def _is_accent(word: str, acc: str) -> bool:
    a = re.sub(r"[^a-z0-9]", "", acc.lower())
    return bool(a) and re.sub(r"[^a-z0-9]", "", word.lower()) == a


def _fmt(v: float) -> str:
    return f"{int(round(v)):,}" if abs(v - round(v)) < 1e-6 or abs(v) >= 100 else f"{v:.1f}"


# ================================================================ renderer

class Renderer:
    def __init__(self, story: dict, narration: dict, p: dict, assets: dict, segs: list[dict]):
        import stickman
        self.sm = stickman
        self.story, self.narr, self.p, self.assets, self.segs = story, narration, p, assets, segs
        self.acc = accent()
        self.plate_cache: dict = {}
        self.layer_cache: dict = {}
        self.groups = _caption_groups(narration["words"])
        self.paper = self._paper()
        self.spans = _scene_spans(story, narration)
        self.static: dict = {}  # still backgrounds, one per segment
        self.t_true, self.t_title = opener_length(story)

    def look(self, who: str) -> dict:
        if who == "you":
            return self.sm.HOST
        return self.p["cast"].get(who) or self.sm.look_for(who)

    def figure(self, who, action, expr, view, facing, t, height, alpha=1.0):
        import sprites
        if CONFIG.get("explainer_character_stage", True):
            # Approved M01-M04 images are the source of truth for neutral/idle whole-body views.
            # No added halo or recolor: the original red aura has already been approved.
            original = (sprites.approved_full_body(view, height, facing)
                        if who == "you" and action in ("standing", "waiting") else None)
            if original is not None:
                im, foot = original
            else:
                # Unapproved action poses use the temporary procedural stage rig until
                # their individual P-series PNG replacements arrive.
                pose_t = 0.15 if action in self.sm.MOVING else 0.0
                im, foot = self.sm.draw(self.look(who), action, expr, view, facing, pose_t, height, False)
                im = sprites.rim_native(im)
        else:
            blink = (t % 3.7) < 0.12
            tq = round(t * 15) / 15 if action in self.sm.MOVING or action in ("reacting", "scared", "turning") else \
                round(t * 5) / 5
            got = sprites.draw(who, self.look(who), action, expr, view, facing, t, height) if sprites.available() \
                else None
            im, foot = got or self.sm.draw(self.look(who), action, expr, view, facing, tq, height, blink)
        if alpha < 1:
            im = im.copy()
            im.putalpha(im.getchannel("A").point(lambda a: int(a * alpha)))
        return im, foot

    # ---------------------------------------------------------------- scene shots
    def scene_frame(self, seg: dict, t: float) -> Image.Image:
        s = seg["shot"]
        dur = seg["end"] - seg["start"]
        x = t / max(dur, 0.01)
        if s.get("insert") and s["insert"] in self.assets["inserts"]:
            base = self._plate(self.assets["inserts"][s["insert"]], 1.12)
            frame = self._crop(base, 0.5, 0.5, 1.0 + (0.05 * _ease(x) if s.get("motion") != "none" else 0.0))
            frame.alpha_composite(self._vignette())
            self.overlay(frame, s, t, None)
            return frame
        frame = self._background(seg, x)
        st = s.get("shot_type", "wide")
        prim, sec = s.get("primary") or "", s.get("secondary") or ""
        move = 0.0
        target = None
        if sec == "crowd":  # passengers / villagers: small grey figures behind
            for k, fx in enumerate((0.16, 0.36, 0.62, 0.84)):
                im, (fxp, fyp) = self.figure("crowd", "standing" if k % 2 else "walking", "neutral",
                                             "side" if k % 2 else "three_quarter", "left" if k % 2 else "right",
                                             t + k, 470, alpha=0.55)
                self._paste(frame, im, int(W * fx - fxp), int(1520 - fyp))
        if st == "over_shoulder" and prim:  # the watched person small in front, "you" big from behind
            if sec and sec != "crowd":
                im, (fxp, fyp) = self.figure(sec, s.get("action2", "standing"), "neutral", "three_quarter", "left",
                                             t, 640)
                gx = W * 0.66 + self._travel(s.get("action2"), "left", x) * 0.6
                self._paste(frame, self._shadow(int(im.width * 0.5)), int(gx - im.width * 0.25), 1590 - 30)
                self._paste(frame, im, int(gx - fxp), int(1600 - fyp))
                target = (gx, 1600 - 600)
            actor_h = 900 if CONFIG.get("explainer_character_stage", True) else 1500
            im, (fxp, fyp) = self.figure(prim, s.get("action", "standing"), s.get("expression", "neutral"), "back",
                                         "right", t, actor_h)
            feet_y = 1380 if CONFIG.get("explainer_character_stage", True) else 2250
            self._paste(frame, im, int(W * 0.2 - fxp), int(feet_y - fyp))
        else:
            spots = []
            if prim and sec and sec != "crowd" and st == "wide":
                spots = [(prim, s.get("action"), s.get("expression"), s.get("view"), s.get("facing", "right"), 0.31),
                         (sec, s.get("action2"), "neutral", "three_quarter",
                          "left" if s.get("facing", "right") == "right" else "right", 0.71)]
            elif prim:
                spots = [(prim, s.get("action"), s.get("expression"), s.get("view"), s.get("facing", "right"), 0.5)]
            elif sec and sec != "crowd":
                spots = [(sec, s.get("action2"), "neutral", "three_quarter", "left", 0.5)]
            height, feet = ({"wide": (690, 1300), "medium": (940, 1365), "close": (1190, 1390)}
                            if CONFIG.get("explainer_character_stage", True)
                            else {"wide": (820, 1660), "medium": (1150, 1980), "close": (1500, 2150)}).get(st, (690, 1300))
            if st == "close" and len(spots) == 1 and spots[0][0] == "you" and spots[0][1] not in self.sm.MOVING:
                import sprites  # the owner's hi-res head-and-shoulders pack: sharp emotional close-ups
                if CONFIG.get("explainer_character_stage", True):
                    # Cropped straight from the SAME rig used for all full-body action poses.
                    im = sprites.stage_closeup(spots[0][2] or "neutral", spots[0][3] or "front")
                    im = im.resize((1030, 1288), Image.Resampling.LANCZOS)
                    if spots[0][4] == "left":
                        im = ImageOps.mirror(im)
                    self._paste(frame, im, int(W / 2 - im.width / 2), 38)
                    spots = []
                else:
                    cu = sprites.closeup(spots[0][2] or "neutral", spots[0][3] or "front")
                    if cu:
                        w0 = int(1150 * (1.0 + 0.015 * math.sin(t * 2.4)))
                        im = sprites.closeup_image(str(cu), w0)
                        if spots[0][4] == "left":
                            im = ImageOps.mirror(im)
                        self._paste(frame, im, int(W / 2 - im.width / 2),
                                    int(1880 - im.height + 6 * math.sin(t * 2.4)))
                        spots = []
            for who, act, expr, view, facing, fx in spots:
                act = act or "standing"
                move = 0.0 if CONFIG.get('explainer_character_stage', True) else self._travel(act, facing, x)
                if len(spots) == 1 and act in self.sm.MOVING and not CONFIG.get('explainer_character_stage', True):
                    fx = 0.5 - (0.22 if facing == "right" else -0.22) * (1 if st == "wide" else 0.4)
                im, (fxp, fyp) = self.figure(who, act, expr or "neutral", view or "front", facing, t, height,
                                             alpha=1.0 if CONFIG.get('explainer_character_stage', True) else self._exit_alpha(act, x))
                px = W * fx + move * (1 if st == "wide" else 0.5)
                if act == "leaving" and not CONFIG.get("explainer_character_stage", True):  # legacy animated exit
                    k = 1 - 0.25 * _ease(x)
                    im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.BILINEAR)
                    fxp, fyp = fxp * k, fyp * k
                    feet_y = feet - 120 * _ease(x)
                else:
                    feet_y = feet
                if st == "wide":
                    sh = self._shadow(int(height * 0.42))
                    self._paste(frame, sh, int(px - sh.width / 2), int(feet_y - sh.height / 2))
                self._paste(frame, im, int(px - fxp), int(feet_y - fyp))
                if who != "you" and target is None:
                    target = (px, feet_y - height * 0.95)
        if CONFIG.get("explainer_character_stage", True):
            self._stage_context(frame, s, seg)
        else:
            frame.alpha_composite(self._vignette())
        self.overlay(frame, s, t, target)
        return frame

    def _stage_context(self, frame: Image.Image, shot: dict, seg: dict) -> None:
        """Minimal contextual cue plus single schematic prop. The actor does the storytelling."""
        scs = self.story.get("scenes") or []
        words = scs[min(seg["scene"], len(scs) - 1)].get("narration", "").lower() if scs else ""
        if any(k in words for k in ("compartment", "carriage", "passenger")):
            cue, prop = "TRAIN COMPARTMENT", "train"
        elif any(k in words for k in ("luggage", "baggage", "trunk", "belongings")):
            cue, prop = "MISSING LUGGAGE", "case"
        elif any(k in words for k in ("roundhay", "garden", "footage", "film that lasts")):
            cue, prop = "ROUNDHAY FOOTAGE", "film"
        elif any(k in words for k in ("train", "paris", "station", "railway")):
            cue, prop = "THE TRAIN", "train"
        elif any(k in words for k in ("camera", "inventor", "lens", "workshop", "negative")):
            cue, prop = "THE INVENTOR", "camera"
        else:
            cue, prop = "THE EVIDENCE", "file"
        close = shot.get("shot_type") == "close"
        key = ("stage-cue", cue, close)
        layer = self.layer_cache.get(key)
        if layer is None:
            layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            d = ImageDraw.Draw(layer)
            col, hot = (210, 221, 235, 200), self.acc + (255,)
            # Deliberate editorial margins: actor centre, evidence prop at upper right,
            # captions in their own bottom strip. No painted scenery.
            d.rounded_rectangle((66, 215, 552, 281), radius=14, fill=(16, 21, 28, 230))
            d.rectangle((75, 229, 84, 266), fill=hot)
            d.text((102, 231), cue, font=font("mono", 26), fill=(243, 244, 245, 255))
            if close:
                pass  # the face fills the frame, so hide the contextual prop
            elif prop == "film":
                d.rounded_rectangle((794, 468, 997, 608), radius=12, outline=col, width=7)
                for yy in (486, 539, 584):
                    for xx in (804, 971):
                        d.rectangle((xx, yy, xx + 16, yy + 14), outline=col, width=3)
                d.line((845, 491, 949, 581), fill=hot, width=8)
            elif prop == "train":
                d.rounded_rectangle((791, 468, 995, 670), radius=22, outline=col, width=8)
                for xx in (816, 909):
                    d.rectangle((xx, 503, xx + 61, 558), outline=col, width=5)
                d.line((807, 606, 971, 606), fill=hot, width=8)
                for xx in (827, 952):
                    d.ellipse((xx - 22, 648, xx + 22, 692), outline=col, width=7)
            elif prop == "case":
                d.rounded_rectangle((803, 527, 991, 680), radius=15, outline=col, width=8)
                d.arc((856, 476, 942, 548), 183, 358, fill=hot, width=9)
                d.line((808, 592, 985, 592), fill=col, width=5)
            elif prop == "camera":
                d.rounded_rectangle((795, 520, 991, 659), radius=14, outline=col, width=8)
                d.ellipse((847, 536, 934, 623), outline=hot, width=8)
                d.line((844, 659, 794, 754), fill=col, width=8)
                d.line((937, 659, 983, 754), fill=col, width=8)
            else:
                d.rounded_rectangle((821, 504, 981, 696), radius=8, outline=col, width=7)
                for yy in (554, 601, 649):
                    d.line((845, yy, 959, yy), fill=hot if yy == 601 else col, width=5)
            self.layer_cache[key] = layer
        frame.alpha_composite(layer)
        if shot.get("primary") == "you" and shot.get("action") == "holding" and \
                shot.get("shot_type") == "medium":
            # Character holds a real foreground clue between the hands, instead of
            # gesturing at a floating AI background. Static, high-contrast line art.
            d = ImageDraw.Draw(frame)
            # The actor's real hand centres sit to either side at this medium framing.
            x0, x1, y0, y1 = 421, 736, 891, 1045
            if any(w in words for w in ("luggage", "trunk", "baggage")):
                d.rounded_rectangle((x0, y0, x1, y1), radius=14,
                                    fill=(116, 88, 69), outline=(240, 236, 227), width=6)
                d.arc((x0 + 85, y0 - 35, x1 - 85, y0 + 30), 182, 358,
                      fill=(235, 228, 217), width=7)
                d.line((x0 + 16, y0 + 38, x1 - 16, y0 + 38),
                       fill=(225, 212, 192), width=5)
                # Do not draw replacement hands: the original rig hands remain on either side.
            else:
                d.rounded_rectangle((x0, y0, x1, y1), radius=8,
                                    fill=(206, 196, 179), outline=(21, 24, 30), width=7)
                for k in range(3):
                    y = y0 + 24 + k * 24
                    d.line((x0 + 29, y, x1 - 26, y), fill=(64, 57, 55), width=5)
                d.rectangle((x1 - 45, y1 - 35, x1 - 18, y1 - 12), fill=self.acc + (255,))

    @staticmethod
    def _travel(action, facing, x) -> float:
        speed = {"walking": 260, "boarding": 300, "sneaking": 160, "running": 520}.get(action or "", 0)
        return (1 if facing == "right" else -1) * speed * (x - 0.5)

    @staticmethod
    def _exit_alpha(action, x) -> float:
        return 1.0 - max(0.0, (x - 0.8) / 0.2) if action == "boarding" else 1.0

    def _background(self, seg: dict, x: float) -> Image.Image:
        """The painted place, STILL by default; subtle_push / subtle_pan / parallax_light only when planned."""
        s = seg["shot"]
        if CONFIG.get("explainer_character_stage", True):
            key = ("blank-stage",)
            if key not in self.static:
                self.static[key] = Image.new("RGBA", (W, H), (43, 48, 55, 255))
            return self.static[key].copy()
        plate = self.assets["plates"].get(s.get("location")) or next(iter(self.assets["plates"].values()))
        st = s.get("shot_type", "wide")
        zoom = {"wide": 1.0, "medium": 1.18, "close": 1.4, "over_shoulder": 1.1}.get(st, 1.0)
        motion = s.get("motion", "none")
        if motion == "none":
            key = (seg["start"], str(plate), st)
            if key not in self.static:
                if len(self.static) > 6:
                    self.static.clear()
                img = self._crop(self._plate(plate, zoom), 0.5, 0.5, 1.0)
                if st == "close":
                    img = img.filter(ImageFilter.GaussianBlur(5))
                self.static[key] = img
            return self.static[key].copy()
        base = self._plate(plate, zoom * 1.06)
        if motion == "subtle_push":
            return self._crop(base, 0.5, 0.5, 1.0 + 0.045 * _ease(x))
        drift = 0.035 * (x - 0.5) * (1 if motion == "subtle_pan" else -1)
        return self._crop(base, 0.5 + drift, 0.5, 1.0)

    # ---------------------------------------------------------------- text on scene shots
    def overlay(self, frame: Image.Image, s: dict, t: float, target) -> None:
        if CONFIG.get("explainer_character_stage", True):
            return  # no extra lower-third text over the actor; context label + safe karaoke only
        mode, text = s.get("text_mode", "none"), s.get("text") or ""
        if mode == "none" or not text or t < 0.12:
            return
        t -= 0.12
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))  # PIL replaces (not blends) translucent fills on RGBA
        getattr(self, f"_text_{mode}", lambda *a: None)(layer, text, s.get("accent", ""), t, target)
        frame.alpha_composite(layer)

    def _lower_third(self, frame, text, t, label):
        d = ImageDraw.Draw(frame, "RGBA")
        f = font("bold", 58)
        shown = text.upper()[:max(0, int(len(text) * min(1.0, t / 0.45)))]  # typewriter
        tw = d.textlength(text.upper(), font=f)
        x0 = 70 - 520 * (1 - _ease(t / 0.22))
        y0 = 1150
        d.rectangle((x0, y0, x0 + 14, y0 + 118), fill=self.acc)
        d.rectangle((x0 + 14, y0, x0 + 14 + tw + 60, y0 + 118), fill=(10, 10, 14, 200))
        d.text((x0 + 44, y0 + 12), label, font=font("mono", 26), fill=self.acc)
        d.text((x0 + 44, y0 + 46), shown, font=f, fill=(255, 255, 255))

    def _text_location(self, frame, text, acc, t, target):
        self._lower_third(frame, text, t, "LOCATION")

    def _text_name(self, frame, text, acc, t, target):
        self._lower_third(frame, text, t, "WHO")

    def _text_punch(self, frame, text, acc, t, target):
        f = font("black", 104)
        words = text.upper().split()
        lines = _wrap(" ".join(words), f, 900)
        d = ImageDraw.Draw(frame, "RGBA")
        y = 380
        k = 0
        for line in lines:
            widths = [d.textlength(w, font=f) for w in line]
            sp = d.textlength(" ", font=f)
            xx = (W - (sum(widths) + sp * (len(line) - 1))) / 2
            for w, ww in zip(line, widths):
                pop = _back((t - 0.08 * k) / 0.22)
                if pop > 0.02:
                    if _is_accent(w, acc):
                        g = _ease((t - 0.08 * k) / 0.2)
                        d.rectangle((xx - 10, y + 6, xx - 10 + (ww + 20) * g, y + 118), fill=self.acc + (235,))
                    self._word(frame, w, f, (255, 255, 255), xx + ww / 2, y + 62, max(0.01, pop), shadow=True)
                xx += ww + sp
                k += 1
            y += 124

    def _text_stamp(self, frame, text, acc, t, target):
        self._build_stamp(frame, {"word": text.upper()[:18]}, t * 1.4, 300)

    def _text_quote(self, frame, text, acc, t, target):
        d = ImageDraw.Draw(frame, "RGBA")
        f = font("semi", 60)
        lines = _wrap(f"“{text}”", f, 820)
        h = len(lines) * 76 + 60
        a = _ease(t / 0.25)
        d.rounded_rectangle((90, 360, 990, 360 + h), radius=24, fill=(10, 10, 14, int(200 * a)))
        d.rectangle((90, 360, 102, 360 + h), fill=self.acc)
        n = int(sum(len(" ".join(l)) for l in lines) * min(1.0, t / 0.7))
        y = 390
        for line in lines:
            s_ = " ".join(line)[:max(0, n)]
            n -= len(" ".join(line)) + 1
            d.text((130, y), s_, font=f, fill=(255, 255, 255, int(255 * a)))
            y += 76

    def _text_evidence(self, frame, text, acc, t, target):
        d = ImageDraw.Draw(frame, "RGBA")
        f = font("bold", 50)
        tw = d.textlength(text.upper(), font=f)
        bx, by = min(W - 70 - tw - 60, 560), 330
        g = _ease(t / 0.3)
        d.rounded_rectangle((bx, by, bx + tw + 60, by + 120), radius=14, fill=PAPER + (int(240 * g),),
                            outline=self.acc + (255,), width=5)
        d.text((bx + 30, by + 10), "EVIDENCE", font=font("mono", 24), fill=self.acc)
        d.text((bx + 30, by + 44), text.upper()[:max(0, int(len(text) * min(1.0, t / 0.5)))], font=f, fill=(28, 24, 22))
        tx, ty = target or (W * 0.5, 980)
        sx, sy = bx + (tw + 60) / 2, by + 120
        k = _ease((t - 0.2) / 0.35)
        if k > 0:
            ex, ey = sx + (tx - sx) * k, sy + (ty - 40 - sy) * k
            d.line((sx, sy, ex, ey), fill=self.acc, width=7)
            if k > 0.95:
                d.ellipse((ex - 14, ey - 14, ex + 14, ey + 14), outline=self.acc, width=6)

    # ---------------------------------------------------------------- opener
    def opener_frame(self, t: float) -> Image.Image:
        """TRUE STORY motion graphic: red block slams in (overshoot + shake + flash), sweep lines, then wipes out."""
        frame = self._opener_bg()
        d = ImageDraw.Draw(frame, "RGBA")
        dur = self.t_true
        k = _back(t / 0.2)
        out = _ease((t - (dur - 0.22)) / 0.22)
        shake = (8 * math.sin(t * 90) * max(0.0, 1 - abs(t - 0.24) / 0.12)) if 0.12 < t < 0.4 else 0.0
        for j in range(3):  # sweep lines
            g = _ease((t - 0.05 * j) / 0.35)
            y = 760 + j * 22
            d.line((W * (1 - g), y + 300 * j, W, y + 300 * j), fill=self.acc + (170,), width=6)
        f = font("black", 150)
        label = "TRUE STORY"
        tw = d.textlength(label, font=f)
        block = Image.new("RGBA", (int(tw + 120), 230), (0, 0, 0, 0))
        db = ImageDraw.Draw(block)
        db.rounded_rectangle((0, 0, block.width - 1, block.height - 1), radius=26, fill=(224, 36, 43, 255))
        db.text((60, 18), label, font=f, fill=(255, 255, 255))
        sc = max(0.05, 1.9 - 0.9 * min(1.15, k))
        b2 = block.resize((max(1, int(block.width * sc * 0.82)), max(1, int(block.height * sc * 0.82))),
                          Image.BILINEAR)
        y_off = -900 * out
        if out < 1:
            b2.putalpha(b2.getchannel("A").point(lambda a: int(a * (1 - out))))
            self._paste(frame, b2, int(W / 2 - b2.width / 2 + shake), int(860 - b2.height / 2 + y_off))
        flash = max(0.0, 1 - abs(t - 0.2) / 0.1)
        if flash > 0:
            frame.alpha_composite(Image.new("RGBA", (W, H), (255, 255, 255, int(110 * flash))))
        d.text((W / 2, 1080 + y_off), "NIGHT FILES", font=font("mono", 34), fill=(230, 230, 230), anchor="mm")
        return frame

    def opener_title(self, t: float) -> Image.Image:
        """Title reveal: letters track in from wide spacing, an accent underline wipes across, then it slides up."""
        frame = self._opener_bg()
        dur = self.t_title - self.t_true
        title = (self.story.get("fixed_title") or self.story.get("title") or "").upper()
        f = font("black", 104 if len(title) <= 24 else 84)
        lines = _wrap(title, f, 920)[:3]
        d = ImageDraw.Draw(frame, "RGBA")
        spacing = 34 * (1 - _ease(t / 0.55))
        out = _ease((t - (dur - 0.2)) / 0.2)
        y = 860 - len(lines) * 58 - 260 * out
        k = 0
        for line in lines:
            text = " ".join(line)
            widths = [d.textlength(ch, font=f) for ch in text]
            total = sum(widths) + spacing * (len(text) - 1)
            x = (W - total) / 2
            for ch, w in zip(text, widths):
                a = _ease((t - 0.025 * k) / 0.2) * (1 - out)
                if a > 0.02 and ch != " ":
                    d.text((x, y), ch, font=f, fill=(255, 255, 255, int(255 * a)))
                x += w + spacing
                k += 1
            y += int(f.size * 1.1)
        g = _ease((t - 0.3) / 0.4)
        d.rectangle((W / 2 - 240 * g, y + 20, W / 2 + 240 * g, y + 34), fill=self.acc + (int(255 * (1 - out)),))
        d.text((W / 2, y + 90), "NIGHT FILES", font=font("mono", 32), fill=(220, 220, 220, int(255 * (1 - out))),
               anchor="mm")
        return frame

    def _opener_bg(self) -> Image.Image:
        if CONFIG.get("explainer_character_stage", True):
            return Image.new("RGBA", (W, H), (28, 32, 39, 255))
        if "opener_bg" not in self.layer_cache:
            first = next((s["shot"] for s in self.segs if s["shot"].get("type") == "scene"), {})
            plate = self.assets["plates"].get(first.get("location")) if first else None
            plate = plate or next(iter(self.assets["plates"].values()), None)
            if plate:
                bg = self._crop(self._plate(plate, 1.0), 0.5, 0.5, 1.0).filter(ImageFilter.GaussianBlur(10))
                bg = ImageEnhance.Brightness(bg.convert("RGB")).enhance(0.38).convert("RGBA")
            else:
                bg = Image.new("RGBA", (W, H), BLACK + (255,))
            self.layer_cache["opener_bg"] = bg
        return self.layer_cache["opener_bg"].copy()

    # ---------------------------------------------------------------- frames
    def frame_at(self, t: float, end_start: float) -> Image.Image:
        if t >= end_start:
            return self.end_card(t - end_start)
        seg = next((s for s in self.segs if s["start"] <= t < s["end"]), self.segs[-1])
        local = t - seg["start"]
        kind = seg["shot"]["type"]
        import noir
        dur = seg["end"] - seg["start"]
        sh = seg["shot"]
        if kind == "opener":
            frame = noir.render("true_story", {}, local, dur, self.ctx(seg, bg=self._opener_bg()))
        elif kind == "opener_title":
            frame = noir.render("title", {"text": self.story.get("fixed_title") or self.story.get("title") or ""},
                                local, dur, self.ctx(seg, bg=self._opener_bg()))
        elif kind == "card":
            frame = self._slide_in(self.card_frame(seg, local), local)
        elif kind == "title":
            frame = noir.render("impact", {"text": sh.get("text", ""), "accent": sh.get("accent", "")}, local, dur,
                                self.ctx(seg))
        elif kind == "graphic":
            frame = self._slide_in(noir.render(sh["template"], sh.get("fields") or {}, local, dur, self.ctx(seg)),
                                   local)
        else:
            frame = self.scene_frame(seg, local)
        self.captions(frame, t, "scene")
        return frame

    def _index(self, seg: dict) -> int:
        try:
            return self.segs.index(seg)
        except ValueError:
            return 0

    def ctx(self, seg: dict, bg=None) -> dict:
        """What a noir template needs: palette, a ground tone that alternates by position, the segment's words
        (for word-synced reveals), this video's plates (filmstrip), the subject's figure (missing effect)."""
        k = self._index(seg)
        sh = seg["shot"]
        c = {"accent": self.acc, "tone": __import__("noir").tone_for(k), "seed": k % 7 + 1,
             "words": [{"word": w["word"], "start": w["start"] - seg["start"]} for w in self.narr["words"]
                       if seg["start"] - 0.05 <= w["start"] < seg["end"]], "bg": bg}
        if sh.get("template") == "filmstrip":
            if "stills" not in self.layer_cache:
                if CONFIG.get("explainer_character_stage", True):
                    # Reusable storyboard panels of the ACTOR, not four blank placeholders or AI scenes.
                    result = []
                    for act, expr in (("holding", "curious"), ("pointing", "determined"),
                                      ("thinking", "worried"), ("reacting", "shocked")):
                        bg_im = Image.new("RGB", (600, 760), (49, 54, 60))
                        fig, (fx, fy) = self.figure("you", act, expr, "front", "right", 0.0, 600)
                        bg_im.paste(fig, (round(300 - fx), round(705 - fy)), fig)
                        result.append(bg_im)
                    self.layer_cache["stills"] = result
                else:
                    self.layer_cache["stills"] = [Image.open(p) for p in list(self.assets["plates"].values())[:4]]
            c["stills"] = self.layer_cache["stills"]
        if sh.get("template") == "missing":
            who = (sh.get("fields") or {}).get("subject") or "you"
            key = ("missing_fig", who)
            if key not in self.layer_cache:
                self.layer_cache[key] = self.figure(who, "standing", "neutral", "front", "right", 0.0, 900)[0]
            c["figure"] = self.layer_cache[key]
        return c

    def _slide_in(self, frame: Image.Image, t: float) -> Image.Image:
        """Cards wipe in from the right over 0.2 s."""
        k = _ease(t / 0.2)
        if k >= 1:
            return frame
        out = Image.new("RGBA", (W, H), BLACK + (255,))
        out.alpha_composite(frame, (int(W * (1 - k)), 0))
        return out

    def _paper(self) -> Image.Image:
        rng = np.random.default_rng(7)
        base = np.array(PAPER, dtype=np.float32)[None, None, :] + rng.normal(0, 5, (H // 4, W // 4, 1))
        im = Image.fromarray(np.clip(base, 0, 255).astype("uint8")).resize((W, H), Image.BICUBIC)
        return im.convert("RGBA")

    def _plate(self, path: Path, zoom: float) -> Image.Image:
        key = (str(path), zoom)
        if key not in self.plate_cache:
            im = Image.open(path).convert("RGB")
            scale = max(W / im.width, H / im.height) * zoom
            im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
            im = ImageEnhance.Brightness(im).enhance(0.82)
            im = ImageEnhance.Color(im).enhance(0.9)
            self.plate_cache[key] = im.filter(ImageFilter.UnsharpMask(2, 60, 2)).convert("RGBA")
        return self.plate_cache[key]

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
        w = min(bw, bh * W / H) / z
        h = w * H / W
        x0 = max(0, min(bw - w, cx * bw - w / 2))
        y0 = max(0, min(bh - h, cy * bh - h / 2))
        return base.resize((W, H), Image.BILINEAR, box=(x0, y0, x0 + w, y0 + h)).convert("RGBA")

    def title_frame(self, seg: dict, t: float) -> Image.Image:
        s = seg["shot"]
        frame = Image.new("RGBA", (W, H), BLACK + (255,))
        d0 = ImageDraw.Draw(frame)  # thin accent rule wipes across under the title
        g = _ease((t - 0.1) / 0.35)
        d0.rectangle((W / 2 - 200 * g, 1105, W / 2 + 200 * g, 1115), fill=self.acc)
        f = font("black", 128)
        lines = _wrap(s["text"].upper(), f, 900)
        if len(lines) > 3:
            f = font("black", 96)
            lines = _wrap(s["text"].upper(), f, 920)
        lh = int(f.size * 1.08)
        y0 = 860 - lh * len(lines) // 2
        k = 0
        d = ImageDraw.Draw(frame)
        for li, line in enumerate(lines):
            widths = [d.textlength(w, font=f) for w in line]
            space = d.textlength(" ", font=f)
            x = (W - (sum(widths) + space * (len(line) - 1))) / 2
            for w, ww in zip(line, widths):
                pop = _back((t - 0.07 * k) / 0.25)
                if pop > 0.02:
                    col = self.acc if _is_accent(w, s.get("accent", "")) else (255, 255, 255)
                    self._word(frame, w, f, col, x + ww / 2, y0 + li * lh + lh / 2, max(0.01, pop))
                x += ww + space
                k += 1
        return frame

    def _word(self, frame, word, f, col, cx, cy, scale, shadow=False):
        key = ("w", word, f.size, col, round(scale, 2), shadow)
        im = self.layer_cache.get(key)
        if im is None:
            box = ImageDraw.Draw(Image.new("L", (1, 1))).textbbox((0, 0), word, font=f)
            pad = 24 if shadow else 4
            im = Image.new("RGBA", (box[2] - box[0] + 2 * pad, box[3] - box[1] + 2 * pad), (0, 0, 0, 0))
            if shadow:
                ImageDraw.Draw(im).text((pad - box[0], pad - box[1] + 6), word, font=f, fill=(0, 0, 0, 210))
                im = im.filter(ImageFilter.GaussianBlur(8))
            ImageDraw.Draw(im).text((pad - box[0], pad - box[1]), word, font=f, fill=col + (255,))
            if abs(scale - 1) > 0.01:
                im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.BILINEAR)
            if len(self.layer_cache) < 4000:
                self.layer_cache[key] = im
        self._paste(frame, im, int(cx - im.width / 2), int(cy - im.height / 2))

    def card_frame(self, seg: dict, t: float) -> Image.Image:
        s = seg["shot"]
        dur = seg["end"] - seg["start"]
        import noir
        frame = noir.ground(noir.tone_for(self._index(seg)), 3).copy()
        d = ImageDraw.Draw(frame)
        # kicker: accent square + mono text, slides in
        kx = 90 - 40 * (1 - _ease(t / 0.25))
        d.rectangle((kx, 452, kx + 22, 474), fill=self.acc)
        d.text((kx + 40, 446), s.get("kicker") or "", font=font("mono", 34), fill=MUTED)
        f = font("cond", 132)
        lines = _wrap(s["text"].upper(), f, 880)
        if len(lines) > 3:
            f = font("cond", 100)
            lines = _wrap(s["text"].upper(), f, 880)
        lh = int(f.size * 1.08)
        y = 520
        k = 0
        for line in lines:
            x = 90
            for w in line:
                pop = _back((t - 0.05 * k) / 0.22)
                ww = d.textlength(w, font=f)
                if pop > 0.02:
                    col = self.acc if _is_accent(w, s.get("accent", "")) else INK
                    self._word(frame, w, f, col, x + ww / 2, y + lh / 2, max(0.01, pop))
                x += ww + d.textlength(" ", font=f)
                k += 1
            y += lh
        b = s.get("build") or {"kind": "none"}
        bt = (t - 0.35) / max(0.6, min(1.8, dur - 0.6))  # build progress 0..1
        top = max(y + 50, 880)
        getattr(self, f"_build_{b['kind']}", lambda *a: None)(frame, b, bt, top)
        return frame

    # builds (top = first free y; everything stays above the caption band at ~1330)

    def _build_grid(self, frame, b, x, top):
        n, filled = b["total"], b["filled"]
        cols = min(10, max(2, math.ceil(math.sqrt(n * 1.6))))
        rows = math.ceil(n / cols)
        cell = min(84, int(900 / cols) - 10, int((1300 - top - 70) / max(1, rows)) - 10)
        d = ImageDraw.Draw(frame)
        shown = int(n * _ease(x * 1.4))
        lit = int(filled * _ease(x * 1.4 - 0.4)) if x > 0.3 else 0
        for k in range(shown):
            r, c = divmod(k, cols)
            x0, y0 = 90 + c * (cell + 10), top + r * (cell + 10)
            fill = self.acc if k < lit else (81, 75, 72)
            d.rounded_rectangle((x0, y0, x0 + cell, y0 + cell), radius=8, fill=fill)
        if b.get("label") and x > 0.2:
            d.text((90, top + rows * (cell + 10) + 10), b["label"].upper(), font=font("mono", 32), fill=MUTED)

    def _build_bars(self, frame, b, x, top):
        d = ImageDraw.Draw(frame)
        bars = b["bars"]
        vmax = max([v["value"] for v in bars] + [b.get("threshold") or 0]) * 1.15 or 1
        base_y, hmax = 1250, max(160, 1250 - top - 40)
        bw = min(170, int(820 / len(bars)) - 30)
        for k, bar in enumerate(bars):
            g = _ease(x * 1.3 - 0.15 * k)
            h = int(hmax * bar["value"] / vmax * g)
            x0 = 120 + k * (bw + 40)
            over = b.get("threshold") is not None and bar["value"] >= b["threshold"]
            d.rectangle((x0, base_y - h, x0 + bw, base_y), fill=self.acc if over else INK)
            if g > 0.6:
                d.text((x0, base_y + 10), bar["label"].upper()[:10], font=font("mono", 26), fill=MUTED)
                d.text((x0, base_y - h - 52), _fmt(bar["value"]), font=font("bold", 40), fill=INK)
        if b.get("threshold") is not None and x > 0.4:
            ty = base_y - int(hmax * b["threshold"] / vmax)
            for xx in range(100, 980, 36):
                d.line((xx, ty, xx + 20, ty), fill=self.acc, width=5)
            d.text((620, ty - 46), (b.get("threshold_label") or "").upper(), font=font("mono", 28), fill=self.acc)

    def _build_counter(self, frame, b, x, top):
        v = b["from"] + (b["to"] - b["from"]) * _ease(x)
        if float(b["to"]).is_integer():
            v = round(v)
        txt = f"{b.get('prefix', '')}{_fmt(v)}{b.get('suffix', '')}"
        f = font("black", 200 if len(txt) <= 6 else 150 if len(txt) <= 9 else 110)
        d = ImageDraw.Draw(frame)
        d.text((90, top), txt, font=f, fill=self.acc)

    def _build_arrow(self, frame, b, x, top):
        d = ImageDraw.Draw(frame)
        f = font("bold", 44)
        y = top + 60
        d.rounded_rectangle((90, y, 470, y + 140), radius=18, outline=INK, width=6)
        d.text((280, y + 70), b["from"].upper(), font=f, fill=INK, anchor="mm")
        g = _ease(x * 1.5 - 0.2)
        if g > 0:
            x1 = 490 + int(120 * g)
            d.line((490, y + 70, x1, y + 70), fill=self.acc, width=10)
            if g > 0.95:
                d.polygon([(x1 + 30, y + 70), (x1 - 4, y + 46), (x1 - 4, y + 94)], fill=self.acc)
        if x > 0.6:
            d.rounded_rectangle((650, y, 1000, y + 140), radius=18, outline=self.acc, width=8)
            d.text((825, y + 70), b["to"].upper(), font=f, fill=self.acc, anchor="mm")

    def _build_stamp(self, frame, b, x, top):
        if x <= 0:
            return
        g = _back(x * 2.2)
        scale = 2.4 - 1.4 * min(1.0, g)
        f = font("black", 110)
        box = ImageDraw.Draw(Image.new("L", (1, 1))).textbbox((0, 0), b["word"], font=f)
        w, h = box[2] - box[0] + 80, box[3] - box[1] + 70
        im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        di = ImageDraw.Draw(im)
        di.rectangle((4, 4, w - 5, h - 5), outline=self.acc + (255,), width=10)
        di.text((40 - box[0], 35 - box[1]), b["word"], font=f, fill=self.acc + (255,))
        im = im.rotate(-8, expand=True, resample=Image.BICUBIC)
        sc = min(1.0, 900 / im.width) * scale
        im = im.resize((max(1, int(im.width * sc)), max(1, int(im.height * sc))), Image.BILINEAR)
        alpha = min(1.0, x * 6)
        if alpha < 1:
            im.putalpha(im.getchannel("A").point(lambda a: int(a * alpha)))
        self._paste(frame, im, int(W / 2 - im.width / 2), int(top + 170 - im.height / 2))

    def _build_list(self, frame, b, x, top):
        d = ImageDraw.Draw(frame)
        for k, item in enumerate(b["items"]):
            g = _ease(x * 2 - 0.45 * k)
            if g <= 0:
                continue
            y = top + k * 100
            xx = 90 - int(40 * (1 - g))
            d.text((xx, y), "→", font=font("black", 56), fill=self.acc)
            d.text((xx + 80, y + 4), item.upper(), font=font("bold", 52), fill=INK)

    def _build_none(self, *a):
        return None

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
        if kind != "card" and CONFIG.get("explainer_character_stage", True):
            d.rounded_rectangle((58, 0, W - 58, hgt), radius=23, fill=(9, 13, 19, 232))
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

    def end_card(self, t: float) -> Image.Image:
        frame = Image.new("RGBA", (W, H), BLACK + (255,))
        logo = ROOT / "assets" / "mascot_round.png"
        a = _ease(t / 0.4)
        if logo.exists():
            key = ("logo",)
            if key not in self.layer_cache:
                self.layer_cache[key] = Image.open(logo).convert("RGBA").resize((520, 520), Image.LANCZOS)
            lg = self.layer_cache[key]
            sc = 0.85 + 0.15 * _back(t / 0.4)
            lg2 = lg.resize((int(520 * sc), int(520 * sc)), Image.BILINEAR)
            self._paste(frame, lg2, W // 2 - lg2.width // 2, 760 - lg2.height // 2)
        d = ImageDraw.Draw(frame)
        if a > 0.3:
            d.text((W / 2, 1150), "FOLLOW FOR MORE", font=font("black", 84), fill=(255, 255, 255), anchor="mm")
            d.text((W / 2, 1270), "NIGHT FILES", font=font("black", 116), fill=self.acc, anchor="mm")
        return frame


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
    for t, name, vol in events:
        if name not in cache:
            cache[name] = _load_sfx(name, sr)
        s = cache[name]
        if s is None:
            continue
        a = int(t * sr)
        s = s[: max(0, len(mix) - a)]
        mix[a:a + len(s)] += s * vol
    peak = float(np.max(np.abs(mix))) or 1.0
    if peak > 0.98:
        mix *= 0.98 / peak
    sf.write(str(out), mix[: int(total * sr)], sr)
    return out


def render(story: dict, narration: dict, p: dict, assets: dict, workdir: Path) -> Path:
    from render import END_CARD_DELAY, tail_for
    segs = timeline(story, narration, p)
    total = narration["duration"] + tail_for(narration["duration"])
    end_start = narration["duration"] + END_CARD_DELAY
    r = Renderer(story, narration, p, assets, segs)
    events = []
    for k, s in enumerate(segs):
        if k and s["shot"]["type"] in ("card", "title") and segs[k - 1]["shot"]["type"] == "scene":
            events.append((max(0.0, s["start"] - 0.12), "whoosh", 0.22))
        b = s["shot"].get("build") or {}
        if b.get("kind") == "stamp":
            events.append((s["start"] + 0.35 + 0.45 * max(0.6, min(1.8, s["end"] - s["start"] - 0.6)) / 2.2,
                           "ui_click", 0.6))
    t_true, t_title = opener_length(story)
    if t_true:
        events.append((0.18, "ui_click", 0.8))  # the TRUE STORY slam
    if t_title:
        events.append((max(0.0, t_true - 0.1), "whoosh", 0.25))
    events.append((end_start, "ui_click", 0.7))
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
            proc.stdin.write(r.frame_at(i / FPS, end_start).convert("RGB").tobytes())
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
        key = (f"{sh['type']}:{sh.get('insert') or sh.get('location')}:{sh.get('primary')}:{sh.get('shot_type')}:"
               f"{sh.get('view')}" if sh["type"] == "scene"
               else f"{sh['type']}:{s['start']:.1f}")
        secs[key] = secs.get(key, 0.0) + s["end"] - s["start"]
    top = max(secs, key=secs.get)
    story["_visuals"] = {"distinct": len(secs), "longest_s": round(secs[top], 1),
                         "longest_share": round(secs[top] / total, 3), "longest_name": top}
    lens = [s["end"] - s["start"] for s in segs]
    story["explainer_render"] = {"segments": len(segs), "counts": counts, "shot_len_min": round(min(lens), 2),
                                 "shot_len_max": round(max(lens), 2), "shot_len_avg": round(sum(lens) / len(lens), 2),
                                 "render_seconds": round(time.time() - t0)}
    log(f"Explainer render: {len(segs)} shots {counts}, {min(lens):.1f}-{max(lens):.1f}s (avg "
        f"{sum(lens) / len(lens):.1f}s), {n} frames in {time.time() - t0:.0f}s")
    (workdir / "explainer_plan.json").write_text(json.dumps(
        {"plan": p, "segments": [{**s, "shot": s["shot"]} for s in segs]}, indent=1, ensure_ascii=False, default=str))
    return out


def build(story: dict, narration: dict, img_dir: Path, workdir: Path) -> Path:
    """plan -> painted assets -> render (no music; main.py / the test add it like for classic)."""
    import hashlib
    key = hashlib.sha1(json.dumps([w["word"] for w in narration["words"]]).encode()).hexdigest()[:16]
    saved = img_dir / "explainer_storyboard.json"
    p = None
    try:  # same narration (a resumed build / render-only retry): same storyboard, no new LLM call
        old = json.loads(saved.read_text())
        if old.get("key") == key:
            p = old["plan"]
            log("Explainer storyboard: reused from the earlier try (same narration)")
    except (OSError, ValueError, KeyError):
        pass
    if p is None:
        p = plan(story, narration)
        img_dir.mkdir(parents=True, exist_ok=True)
        saved.write_text(json.dumps({"key": key, "plan": p}, ensure_ascii=False, default=str))
    assets = make_assets(story, p, img_dir)
    story["render_style"] = "explainer"
    story["explainer_plan"] = {"cast": [c["name"] for c in p["cast"].values()],
                               "shots": sum(len(s["shots"]) for s in p["scenes"])}
    return render(story, narration, p, assets, workdir)


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
