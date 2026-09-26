"""Writes an original scary story + scene breakdown + TikTok caption with Gemini."""
import json
import random
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
                "required": ["narration", "image_prompt", "image_prompt_2", "sfx"],
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


def _call_gemini(model: str, prompt: str, api_key: str, temperature: float = 1.0, as_json: bool = True):
    gen = {"temperature": temperature}
    if as_json:
        gen.update({"responseMimeType": "application/json", "responseSchema": SCHEMA})
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
    """Rotate through the story modes in config (e.g. fiction, mystery, fiction, mystery...)."""
    modes = CONFIG.get("story_modes", ["fiction"])
    last = next((h.get("mode", "fiction") for h in reversed(history) if not h.get("skipped")), None)
    if last in modes:
        return modes[(modes.index(last) + 1) % len(modes)]
    return modes[0]


def _run_models(prompt: str, api_key: str, temperature: float) -> dict:
    errors = []
    for model in CONFIG["llm_models"]:
        for attempt in range(3):
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
                if "503" in str(e) and attempt >= 1:
                    break  # model overloaded: don't wait, move to the next model
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
    "footsteps": ("step", "walk", "crunch", "pac", "running", "ran ", "stride", "heel"),
    "breathing": ("breath", "breathing", "panting", "gasp"),
    "whispers": ("whisper", "murmur", "voice"), "knocking": ("knock",), "window_tap": ("tap", "window"),
    "door": ("door",), "gate_creak": ("gate",), "floor_creak": ("creak", "floorboard"),
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


def _prompt_files() -> list:
    from common import ROOT
    return sorted((ROOT / "prompts").glob("fiction*.txt"))


def _run_text(prompt: str, api_key: str, lo: int, hi: int) -> tuple[str, str]:
    errors = []
    for model in CONFIG["llm_models"]:
        for attempt in range(3):
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


def _creator_story(history: list[dict], api_key: str, sfx_list: str, inspiration: str | None) -> dict:
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
- If the place matters to the story (a road, a bridge, a motel, a trail), open by naming the place and its warning, e.g. "If you ever drive down Old Mill Road at night, never stop at the bridge." The place can be invented. If the place doesn't matter, don't force it.
- If the story builds up to a physical piece of proof (an object left behind, a photo, a mark), end on that proof so the viewer can see it. If it doesn't, don't force it.
- Write so every sentence can be shown as a picture: concrete things (the car, the bridge, the jacket, the window), not feelings.

## CHANNEL RULES
- The main characters are adults.
- TikTok-safe: dark and tense, but no gore, no sexual content, no self-harm or suicide, nothing involving harm to children.
- No real people, real brands, or real named towns.

## ALREADY USED (do not reuse the premise, setting, threat, or twist of any of these)
{recent}
"""
    if inspiration:
        prompt += ("\n## INSPIRATION\nTake only the core idea and the feeling of this piece and write a NEW, ORIGINAL story "
                   "from it: new characters, names, setting details, twist and ending. Never copy its sentences.\n\"\"\"\n"
                   + inspiration[:6000] + "\n\"\"\"\n")
    script, model = _run_text(prompt, api_key, lo, hi)
    log(f"Script written with {file.name} via {model} ({len(script.split())} words)")

    from common import ROOT
    plan = (ROOT / "prompts" / "scene_plan.txt").read_text(encoding="utf-8")
    plan = "\n".join(l for l in plan.splitlines() if not l.startswith("#"))
    plan_prompt = plan.replace("{script}", script).replace("{sfx_list}", sfx_list)
    story = _run_models(plan_prompt, api_key, temperature=0.4)
    story.update({"mode": "fiction", "subgenre": subgenre,
                  "prompt_file": file.name, "script_model": model})
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
    rules = ("ONLY facts from this source, never invent details; only call someone guilty if convicted or confessed; "
             "respectful; no gore; third person; plain English; no real faces in images.\nSOURCE:\n" + facts[:6000])
    story = edit_story(story, api_key, sfx_list, rules)
    log(f"True story '{story['title']}' ({len(story['scenes'])} scenes) via {story['model']}")
    return story


def write_story(history: list[dict]) -> dict:
    skipped: list[dict] = []
    story = _write_story(history, skipped)
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

    if mode in ("mystery", "lore") and not inspiration:
        import mystery
        for _ in range(3):
            case = mystery.pick_case(history, mode)
            try:
                prompt, facts = mystery.build_prompt(CONFIG["channel_name"], case, sfx_list, mode)
                story = _run_models(prompt, api_key, temperature=0.6)
                rules = ("ONLY facts from this source, never invent details; theories/legends clearly labelled; "
                         "no accusing real people; respectful; no gore; third person; plain English.\nSOURCE:\n" + facts[:6000])
                story = edit_story(story, api_key, sfx_list, rules)
                story.update({"mode": mode, "case": case,
                              "subgenre": "real unsolved mystery" if mode == "mystery" else "legend / folklore"})
                log(f"{mode.title()} '{story['title']}' ({len(story['scenes'])} scenes) via {story['model']}")
                return story
            except Exception as e:  # noqa: BLE001
                log(f"{mode} mode failed ({str(e)[:200]}); trying another topic")
                history = history + [{"case": case}]
        log("Falling back to fiction today")

    story = _creator_story(history, api_key, sfx_list, inspiration)
    if inspiration and item:
        story["source"] = item["key"]
    words = sum(len(s["narration"].split()) for s in story["scenes"])
    log(f"Story '{story['title']}' ({words} words, {len(story['scenes'])} scenes) via {story['model']}")
    return story
