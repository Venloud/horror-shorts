"""Writes an original scary story + scene breakdown + TikTok caption with Gemini."""
import json
import random
import re
import time
from collections import Counter

import requests

from common import CONFIG, env, log

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "title": {"type": "STRING"},
        "premise": {"type": "STRING"},
        "hook_overlay": {"type": "STRING"},
        "scenes": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "narration": {"type": "STRING"},
                    "image_prompt": {"type": "STRING"},
                    "image_prompt_2": {"type": "STRING"},
                    "image_prompt_3": {"type": "STRING"},
                    "image_prompt_4": {"type": "STRING"},
                    "sfx": {"type": "STRING"},
                    "location": {"type": "STRING"},
                },
                "required": ["narration", "image_prompt", "image_prompt_2", "image_prompt_3", "image_prompt_4", "sfx"],
            },
        },
        "characters": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "name": {"type": "STRING"}, "look": {"type": "STRING"}}, "required": ["name", "look"]}},
        "locations": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "name": {"type": "STRING"}, "look": {"type": "STRING"}}, "required": ["name", "look"]}},
        "setting": {"type": "STRING"},
        "threat": {"type": "STRING"},
        "twist": {"type": "STRING"},
        "twist_scene": {"type": "INTEGER"},
        "caption": {"type": "STRING"},
        "hashtags": {"type": "ARRAY", "items": {"type": "STRING"}},
        "pinned_comment": {"type": "STRING"},
    },
    "required": ["title", "premise", "hook_overlay", "scenes", "twist_scene",
                 "caption", "hashtags", "pinned_comment"],
}

EDITOR_PROMPT = """You are a strict story editor for a horror TikTok channel. Below is a draft (JSON).
Check it against this list, then return the improved story in the SAME JSON format.

CHECKLIST
1. Does the ending clearly pay off the hook? (If the hook mentions a habit, rule, object, or promise, the ending must explain it.)
2. Is it logical? The threat must follow one clear rule; no random events that are never explained; the viewer can retell the plot in one sentence.
3. Is there a real ending? Climax, then what happened after, then a final chilling line. Not a cliffhanger that just stops.
4. Does every scene move the story forward? Cut filler, keep the scariest concrete details.
5. THE HOOK: would the first 6 words alone stop a scroller? Does scene 1 open on the most shocking moment and raise one burning question? If it is generic, slow, or explains too much, rewrite scene 1 and hook_overlay until it hits hard (max 18 words).
6. Same rules as before: {rules}

If something fails, rewrite those scenes (and image_prompt, image_prompt_2 and sfx to match; the four image prompts must be different shots matching each quarter of the scene). Keep what already works. Keep the characters and locations lists and each scene's location.
Keep {words} words total, the same number of scenes or 7-9, and keep sfx values from this list only: {sfx_list}

DRAFT:
{draft}
"""


def edit_story(story: dict, api_key: str, sfx_list: str, rules: str) -> dict:
    """Second pass: an editor checks logic, ending, and hook payoff, then rewrites."""
    draft = {k: story[k] for k in SCHEMA["properties"] if k in story}
    prompt = EDITOR_PROMPT.format(draft=json.dumps(draft, ensure_ascii=False, indent=1),
                                  sfx_list=sfx_list, rules=rules, words="120 to 140")
    try:
        edited = _run_models(prompt, api_key, temperature=0.5)
        for k in ("characters", "locations"):  # keep the character / location sheets if the editor dropped them
            if story.get(k) and not edited.get(k):
                edited[k] = story[k]
        log("Editor pass: story revised")
        return edited
    except Exception as e:  # noqa: BLE001
        log(f"Editor pass failed, keeping the first draft: {str(e)[:200]}")
        return story


def pick_subgenre(history: list[dict]) -> str:
    """Pick the least-recently/least-often used subgenre, with a little randomness."""
    subs = CONFIG["subgenres"]
    recent = [h.get("subgenre") for h in history[-len(subs):]]
    counts = Counter(recent)
    fresh = [s for s in subs if counts[s] == 0]
    return random.choice(fresh or subs)


def _call_gemini(model: str, prompt: str, api_key: str, temperature: float = 1.0, as_json: bool = True, schema=None):
    gen = {"temperature": temperature}
    if as_json:
        gen.update({"responseMimeType": "application/json", "responseSchema": schema or SCHEMA})
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": gen,
        # Horror and true crime trip the default filters; allow dark (non-explicit) themes.
        "safetySettings": [{"category": c, "threshold": "BLOCK_ONLY_HIGH"} for c in (
            "HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH",
            "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT")],
    }
    r = requests.post(GEMINI_URL.format(model=model), json=body, timeout=120,
                      headers={"x-goog-api-key": api_key})
    if r.status_code != 200:
        raise RuntimeError(f"{model} HTTP {r.status_code}: {r.text[:400]}")
    data = r.json()
    cands = data.get("candidates") or []
    if not cands:
        reason = (data.get("promptFeedback") or {}).get("blockReason", "no reason given")
        raise RuntimeError(f"BLOCKED: Gemini refused this topic ({reason})")
    parts = (cands[0].get("content") or {}).get("parts") or []
    if not parts:
        raise RuntimeError(f"BLOCKED: empty answer (finishReason {cands[0].get('finishReason')})")
    text = "".join(p.get("text", "") for p in parts)
    return json.loads(text) if as_json else text.strip()


def _validate(story: dict) -> None:
    scenes = story.get("scenes") or []
    if not 6 <= len(scenes) <= 14:
        raise ValueError(f"bad scene count {len(scenes)}")
    words = sum(len(s["narration"].split()) for s in scenes)
    if not 90 <= words <= 320:
        raise ValueError(f"narration length {words} words out of range")
    if not 0 <= int(story.get("twist_scene", 0)) < len(scenes):
        story["twist_scene"] = max(0, len(scenes) - 2)


def pick_mode(history: list[dict]) -> str:
    """Position-based rotation through config story_modes, so a mode can repeat (e.g. lore, mystery, lore, case)."""
    modes = CONFIG.get("story_modes", ["lore"])
    count = sum(1 for h in history if h.get("title") and not h.get("skipped")
                and not str(h.get("mode", "")).startswith("inbox"))
    return modes[count % len(modes)]


def _run_models(prompt: str, api_key: str, temperature: float, patient: bool = True) -> dict:
    errors = []
    for idx, model in enumerate(CONFIG["llm_models"]):
        # The first model writes far better image prompts: when it's only overloaded (503), wait for it (~2 min).
        wait_503 = patient and idx == 0
        for attempt in range(5 if wait_503 else 3):
            try:
                story = _call_gemini(model, prompt, api_key, temperature)
                _validate(story)
                story["model"] = model
                return story
            except Exception as e:  # noqa: BLE001
                errors.append(f"{model}#{attempt + 1}: {str(e)[:300]}")
                log(f"Story attempt failed: {str(e)[:200]}")
                if "404" in str(e):
                    break  # model retired: skip straight to the next one
                if "429" in str(e):
                    break  # daily free quota used up for this model: go straight to the next one
                if "BLOCKED" in str(e) and attempt >= 1:
                    break  # topic refused twice: try the next model once, then give up on this topic
                if "503" in str(e) and wait_503:
                    if attempt < 4:
                        time.sleep(min(40, 10 * (attempt + 1)))
                    continue  # best model overloaded: wait for it, up to 5 tries
                if "503" in str(e) and attempt >= 1:
                    break  # backup model overloaded: don't wait, move to the next model
                if attempt >= 2:
                    break  # other errors: 3 tries per model, as before
                time.sleep(8 * (attempt + 1))
    raise RuntimeError("Could not write a story:\n" + "\n".join(errors))


def sfx_names() -> str:
    """Available sounds with a description of each, so the AI picks ones that really match the scene."""
    from common import ROOT
    have = {p.stem for p in (ROOT / "assets" / "sfx").glob("*.mp3") if not p.stem.startswith("ui_")}
    try:
        info = json.loads((ROOT / "data" / "sfx_sources.json").read_text())
    except Exception:  # noqa: BLE001
        info = {}
    lines = [f"\n  - {n}: {info.get(n, {}).get('desc', n.replace('_', ' '))}" for n in sorted(have)]
    return "".join(lines) + "\n  - none: no sound effect" + (
        "\n  Only use a sound if it matches BOTH the action AND the place exactly "
        "(e.g. walking in a jungle = footsteps_mud or footsteps_leaves, never footsteps_wood). "
        "If nothing matches exactly, use none."
        "\n  You may add ONE ending to any sound to fit the space: _echo (big empty room, hallway, church, cave, "
        "warehouse), _muffled (behind a wall or door, under a bed, underground), _distant (far away, outside). "
        "Examples: footsteps_wood_echo, knocking_muffled, scream_woman_distant, gunshot_distant.")


# ---------- the creator's own story instructions (prompts/fiction_*.txt) ----------

# Words that must appear in a scene's narration for its sound to be kept (base sound name -> clues).
SFX_CLUES = {
    "footsteps": ("step", "walk", "crunch", "pac", "running", "ran ", "stride", "heel", "arriv", "hallway", "corridor", "stairs", "entered"),
    "breathing": ("breath", "breathing", "panting", "gasp"),
    "whispers": ("whisper", "murmur", "voice"), "knocking": ("knock",), "window_tap": ("tap", "window"),
    "door": ("door", "stormed", "burst in", "locked", "entered"), "gate_creak": ("gate",), "floor_creak": ("creak", "floorboard"),
    "phone": ("phone", "call", "ring", "text", "buzz", "voicemail"), "doorbell": ("doorbell", "bell"),
    "scream": ("scream", "shriek", "yell"), "heartbeat": ("heart", "pulse"), "clock_ticking": ("clock", "tick"),
    "keys_jingle": ("key",), "glass_break": ("glass", "shatter", "window"), "gunshot": ("gun", "shot", "fired"),
    "dog_bark": ("dog", "bark"), "wolf_howl": ("howl", "wolf"), "owl": ("owl",), "crows": ("crow", "bird"),
    "wind": ("wind", "gust"), "rain": ("rain", "storm"), "thunder": ("thunder", "storm", "lightning"),
    "car": ("car", "engine", "drove", "truck"), "tv_static": ("tv", "static", "screen"), "radio_static": ("radio", "static"),
    "scratching": ("scratch", "claw"), "twigs_snap": ("snap", "twig", "branch"), "thud": ("thud", "fell", "drop", "slam"),
    "creepy_laugh": ("laugh", "giggle"), "humming": ("hum",), "music_box": ("music box", "melody", "lullaby"),
    "light_flicker": ("flicker",), "light_switch": ("switch", "light"), "match_strike": ("match",),
    "water_drip": ("drip", "water"), "chains": ("chain",), "church_bell": ("bell", "church"), "siren_distant": ("siren",),
    "camera_shutter": ("camera", "photo", "picture"), "fire_crackle": ("fire", "flame"), "crickets": ("cricket", "night"),
}


def clean_sfx(story: dict) -> None:
    """Drop sounds that don't match what the narration says, never on the hook, at most 4 per video.
    Stings (whoosh, riser, impact) only on the twist scene."""
    kept = 0
    twist = int(story.get("twist_scene", -1))
    for i, sc in enumerate(story.get("scenes", [])):
        name = (sc.get("sfx") or "none").strip()
        if name == "none":
            continue
        base = name
        for suffix in ("_echo", "_muffled", "_distant"):
            base = base.removesuffix(suffix)
        text = sc.get("narration", "").lower()
        key = next((k for k in SFX_CLUES if base.startswith(k)), None)
        ok = i > 0 and kept < 4 and (
            (key and any(c in text for c in SFX_CLUES[key]))
            or (key is None and i == twist and base in ("whoosh", "riser", "impact_boom", "ghost_presence")))
        if ok:
            kept += 1
        else:
            log(f"Sound '{name}' removed from scene {i + 1} (doesn't match the narration)")
            sc["sfx"] = "none"


def recent_list(history: list[dict]) -> str:
    """The last 40 stories with their plot, setting, threat and twist, so new stories avoid all of them."""
    lines = []
    for h in history[-40:]:
        if not h.get("title"):
            continue
        extra = "; ".join(f"{k}: {h[k]}" for k in ("setting", "threat", "twist") if h.get(k))
        lines.append(f"- {h['title']}: {h.get('premise', '')}" + (f" ({extra})" if extra else ""))
    return "\n".join(lines) or "- (none yet)"


# ---------- automatic quality gate for made-up stories (100-point formula) ----------

SCORE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "grab": {"type": "INTEGER"}, "curiosity_gap": {"type": "INTEGER"}, "relatable_setup": {"type": "INTEGER"},
        "one_wrong_thing": {"type": "INTEGER"}, "pressure_loop": {"type": "INTEGER"}, "choice": {"type": "INTEGER"},
        "reframe": {"type": "INTEGER"}, "payoff_clarity": {"type": "INTEGER"}, "final_image": {"type": "INTEGER"},
        "what_happened": {"type": "STRING"},
        "fixes": {"type": "STRING"},
    },
    "required": ["grab", "curiosity_gap", "relatable_setup", "one_wrong_thing", "pressure_loop", "choice",
                 "reframe", "payoff_clarity", "final_image", "what_happened", "fixes"],
}
SCORE_MAX = {"grab": 15, "curiosity_gap": 10, "relatable_setup": 10, "one_wrong_thing": 10, "pressure_loop": 20,
             "choice": 10, "reframe": 10, "payoff_clarity": 10, "final_image": 5}

SCORE_PROMPT = """You are a tough judge for a horror TikTok channel. Score this 50-60 second narration script.
Be strict: most first drafts deserve 55-75. Only a genuinely gripping, clear, complete story scores 80+.

SCORING (give each category a whole number up to its maximum):
- grab (max 15): does the FIRST sentence alone make you think "wait, what?" (contradiction, impossible situation, threat)? A plain setup line ("At 2 AM someone knocked") scores 5 or less.
- curiosity_gap (max 10): is there one burning question the viewer needs answered?
- relatable_setup (max 10): an ordinary situation the viewer can picture themselves in, with no biography or wasted names?
- one_wrong_thing (max 10): ONE central strange thing the story stays focused on (not a pile of creepy details)?
- pressure_loop (max 20): does every answer create a worse question, so tension keeps rising?
- choice (max 10): is the narrator forced into a decision the viewer instinctively makes with them?
- reframe (max 10): a reveal that changes the meaning of something already shown (not a random new monster)?
- payoff_clarity (max 10): can the viewer say in one sentence WHAT JUST HAPPENED? The monster may stay unexplained, but the event must be understandable. A vague ending where you can't tell what happened scores 0-3.
- final_image (max 5): does it end on one unforgettable image or line?

Also give:
- what_happened: one sentence explaining what happened. If you cannot, say "UNCLEAR".
- fixes: the 2-3 most important concrete changes that would raise the score.

SCRIPT:
\"\"\"
{script}
\"\"\"
"""


def score_script(script: str, api_key: str) -> tuple[int, dict]:
    last = None
    for model in CONFIG["llm_models"]:
        try:
            r = _call_gemini(model, SCORE_PROMPT.replace("{script}", script), api_key, 0.2, as_json=True, schema=SCORE_SCHEMA)
            total = sum(max(0, min(int(r.get(k, 0)), mx)) for k, mx in SCORE_MAX.items())
            if "UNCLEAR" in r.get("what_happened", "").upper():
                total = min(total, 70)  # a story nobody can explain never passes
            return total, r
        except Exception as e:  # noqa: BLE001
            last = e
            if "404" in str(e) or "429" in str(e) or "503" in str(e):
                continue
    raise RuntimeError(f"Could not score the story: {str(last)[:200]}")


class StoryBelowBar(Exception):
    pass


COLD_CASE_FILE = "fiction_cold_case.txt"


def _prompt_files() -> list:
    from common import ROOT
    # fiction_cold_case.txt is only for the "coldcase" mode, never picked for normal fiction
    return sorted(p for p in (ROOT / "prompts").glob("fiction*.txt") if p.name != COLD_CASE_FILE)


def _run_text(prompt: str, api_key: str, lo: int, hi: int) -> tuple[str, str]:
    errors = []
    for idx, model in enumerate(CONFIG["llm_models"]):
        # The first model writes far better image prompts: when it's only overloaded (503), wait for it (~2 min).
        wait_503 = patient and idx == 0
        for attempt in range(5 if wait_503 else 3):
            try:
                text = _call_gemini(model, prompt, api_key, 1.0, as_json=False)
                n = len(text.split())
                if not lo * 0.8 <= n <= hi * 1.3:
                    raise ValueError(f"story length {n} words, wanted {lo}-{hi}")
                return text, model
            except Exception as e:  # noqa: BLE001
                errors.append(f"{model}#{attempt + 1}: {str(e)[:200]}")
                log(f"Story attempt failed: {str(e)[:200]}")
                if "404" in str(e) or "429" in str(e) or ("BLOCKED" in str(e) and attempt >= 1) or ("503" in str(e) and attempt >= 1):
                    break
                time.sleep(6 * (attempt + 1))
    raise RuntimeError("Could not write a story:\n" + "\n".join(errors))


def _creator_story(history: list[dict], api_key: str, sfx_list: str, inspiration: str | None,
                   cold_case: bool = False) -> dict:
    from common import ROOT
    if cold_case:  # original fake case file (fiction, never labelled true)
        file, subgenre = ROOT / "prompts" / COLD_CASE_FILE, "cold case file (fiction)"
    else:
        files = _prompt_files()
        if not files:
            raise RuntimeError("No story instructions found: add a prompts/fiction_*.txt file")
        subgenre = pick_subgenre(history)
        # A subgenre can have its own instructions file (config "subgenre_prompts"); otherwise use a
        # general file that contains {subgenre}; otherwise any file.
        by_name = {f.name: f for f in files}
        mapped = CONFIG.get("subgenre_prompts", {}).get(subgenre)
        general = [f for f in files if "{subgenre}" in f.read_text(encoding="utf-8")]
        file = by_name.get(mapped) or (random.choice(general) if general else random.choice(files))
    lo, hi = CONFIG.get("story_words", [170, 220])
    recent = recent_list(history)
    prompt = file.read_text(encoding="utf-8").strip().replace("{subgenre}", subgenre) + f"""

## LENGTH
The narration must be {lo} to {hi} words in total (about {round(lo / 2.4)}-{round(hi / 2.4)} seconds read aloud). Count them.

## STORYTELLING NOTES
{{place_note}}- If the story builds up to a physical piece of proof (an object left behind, a photo, a mark), end on that proof so the viewer can see it. If it doesn't, don't force it.
- Write so every sentence can be shown as a picture: concrete things (the car, the bridge, the jacket, the window), not feelings.

## CHANNEL RULES
- The main characters are adults.
- TikTok-safe: dark and tense, but no gore, no sexual content, no self-harm or suicide, nothing involving harm to children.
- No real people, real brands, or real named towns.

## ALREADY USED (do not reuse the premise, setting, threat, or twist of any of these)
{recent}
"""
    prompt = prompt.replace("{place_note}", "" if cold_case else (
        '- If the place matters to the story (a road, a bridge, a motel, a trail), open by naming the place and its '
        'warning, e.g. "If you ever drive down Old Mill Road at night, never stop at the bridge." The place can be '
        "invented. If the place doesn't matter, don't force it.\n"))
    if inspiration:
        prompt += ("\n## INSPIRATION\nTake only the core idea and the feeling of this piece and write a NEW, ORIGINAL story "
                   "from it: new characters, names, setting details, twist and ending. Never copy its sentences.\n\"\"\"\n"
                   + inspiration[:6000] + "\n\"\"\"\n")
    bar = int(CONFIG.get("story_min_score", 80))
    tries = int(CONFIG.get("story_max_drafts", 3))
    best = None  # (score, script, model, review)
    ask = prompt
    for attempt in range(1, tries + 1):
        script, model = _run_text(ask, api_key, lo, hi)
        try:
            score, review = score_script(script, api_key)
        except Exception as e:  # noqa: BLE001
            log(f"Scoring unavailable ({str(e)[:120]}); keeping this draft")
            best = (bar, script, model, {"what_happened": "(not scored)"})
            break
        log(f"Draft {attempt} ({file.name}, {len(script.split())} words): {score}/100. "
            f"What happened: {review.get('what_happened', '')[:140]}")
        slow = hook_problem(script) if cold_case else None
        if slow:  # cold case: a date/year/place opener fails the draft, whatever its score
            log(f"Draft {attempt} hook {slow}: counting it as below the bar")
            score = min(score, bar - 1)
            review = {**review, "fixes": f"The first sentence {slow}. Open on the strangest detail; when/where go in "
                                         f"scene 2. " + str(review.get("fixes", ""))}
        if best is None or score > best[0]:
            best = (score, script, model, review)
        if score >= bar:
            break
        ask = (prompt + f"\n\n## YOUR LAST DRAFT SCORED {score}/100. REWRITE IT.\n"
               f"Fix these: {review.get('fixes', '')}\n"
               "Keep what worked, fix what didn't, and make sure the viewer can say what happened in one sentence.\n"
               "LAST DRAFT:\n\"\"\"\n" + script + "\n\"\"\"\n")
    if best[0] < bar:
        raise StoryBelowBar(f"best made-up story scored {best[0]}/100 (needs {bar})")
    score, script, model, review = best
    log(f"Story passed with {score}/100")

    story = plan_scenes(script, api_key, sfx_list)
    story.update({"mode": "coldcase" if cold_case else "fiction", "subgenre": subgenre, "prompt_file": file.name, "script_model": model,
                  "score": score, "what_happened": review.get("what_happened", "")})
    return story


REAL_STORY_IMAGES = """

THIS SCRIPT IS A REAL STORY about real people. This overrides the face rules above: never depict a real person's
face. People appear only as silhouettes against light, in deep shadow, or small in a wide shot. Prefer the real
places, era details and objects (the museum, the empty wall, the frame, the newspaper headline without readable
text). Match the real setting and time period."""


def plan_scenes(script: str, api_key: str, sfx_list: str, real: bool = False) -> dict:
    """Step 2: split a finished script into scenes + image prompts + sounds + caption, without changing its words."""
    from common import ROOT
    plan = (ROOT / "prompts" / "scene_plan.txt").read_text(encoding="utf-8")
    plan = "\n".join(l for l in plan.splitlines() if not l.startswith("#"))
    plan_prompt = plan.replace("{script}", script).replace("{sfx_list}", sfx_list)
    if real:
        plan_prompt += REAL_STORY_IMAGES
    story = _run_models(plan_prompt, api_key, temperature=0.4)
    prompts = [sc.get(k, "") for sc in story["scenes"] for k in ("image_prompt", "image_prompt_2", "image_prompt_3", "image_prompt_4") if sc.get(k)]
    avg = sum(len(x.split()) for x in prompts) / max(1, len(prompts))
    if avg < 16:
        log(f"Image prompts too short (avg {avg:.0f} words); asking again for detailed ones")
        retry = plan_prompt + ("\n\nIMPORTANT: your last image prompts were far too short. Every image prompt must be "
                               "25-45 words with character names, setting details, lighting, camera angle and mood.")
        try:
            story = _run_models(retry, api_key, temperature=0.6)
        except Exception as e:  # noqa: BLE001
            log(f"Retry failed, keeping the first plan: {str(e)[:120]}")
    return story


class UseAsInspiration(Exception):
    """The real story can't be told safely as-is, so it becomes inspiration for an original story."""
    def __init__(self, facts: str):
        super().__init__("too sensitive to retell as true; using it as inspiration instead")
        self.facts = facts


def _true_story(facts: str, name: str, api_key: str, sfx_list: str) -> dict:
    """Fact-locked retelling of a real story; the model may refuse unsafe topics with title SKIP."""
    import mystery
    prompt = mystery.TRUE_PROMPT.format(channel=CONFIG["channel_name"], case=name, facts=facts, sfx_list=sfx_list)
    story = _run_models(prompt, api_key, temperature=0.6)
    flag = story.get("title", "").strip().upper()
    if flag == "INSPIRATION":
        raise UseAsInspiration(facts)
    if flag == "SKIP":
        raise RuntimeError("source is not a real story, skipping")
    rules = (f'scene 1 = the hook sentence, then the exact words "{TRUE_OPENER}"; '
             "ONLY facts from this source, never invent details; only call someone guilty if convicted or confessed; "
             "respectful; no gore; third person; plain English; no real faces in images.\nSOURCE:\n" + facts[:6000])
    story = edit_story(story, api_key, sfx_list, rules)
    story = fix_hook(story, api_key, sfx_list, rules)
    log(f"True story '{story['title']}' ({len(story['scenes'])} scenes) via {story['model']}")
    return story


TRUE_OPENER = "This is a true story."
TRUE_MODES = ("case", "mystery", "inbox-true")  # real events; NOT lore (legends) and NOT fiction


def with_true_opener(text: str) -> str:
    """Put "This is a true story." right AFTER the hook sentence (never first: that's a slow opener)."""
    text = re.sub(r"\s*this is a true story[.!]?\s*", " ", text.strip(), flags=re.IGNORECASE).strip()
    end = re.search(r"[.!?…][\"”’)]?(?=\s+[A-Z\"“‘(]|\s*$)", text)
    if not end:
        return f"{text.rstrip(',;:')}. {TRUE_OPENER}".strip() if text else TRUE_OPENER
    hook, rest = text[:end.end()], text[end.end():].strip()
    return f"{hook} {TRUE_OPENER} {rest}".strip()


MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september",
          "october", "november", "december")
# Countries, continents, US states and big regions: none of these may be in a hook's first 6 words.
PLACES = """afghanistan albania algeria argentina armenia australia austria bangladesh belarus belgium bolivia
bosnia brazil bulgaria cambodia cameroon canada chile china colombia congo croatia cuba cyprus czech denmark
ecuador egypt england estonia ethiopia finland france germany ghana greece guatemala haiti honduras hungary
iceland india indonesia iran iraq ireland israel italy jamaica japan kazakhstan kenya korea latvia lebanon
libya lithuania malaysia mexico moldova mongolia morocco nepal netherlands holland nicaragua nigeria norway
pakistan panama peru philippines poland portugal romania russia scotland serbia slovakia slovenia somalia
spain sudan sweden switzerland syria taiwan thailand tunisia ukraine uruguay venezuela vietnam wales yemen
zimbabwe africa asia europe america antarctica australia oceania siberia scandinavia transylvania balkans
alabama alaska arizona arkansas california colorado connecticut delaware florida hawaii idaho illinois
indiana iowa kansas kentucky louisiana maine maryland massachusetts michigan minnesota mississippi missouri
montana nebraska nevada ohio oklahoma oregon pennsylvania tennessee texas utah vermont washington wisconsin
wyoming paris london rome berlin moscow tokyo york boston chicago""".split()
PLACE_PHRASES = ("new york", "new jersey", "new mexico", "new hampshire", "new zealand", "north carolina",
                 "south carolina", "north dakota", "south dakota", "west virginia", "rhode island",
                 "united states", "united kingdom", "south africa", "saudi arabia", "los angeles")


def hook_problem(text: str) -> str | None:
    """Why the first 6 words of a hook are a slow opener (a year, "In <month>", a place), or None if fine."""
    text = re.sub(r"^\s*this is a true story[.!]?\s*", "", text or "", flags=re.IGNORECASE)
    first = " ".join(text.split()[:6])
    low = re.sub(r"[^a-z0-9\s-]", " ", first.lower())
    if re.search(r"\b\d{4}s?\b", low):
        return "has a year in it"
    if re.search(r"\bin (" + "|".join(MONTHS) + r")\b", low):
        return "opens with a month"
    words = set(re.split(r"[\s-]+", low))
    hit = next((p for p in PLACES if p in words), None) or next((p for p in PLACE_PHRASES if p in low), None)
    if hit:
        return f"names a place ({hit})"
    return None


def fix_hook(story: dict, api_key: str, sfx_list: str, rules: str, tries: int = 2) -> dict:
    """If scene 1 opens slow (date, year, place), send it back to the editor for a new hook (max 2 tries)."""
    for attempt in range(tries):
        first = (story.get("scenes") or [{}])[0].get("narration", "")
        problem = hook_problem(first)
        if not problem:
            return story
        start = " ".join(first.split()[:6])
        log(f"Hook starts '{start}...' which {problem}: rewriting it ({attempt + 1}/{tries})")
        story = edit_story(story, api_key, sfx_list, rules + (
            f"\nHOOK FIX (most important): scene 1 starts with \"{start}\", which {problem}. Viewers swipe away "
            "in the first second. Rewrite scene 1 so its first words are the strangest or most shocking detail. "
            "Never open with a date, a year, or a place name; move when/where into scene 2."))
    first = (story.get("scenes") or [{}])[0].get("narration", "")
    if hook_problem(first):
        log(f"Hook still opens slow after {tries} rewrites, keeping it: '{' '.join(first.split()[:6])}...'")
    return story


def mark_true_story(story: dict) -> dict:
    """Flag real-event videos and make sure scene 1 opens with the true-story line (the editor may drop it)."""
    if story.get("mode") in TRUE_MODES:
        story["true_story"] = True
    if story.get("mode") in ("coldcase", "fiction", "lore"):
        story["true_story"] = False  # made-up stories and legends are never labelled true
    if story.get("true_story") and story.get("scenes"):
        story["scenes"][0]["narration"] = with_true_opener(story["scenes"][0].get("narration", ""))
    return story


def write_story(history: list[dict]) -> dict:
    skipped: list[dict] = []
    story = _write_story(history, skipped)
    mark_true_story(story)
    clean_sfx(story)
    story["_skipped"] = skipped
    return story


def _write_story(history: list[dict], skipped: list[dict]) -> dict:
    api_key = env("GEMINI_API_KEY")
    mode = pick_mode(history)
    sfx_list = sfx_names()
    import sources
    inspiration = None

    # 1) The creator's inbox (links / pasted stories) jumps the queue
    item = None
    try:
        item = sources.next_inbox(history)
    except Exception as e:  # noqa: BLE001
        log(f"Inbox read failed: {str(e)[:150]}")
    if item:
        try:
            text = sources.inbox_text(item)
            log(f"Inbox item: {item['key']} ({item['kind']}, {len(text)} chars)")
            if item["kind"] == "script":
                log("Inbox SCRIPT: narrating it exactly as written, only adding visuals")
                if item.get("true"):
                    text = with_true_opener(text)
                story = plan_scenes(text, api_key, sfx_list, real=item.get("true", False))
                story.update({"mode": "inbox-script", "source": item["key"], "subgenre": "creator script",
                              "true_story": bool(item.get("true"))})
                return story
            if item["kind"] == "true":
                try:
                    story = _true_story(text, item["key"], api_key, sfx_list)
                    story.update({"mode": "inbox-true", "source": item["key"], "subgenre": "true story"})
                    return story
                except UseAsInspiration:
                    log("Too sensitive to retell as true: turning it into an original story instead")
            inspiration = text
        except Exception as e:  # noqa: BLE001
            log(f"Inbox item {item['key']} failed ({str(e)[:200]}); skipping it")
            history = history + [{"source": item["key"]}]
            skipped.append({"source": item["key"], "skipped": True})
            item = None

    # 2) FBI case files
    if mode == "case" and not inspiration:
        for _ in range(3):
            case = sources.next_case(history)
            try:
                story = _true_story(sources.case_facts(case), case["title"], api_key, sfx_list)
                story.update({"mode": "case", "case": case["title"], "subgenre": "true crime case file"})
                return story
            except UseAsInspiration as e:
                log(f"'{case['title']}' is too sensitive to retell: using it as inspiration for an original story")
                skipped.append({"case": case["title"], "skipped": True})
                inspiration = e.facts
                break
            except Exception as e:  # noqa: BLE001
                log(f"Case mode failed ({str(e)[:200]}); trying another case")
                history = history + [{"case": case["title"]}]
                skipped.append({"case": case["title"], "skipped": True})
        log("Falling back to fiction today")

    # 3) Original fake case file (fiction; never gets the TRUE STORY label)
    if mode == "coldcase" and not inspiration:
        try:
            story = _creator_story(history, api_key, sfx_list, None, cold_case=True)
            words = sum(len(s["narration"].split()) for s in story["scenes"])
            log(f"Cold case '{story['title']}' ({words} words, {len(story['scenes'])} scenes) via {story['model']}")
            return story
        except Exception as e:  # noqa: BLE001 (below the bar or failed): make a legend instead
            log(f"Cold case failed ({str(e)[:200]}): making a legend video instead")
            story = _real_story(history, "lore", api_key, sfx_list)
            if story:
                return story
            raise RuntimeError("Cold case failed and no legend could be made") from e

    if mode in ("mystery", "lore") and not inspiration:
        story = _real_story(history, mode, api_key, sfx_list)
        if story:
            return story
        log("Falling back to fiction today")

    try:
        story = _creator_story(history, api_key, sfx_list, inspiration)
    except StoryBelowBar as e:
        log(f"{e}: throwing those drafts away and making a legend video instead")
        story = _real_story(history, "lore", api_key, sfx_list) or _real_story(history, "mystery", api_key, sfx_list)
        if not story:
            raise RuntimeError("No story passed the quality bar and no legend/mystery could be made") from e
        return story
    if inspiration and item:
        story["source"] = item["key"]
    words = sum(len(s["narration"].split()) for s in story["scenes"])
    log(f"Story '{story['title']}' ({words} words, {len(story['scenes'])} scenes) via {story['model']}")
    return story


def _real_story(history: list[dict], mode: str, api_key: str, sfx_list: str) -> dict | None:
    """A real legend (lore) or unsolved mystery, fact-locked to its Wikipedia source."""
    if True:
        import mystery
        for _ in range(3):
            case = mystery.pick_case(history, mode)
            try:
                prompt, facts = mystery.build_prompt(CONFIG["channel_name"], case, sfx_list, mode)
                story = _run_models(prompt, api_key, temperature=0.6)
                rules = ((f'scene 1 = the hook sentence, then the exact words "{TRUE_OPENER}"; ' if mode == "mystery" else "")
                         + "ONLY facts from this source, never invent details; theories/legends clearly labelled; "
                         "no accusing real people; respectful; no gore; third person; plain English.\nSOURCE:\n" + facts[:6000])
                story = edit_story(story, api_key, sfx_list, rules)
                story = fix_hook(story, api_key, sfx_list, rules)
                story.update({"mode": mode, "case": case,
                              "subgenre": "real unsolved mystery" if mode == "mystery" else "legend / folklore"})
                log(f"{mode.title()} '{story['title']}' ({len(story['scenes'])} scenes) via {story['model']}")
                return story
            except Exception as e:  # noqa: BLE001
                log(f"{mode} mode failed ({str(e)[:200]}); trying another topic")
                history = history + [{"case": case}]
    return None
