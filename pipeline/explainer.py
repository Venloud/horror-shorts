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
PAPER, INK, MUTED, BLACK = (238, 229, 210), (23, 23, 26), (112, 104, 90), (10, 10, 12)
HUD_Y, CHIP_Y, CAP_Y = 150, 292, 1430  # TikTok's top bar ends ~140 px; captions centred in the lower third
POSE_FALLBACK = {"angry": "determined", "scared": "shocked", "shocked": "scared", "determined": "pointing",
                 "sneaky": "looking_back", "sweating": "worried", "looking_back": "sneaky", "running": "looking_back",
                 "sitting": "worried", "holding": "pointing", "pointing": "determined"}
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
EXPLAINER style. The video cuts every 2-3 seconds between painted scenes with a stick figure called "you", info cards
with numbers, and title cards.

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
Keep title, characters, locations and fact_ledger. Update every scene's image prompts and image locations so they show
the new narration's place (an empty place, no people). Keep sfx from the same list.
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

PLAN_PROMPT = """You are the editor of a vertical explainer video. It cuts every 1.5-3 seconds between:
- "scene": a painted background place with our stick-figure character "you" on it (or an object close-up),
- "card": a beige paper info card: a small mono kicker, big bold text with ONE accent word, and ONE animated build-up,
- "title": a black title card with big white text and ONE accent word.
TRUE STORY: {true}

NARRATION (scene number: text, seconds):
{scenes}

Return JSON:
{{"hud_labels": ["<3 short stat labels, max 7 letters each, e.g. NIGHT, CLUES, NERVE>"],
 "locations": [{{"name": "<short name>", "look": "<18-28 words: the EMPTY place, era, light, mood; no people, no text>"}}],
 "inserts": [{{"name": "<short name>", "prompt": "<one object close-up, no people, no text, max 15 words>"}}],
 "scenes": [{{"chip": "<chapter label, max 12 chars: PROBLEM 1, NIGHT 2, CLUE 3>", "hud": ["<3 values, max 6 chars>"],
             "shots": [SHOT, ...]}}]}}
one "scenes" entry per narration scene, in order. SHOT is one of:
{{"type": "scene", "at": "<first 2-4 words where this shot starts, copied exactly from the narration>",
  "location": "<a locations name>", "pose": "<{poses}>", "framing": "wide|medium|face", "insert": ""}}
{{"type": "scene", "at": "...", "insert": "<an inserts name: show that object close-up instead of the character>"}}
{{"type": "card", "at": "...", "kicker": "<MONO KICKER, max 26 chars, e.g. PROBLEM 1 · THE NOISE>",
  "text": "<max 7 words>", "accent": "<one word of text>", "build": BUILD}}
{{"type": "title", "at": "...", "text": "<max 6 words>", "accent": "<one word of text>"}}
BUILD is one of:
{{"kind": "grid", "total": <4-60>, "filled": <n>, "label": "<max 4 words>"}}
{{"kind": "bars", "bars": [{{"label": "<max 2 words>", "value": <number>}}, ...2-4], "threshold": <number>, "threshold_label": "<max 3 words>"}}
{{"kind": "counter", "from": <number>, "to": <number>, "prefix": "<$ or empty>", "suffix": "<% or ' days' or empty>"}}
{{"kind": "arrow", "from": "<max 3 words>", "to": "<max 3 words>"}}
{{"kind": "stamp", "word": "<ONE WORD, e.g. AUTOMATICALLY, GONE, DENIED>"}}
{{"kind": "list", "items": ["<max 4 words>", "...", "..."]}}
{{"kind": "none"}}
RULES
- 3-5 shots per scene so there is a cut every 1.5-3 s. The FIRST shot of scene 1 is a "scene" shot with a strong
  expression (the hook is frame one). "at" of a scene's first shot = the scene's first words.
- Every shot shows EXACTLY what is said at that moment. About one shot in three is a card or title, for the key
  numbers, rules and turns; never two titles in a row.
- Every number on a card, title or HUD must be SAID in the narration{true_rule}. Card text uses the narration's words.
- HUD: three values per scene that change as things escalate (counts said in the narration like day/clues/miles, or
  a meter about YOU like NERVE 70%). chip = a short chapter label.
- pose = the expression that fits the words. "face" = a close-up of the face for emotional beats.
- At most {max_locs} locations and {max_inserts} inserts in total (each is one painted image); reuse locations.
  No people, no text/signs/symbols, nothing occult, no gore, never a real victim's body.
"""


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
    """Beat plan on the FINAL narration: shots per scene (with start times from the word timings), HUD values,
    chapter chips, locations and inserts. Invalid pieces are repaired or replaced by a keyword plan."""
    import explainer_character as ec
    words = narration["words"]
    spans = _scene_spans(story, narration)
    max_locs = int(CONFIG.get("explainer_max_plates", 6))
    max_ins = int(CONFIG.get("explainer_max_inserts", 4))
    scenes_txt = "\n".join(f"{i + 1}: {sc.get('narration', '')} ({spans[i][1] - spans[i][0]:.1f}s)"
                           for i, sc in enumerate(story["scenes"]))
    true = bool(story.get("true_story"))
    data = _plan_call(PLAN_PROMPT.format(
        true="yes" if true else "no", scenes=scenes_txt, poses="|".join(ec.POSES), max_locs=max_locs,
        max_inserts=max_ins, true_rule=" (TRUE story: never invent a number)" if true else "")) or {}
    said = _said_values(story)
    labels = [str(x).upper()[:7] for x in (data.get("hud_labels") or []) if str(x).strip()][:3]
    if len(labels) < 3:
        labels = ["SCENE", "CLUES", "NERVE"]
    locs = []
    for l in data.get("locations") or []:
        if isinstance(l, dict) and l.get("name") and l.get("look") and len(locs) < max_locs:
            locs.append({"name": str(l["name"])[:40], "look": _clean_visual(str(l["look"]))})
    if not locs:  # the story's own location sheet
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
    out_scenes, prev_hud = [], ["", "", ""]
    for i, sc in enumerate(story["scenes"]):
        rs = raw_scenes[i] if i < len(raw_scenes) and isinstance(raw_scenes[i], dict) else {}
        s_words = [w for w in words if w.get("scene") == i]
        shots = []
        for s in (rs.get("shots") or [])[:6]:
            v = _valid_shot(s, s_words, sc.get("narration", ""), said, loc_names, ins_names, locs)
            if v:
                shots.append(v)
        if not shots:
            shots = _keyword_shots(sc.get("narration", ""), s_words, locs, i)
        if shots[0]["type"] != "scene" and i == 0:
            shots.insert(0, _keyword_shots(sc.get("narration", ""), s_words, locs, i)[0])
        hud = [str(v).upper()[:6] for v in (rs.get("hud") or [])][:3]
        hud = [h if _number_ok(h, said, meter=True) else prev_hud[k] if k < len(prev_hud) else "" for k, h in
               enumerate(hud + [""] * (3 - len(hud)))]
        prev_hud = hud
        chip = re.sub(r"\s+", " ", str(rs.get("chip") or f"PART {i + 1}")).upper()[:12]
        out_scenes.append({"chip": chip, "hud": hud, "shots": shots})
    p = {"hud_labels": labels, "locations": locs, "inserts": inserts, "scenes": out_scenes}
    used_locs = {s.get("location") for sc in out_scenes for s in sc["shots"] if s["type"] == "scene"}
    used_ins = {s.get("insert") for sc in out_scenes for s in sc["shots"] if s.get("insert")}
    p["locations"] = [l for l in locs if l["name"] in used_locs] or locs[:1]
    p["inserts"] = [x for x in inserts if x["name"] in used_ins]
    counts = {"scene": 0, "card": 0, "title": 0}
    for sc in out_scenes:
        for s in sc["shots"]:
            counts[s["type"]] += 1
    log(f"Explainer plan ({'LLM' if raw_scenes else 'keyword fallback'}): {counts}, "
        f"{len(p['locations'])} location(s), {len(p['inserts'])} insert(s), HUD {labels}")
    return p


def _clean_visual(text: str) -> str:
    import images
    t = images._no_text(re.sub(r"\s+", " ", text)).strip().rstrip(".")
    return re.sub(r"\b(pentagram|sigil|occult|ritual|all-seeing eye|eye of providence|blood|gore|corpse|body)\b",
                  "", t, flags=re.IGNORECASE)


def _said_values(story: dict) -> set:
    import spoken_numbers as nums
    return nums.values(" ".join(sc.get("narration", "") for sc in story["scenes"]))


def _number_ok(text: str, said: set, meter: bool = False) -> bool:
    """Every number on screen must be said in the narration (tiny counts <= 3 and, on the HUD, 'you' meters in %
    are allowed)."""
    import spoken_numbers as nums
    if meter and re.fullmatch(r"\s*\d{1,3}\s*%\s*", text or ""):
        return True
    return all(v <= 3 or v in said for v in nums.values(str(text or "")))


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


def _valid_shot(s, s_words, narr, said, loc_names, ins_names, locs) -> dict | None:
    import explainer_character as ec
    if not isinstance(s, dict):
        return None
    kind = str(s.get("type") or "").lower()
    at = _anchor(str(s.get("at") or ""), s_words)
    if kind == "scene":
        ins = ins_names.get(str(s.get("insert") or "").lower(), "")
        loc = loc_names.get(str(s.get("location") or "").lower()) or locs[0]["name"]
        pose = s.get("pose") if s.get("pose") in ec.POSES else _pose_for(narr)
        framing = s.get("framing") if s.get("framing") in ("wide", "medium", "face") else "wide"
        return {"type": "scene", "at": at, "location": loc, "pose": pose, "framing": framing, "insert": ins}
    if kind == "title":
        text = str(s.get("text") or "").strip()[:48]
        if not text or not _number_ok(text, said):
            return None
        return {"type": "title", "at": at, "text": text, "accent": str(s.get("accent") or "")}
    if kind != "card":
        return None
    text = str(s.get("text") or "").strip()[:60]
    kicker = str(s.get("kicker") or "").strip().upper()[:28]
    if not text or not _number_ok(text + " " + kicker, said):
        return None
    b = s.get("build") if isinstance(s.get("build"), dict) else {}
    b = _valid_build(b, said)
    return {"type": "card", "at": at, "kicker": kicker, "text": text, "accent": str(s.get("accent") or ""),
            "build": b}


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
        if ok(z) and (a <= 3 or ok(a)):
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


_POSE_WORDS = [("running", r"\b(run|ran|running|chase|flee|fled|escape)"), ("scared", r"\b(scream|terrif|afraid|fear)"),
               ("shocked", r"\b(gone|vanish|disappear|impossible|never|nobody|no one)"),
               ("sweating", r"\b(sweat|nervous|panic|deadline|hours? left)"),
               ("sneaky", r"\b(sneak|quiet|silent|hide|hid|tiptoe)"), ("looking_back", r"\b(behind|follow|watch)"),
               ("angry", r"\b(angry|furious|lie|lied|refus)"), ("holding", r"\b(flashlight|lamp|hold|found|pick)"),
               ("pointing", r"\b(look at|there|this is|clue|notice)"), ("sitting", r"\b(sit|sat|wait|desk|think)"),
               ("determined", r"\b(decide|plan|first|you need|you check)")]


def _pose_for(text: str) -> str:
    return next((p for p, rx in _POSE_WORDS if re.search(rx, text, re.IGNORECASE)), "worried")


def _keyword_shots(narr: str, s_words: list[dict], locs: list[dict], i: int) -> list[dict]:
    loc = locs[i % len(locs)]["name"]
    first = " ".join(re.split(r"[.,!?;:]", narr)[0].split()[:6])
    return [{"type": "scene", "at": s_words[0]["start"] if s_words else None, "location": loc,
             "pose": _pose_for(narr), "framing": "wide", "insert": ""},
            {"type": "title", "at": None, "text": first, "accent": ""},
            {"type": "scene", "at": None, "location": loc, "pose": _pose_for(narr[len(narr) // 2:]),
             "framing": "face", "insert": ""}]


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


def timeline(story: dict, narration: dict, p: dict) -> list[dict]:
    """Segments {start, end, shot, scene}: planned shots at their anchor words, every segment 1.3-3 s (long ones
    are split: a painted shot gets a new framing, a card is followed by a reaction shot)."""
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
        pts = [(times[k], shots[k]) for k in order]
        merged = []
        for t, s in pts:  # too close to the previous cut: drop this shot (the earlier one keeps the time)
            if merged and t - merged[-1][0] < SHOT_MIN:
                continue
            merged.append((t, s))
        if len(merged) > 1 and b - merged[-1][0] < SHOT_MIN:
            merged.pop()
        for k, (t, s) in enumerate(merged):
            end = merged[k + 1][0] if k + 1 < len(merged) else b
            segs.extend(_split(t, end, s, i, words, p))
    return segs


def _split(t0: float, t1: float, shot: dict, scene: int, words: list[dict], p: dict) -> list[dict]:
    if t1 - t0 <= SHOT_MAX + 0.2:
        return [{"start": t0, "end": t1, "shot": shot, "scene": scene}]
    n = math.ceil((t1 - t0) / SHOT_MAX)
    cuts = [t0]
    for k in range(1, n):  # snap to a word start near the even split
        want = t0 + (t1 - t0) * k / n
        near = [w["start"] for w in words if t0 + SHOT_MIN < w["start"] < t1 - SHOT_MIN]
        cuts.append(min(near, key=lambda x: abs(x - want)) if near else want)
    cuts = sorted(set(cuts)) + [t1]
    out = []
    for k in range(len(cuts) - 1):
        s = shot if k == 0 else _variant(shot, k, scene, p)
        out.append({"start": cuts[k], "end": cuts[k + 1], "shot": s, "scene": scene})
    return out


def _variant(shot: dict, k: int, scene: int, p: dict) -> dict:
    """The next framing of a long beat: wide -> medium -> face, or a reaction shot after a card / title."""
    if shot["type"] == "scene" and not shot.get("insert"):
        order = ["wide", "medium", "face"]
        nxt = order[(order.index(shot.get("framing", "wide")) + k) % 3]
        return dict(shot, framing=nxt, variant=k)
    base = next((s for s in p["scenes"][scene]["shots"] if s["type"] == "scene" and not s.get("insert")), None)
    loc = (base or {}).get("location") or p["locations"][0]["name"]
    pose = (base or {}).get("pose") or "worried"
    return {"type": "scene", "location": loc, "pose": pose, "framing": "face" if k % 2 else "medium",
            "insert": "", "variant": k}


# ================================================================ painted assets

class Budget:
    def __init__(self, cap: int):
        self.cap, self.used = cap, 0


def _draw(prompt: str, dest: Path, budget: Budget) -> Path | None:
    import cf_budget
    import images
    if budget.used >= budget.cap:
        log(f"Explainer: image budget used ({budget.used}/{budget.cap}); {dest.name} not drawn")
        return None
    if images._STATE.get("cf_out") or not env("CLOUDFLARE_API_TOKEN", required=False):
        return None
    if images.test_mode() and not cf_budget.test_allowed():
        log(f"Explainer: today's Cloudflare test share is used up ({cf_budget.line()}); {dest.name} not drawn")
        return None
    budget.used += 1
    try:
        images._save_valid(images._cloudflare(prompt[:2000], random.randint(1, 10 ** 6)), dest)
        return dest
    except Exception as e:  # noqa: BLE001
        log(f"Explainer: {dest.name} draw failed ({str(e)[:160]})")
        return None


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:40] or "x"


def make_assets(story: dict, p: dict, img_dir: Path) -> dict:
    """Painted plates (one per location) + object inserts, <= explainer_max_images Cloudflare images in total
    (retries included). A plate that can't be drawn gets a code-drawn night gradient; a missing insert is replaced
    by the character shot. Files are kept in img_dir, so a resumed build reuses them."""
    import images
    img_dir.mkdir(parents=True, exist_ok=True)
    budget = Budget(int(CONFIG.get("explainer_max_images", 12)))
    style = CONFIG.get("explainer_plate_style") or (
        "moody cinematic digital painting, dramatic low-key lighting, deep teal shadows with warm amber highlights, "
        "soft painterly brushwork, atmospheric haze, empty scene, no people, no text, no signs, no letters")
    era = (story.get("setting") or "")[:80]
    plates, inserts, stats = {}, {}, {"drawn": 0, "reused": 0, "fallback": []}
    jobs = [("plate", l["name"], f"{style}, {l['look']}" + (f", {era}" if era else "") + ", wide establishing view, "
             "vertical composition") for l in p["locations"]]
    jobs += [("insert", x["name"], f"{style}, close-up of {x['prompt']}, shallow depth of field, no hands, no people")
             for x in p["inserts"]]
    for kind, name, prompt in jobs:
        dest = img_dir / f"x_{kind}_{_slug(name)}.png"
        if dest.exists():
            (plates if kind == "plate" else inserts)[name] = dest
            stats["reused"] += 1
            continue
        got = None
        for attempt in range(2):
            if not _draw(prompt, dest, budget):
                break
            v, why = images.check_image(dest, f"{name}: {prompt[len(style) + 2:][:200]}; NO if any people, letters, "
                                              "words or writing are visible")
            log(f"Explainer {kind} '{name}' (draw {attempt + 1}): QA {'YES' if v else 'NO' if v is False else 'skipped'}"
                + (f" ({why})" if why else ""))
            if v is not False:
                got = dest
                break
            dest.rename(dest.with_suffix(f".rejected{attempt}.png"))
        if got:
            (plates if kind == "plate" else inserts)[name] = got
            stats["drawn"] += 1
        else:
            stats["fallback"].append(f"{kind} {name}")
    for l in p["locations"]:
        if l["name"] not in plates:
            plates[l["name"]] = _gradient_plate(img_dir / f"x_plate_{_slug(l['name'])}_fallback.png")
    stats["cloudflare_images"] = budget.used
    story["explainer_assets"] = stats
    log(f"Explainer assets: {stats['drawn']} drawn ({budget.used} Cloudflare calls), {stats['reused']} reused, "
        f"fallbacks: {', '.join(stats['fallback']) or 'none'}")
    return {"plates": plates, "inserts": inserts}


def _gradient_plate(dest: Path) -> Path:
    y = np.linspace(0, 1, 1024)[:, None]
    top, bot = np.array([18, 30, 40]), np.array([6, 8, 12])
    arr = (top * (1 - y) + bot * y)[:, None, :].repeat(1024, axis=1)
    Image.fromarray(arr.astype("uint8").reshape(1024, 1024, 3)).save(dest)
    return dest


# ================================================================ drawing helpers

_FONTS: dict = {}


def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
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

class Character:
    def __init__(self):
        import explainer_character as ec
        self.files = ec.available()
        if not self.files:
            raise ExplainerUnavailable("no character set in assets/character (run the explainer_character workflow)")
        self.side = ec.SIDE
        self.cache: dict = {}
        self.heads: dict = {}

    def pose(self, name: str) -> str:
        seen = set()
        while name not in self.files and name not in seen:
            seen.add(name)
            name = POSE_FALLBACK.get(name, "worried")
        return name if name in self.files else next(iter(self.files))

    def image(self, name: str, height: int, flip: bool = False) -> Image.Image:
        name = self.pose(name)
        key = (name, height, flip)
        if key not in self.cache:
            im = Image.open(self.files[name]).convert("RGBA")
            im = im.resize((max(1, round(im.width * height / im.height)), height), Image.LANCZOS)
            self.cache[key] = ImageOps.mirror(im) if flip else im
        return self.cache[key]

    def head_box(self, name: str) -> tuple[float, float, float]:
        """(centre x, centre y, radius) of the round head, as fractions of the cut-out (the largest bright blob in
        the top half)."""
        name = self.pose(name)
        if name not in self.heads:
            im = Image.open(self.files[name]).convert("RGBA")
            a = np.asarray(im)
            top = a[: max(1, int(a.shape[0] * 0.55))]
            bright = (top[..., 3] > 200) & (top[..., :3].min(axis=2) > 215)
            rows = bright.sum(axis=1)
            cx, cy, r = 0.5, 0.15, 0.12
            if rows.max() > 10:  # the first tall band of bright rows from the top = the head (hands come later)
                on = rows > 0.3 * rows.max()
                start = int(np.argmax(on))
                end = start
                while end < len(on) and (on[end] or (end + 3 < len(on) and on[end:end + 4].any())):
                    end += 1
                band = bright[start:end]
                ys, xs = np.nonzero(band)
                if len(xs) > 50:
                    cx = float(np.median(xs)) / a.shape[1]
                    cy = (start + end) / 2 / a.shape[0]
                    r = max((xs.max() - xs.min()) / 2, (end - start) / 2) / a.shape[0]
            self.heads[name] = (float(cx), float(cy), float(r if 0.06 <= r < 0.3 else 0.18))  # arms up: default size
        return self.heads[name]


class Renderer:
    def __init__(self, story: dict, narration: dict, p: dict, assets: dict, segs: list[dict]):
        self.story, self.narr, self.p, self.assets, self.segs = story, narration, p, assets, segs
        self.char = Character()
        self.acc = accent()
        self.plate_cache: dict = {}
        self.layer_cache: dict = {}
        self.groups = _caption_groups(narration["words"])
        self.paper = self._paper()
        self.spans = _scene_spans(story, narration)

    # ---------------------------------------------------------------- backgrounds
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

    # ---------------------------------------------------------------- shots
    def scene_frame(self, seg: dict, t: float) -> Image.Image:
        s = seg["shot"]
        dur = seg["end"] - seg["start"]
        x = t / max(dur, 0.01)
        rnd = random.Random(f"{seg['start']:.2f}")
        if s.get("insert") and s["insert"] in self.assets["inserts"]:
            base = self._plate(self.assets["inserts"][s["insert"]], 1.12)
            z = 1.0 + 0.07 * _ease(x)
            frame = self._crop(base, 0.5, 0.5, z)
            frame.alpha_composite(self._vignette())
            return frame
        plate = self.assets["plates"].get(s.get("location")) or next(iter(self.assets["plates"].values()))
        framing = s.get("framing", "wide")
        zoom = {"wide": 1.1, "medium": 1.35, "face": 1.6}[framing]
        base = self._plate(plate, zoom)
        pan = rnd.choice([-1, 1])
        cx = 0.5 + pan * 0.06 * (x - 0.5) if framing != "face" else 0.5
        cy = 0.5 if framing == "wide" else 0.45
        frame = self._crop(base, cx, cy, 1.0 + 0.05 * _ease(x))
        if framing == "face":
            frame = frame.filter(ImageFilter.GaussianBlur(4))
        pose = s.get("pose") or "worried"
        side = self.char.pose(pose) in self.char.side
        hx, hy, hr = self.char.head_box(pose)
        if framing == "face":  # head ~ 760 px wide, centred around y 820
            height = int(760 / (2 * hr))
            px, py = W / 2, 820
            ch = self.char.image(pose, height)
            pop = _back(t / 0.22)
            sc = 0.94 + 0.06 * pop
            ch = ch.resize((max(1, int(ch.width * sc)), max(1, int(ch.height * sc))), Image.BILINEAR)
            ox = int(px - hx * ch.width)
            oy = int(py - hy * ch.height + 6 * math.sin(t * 2.4))
        else:
            height = 980 if framing == "wide" else 1450
            flip = side and pan < 0
            ch = self.char.image(pose, height, flip=flip)
            pop = _back(t / 0.22)
            breath = 1 + 0.008 * math.sin(t * 2.6)
            ch = ch.resize((max(1, int(ch.width * (0.93 + 0.07 * pop))),
                            max(1, int(ch.height * (0.93 + 0.07 * pop) * breath))), Image.BILINEAR)
            px = W * (0.5 if not side else (0.58 if not flip else 0.42))
            if pose == "running":
                px += (-1 if not flip else 1) * 120 * (x - 0.5)
            feet = 1700 if framing == "wide" else 2080
            ox, oy = int(px - ch.width / 2), int(feet - ch.height)
            if framing == "wide":  # contact shadow
                sh = self._shadow(int(ch.width * 0.9))
                frame.alpha_composite(sh, (int(px - sh.width / 2), feet - sh.height // 2))
        self._paste(frame, ch, ox, oy)
        frame.alpha_composite(self._vignette())
        return frame

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

    def _word(self, frame, word, f, col, cx, cy, scale):
        key = ("w", word, f.size, col, round(scale, 2))
        im = self.layer_cache.get(key)
        if im is None:
            box = ImageDraw.Draw(Image.new("L", (1, 1))).textbbox((0, 0), word, font=f)
            im = Image.new("RGBA", (box[2] - box[0] + 8, box[3] - box[1] + 8), (0, 0, 0, 0))
            ImageDraw.Draw(im).text((4 - box[0], 4 - box[1]), word, font=f, fill=col + (255,))
            if abs(scale - 1) > 0.01:
                im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.BILINEAR)
            if len(self.layer_cache) < 4000:
                self.layer_cache[key] = im
        self._paste(frame, im, int(cx - im.width / 2), int(cy - im.height / 2))

    def card_frame(self, seg: dict, t: float) -> Image.Image:
        s = seg["shot"]
        dur = seg["end"] - seg["start"]
        frame = self.paper.copy()
        d = ImageDraw.Draw(frame)
        # kicker: accent square + mono text, slides in
        kx = 90 - 40 * (1 - _ease(t / 0.25))
        d.rectangle((kx, 452, kx + 22, 474), fill=self.acc)
        d.text((kx + 40, 446), s.get("kicker") or "", font=font("mono", 34), fill=MUTED)
        f = font("black", 104)
        lines = _wrap(s["text"].upper(), f, 900)
        if len(lines) > 3:
            f = font("black", 80)
            lines = _wrap(s["text"].upper(), f, 900)
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
            fill = self.acc if k < lit else (205, 195, 175)
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

    # ---------------------------------------------------------------- overlays
    def hud(self, frame: Image.Image, seg: dict, t_abs: float) -> None:
        scene = seg["scene"]
        sc = self.p["scenes"][scene]
        prev = self.p["scenes"][scene - 1]["hud"] if scene else ["", "", ""]
        scene_start = self.spans[scene][0]
        since = t_abs - scene_start
        d = ImageDraw.Draw(frame, "RGBA")
        bw, gap = 300, 24
        x0 = (W - (3 * bw + 2 * gap)) // 2
        for k in range(3):
            x = x0 + k * (bw + gap)
            d.rounded_rectangle((x, HUD_Y, x + bw, HUD_Y + 118), radius=16, fill=(10, 10, 14, 185),
                                outline=(255, 255, 255, 70), width=2)
            d.text((x + 20, HUD_Y + 14), self.p["hud_labels"][k], font=font("mono", 26), fill=(190, 190, 196))
            val = sc["hud"][k] or "—"
            changed = sc["hud"][k] != (prev[k] if k < len(prev) else "") and since < 0.5
            col = self.acc if changed else (255, 255, 255)
            f = font("black", 52 if len(val) <= 4 else 42)
            d.text((x + 20, HUD_Y + 50), val, font=f, fill=col)
        chip = "TRUE STORY" if self.story.get("true_story") and t_abs < 3.5 else sc["chip"]
        cfill = (224, 36, 43) if chip == "TRUE STORY" else self.acc
        f = font("mono", 30)
        tw = d.textlength(chip, font=f)
        d.rounded_rectangle((x0, CHIP_Y, x0 + tw + 44, CHIP_Y + 54), radius=27, fill=cfill)
        d.text((x0 + 22, CHIP_Y + 8), chip, font=f, fill=(255, 255, 255))

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

    # ---------------------------------------------------------------- frames
    def frame_at(self, t: float, end_start: float) -> Image.Image:
        if t >= end_start:
            return self.end_card(t - end_start)
        seg = next((s for s in self.segs if s["start"] <= t < s["end"]), self.segs[-1])
        local = t - seg["start"]
        kind = seg["shot"]["type"]
        if kind == "card":
            frame = self.card_frame(seg, local)
        elif kind == "title":
            frame = self.title_frame(seg, local)
        else:
            frame = self.scene_frame(seg, local)
            self.hud(frame, seg, t)
        self.captions(frame, t, kind)
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
        key = (f"{sh['type']}:{sh.get('insert') or sh.get('location')}:{sh.get('framing')}" if sh["type"] == "scene"
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
    Character()  # fail fast without the character set
    p = plan(story, narration)
    assets = make_assets(story, p, img_dir)
    story["render_style"] = "explainer"
    story["explainer_plan"] = {"hud_labels": p["hud_labels"], "chips": [s["chip"] for s in p["scenes"]]}
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
