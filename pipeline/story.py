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
        "twist_scene": {"type": "INTEGER"},
        "caption": {"type": "STRING"},
        "hashtags": {"type": "ARRAY", "items": {"type": "STRING"}},
        "pinned_comment": {"type": "STRING"},
    },
    "required": ["title", "premise", "hook_overlay", "scenes", "twist_scene",
                 "caption", "hashtags", "pinned_comment"],
}

PROMPT = """You write viral short-form horror stories for a faceless TikTok channel called "{channel}".
The story is read aloud by a calm, low narrator over illustrated images. Write an ORIGINAL story.

SUBGENRE FOR TODAY: {subgenre}

STRUCTURE (follow exactly). The story must be COMPLETE and LOGICAL, like a good campfire story.
First, silently plan: (a) the threat and its ONE clear rule (what it is, what it wants, what triggers it), (b) the hook's promise, (c) the ending that pays off that promise. Then write.
1. SCENE 1 = THE HOOK. This decides everything: most viewers swipe in the first 2 seconds.
   - COLD OPEN: start at the most shocking, impossible, or disturbing moment of the story, then rewind. 1-2 sentences, MAX 18 words.
   - The FIRST 6 WORDS must already be unsettling. No warm-up, no setup, no "I want to tell you about".
   - Best formula: a normal statement + one detail that makes it impossible or terrifying. Examples of the STYLE (write new ones, never reuse these):
     "My phone buzzed at 3 AM. It was a text from my own number: don't turn around."
     "My landlord texted to say he'd fixed the leak in my kitchen. I don't have a landlord."
     "I found forty photos of myself sleeping in a camera I'd never seen before."
     "The man in the lake waved at me. The lake had been frozen for a month."
   - It must create ONE burning question the viewer needs answered, and the ending must answer it.
   - Never open with "So", "One night", "This happened", "Have you ever", "Let me tell you", or a rule list.
2. SCENE 2 = REWIND + CONTEXT (1-2 sentences): jump back to how it started, e.g. "It started three weeks earlier." Who I am, where I was. Grounded and ordinary.
3. RISING TENSION: the strange thing starts, then escalates step by step. Every detail must matter later.
4. CLIMAX: the narrator faces the threat directly. Something happens.
5. ENDING (last 1-2 scenes): what happened after, and a final chilling line.
   - The ending MUST pay off the hook. If the hook mentions a habit, rule, or object (a blindfold, a rule, a locked door), the ending must clearly explain why.
   - The narrator must survive to tell it, so show how it ended (they escaped, it left, they found out the truth), then land a final sting: a detail that shows it isn't over.
   - The viewer must understand what happened. Leave ONE eerie question open, not the whole plot.
   - Good final lines: "That's why I sleep with the blindfold on. Because last night, I felt it breathing again." / "The landlord finally told me who lived there before me. He never left."
   - Never end mid-scene or on a cliffhanger with no resolution. No moral, no "and I never went back".

HARD RULES
- Pure fiction. No real people, real crimes, real victims, real brands, or real named towns/addresses.
- The main characters are adults.
- TikTok-safe: tension and dread, not gore. No graphic violence, no self-harm, no suicide, nothing involving harm to children, no sexual content.
- First person, past tense, plain spoken English like someone telling it at 2am. Short sentences. No fancy words.
- 130 to 160 words of narration total (about 50 seconds). This is strict; count them. Every sentence must earn its place.
- 7 to 9 scenes total. Each scene is 1-3 sentences and gets one image.

IMAGE PROMPTS
- Describe each painted frame: subject + setting + lighting + composition (camera angle / shot size).
- TWO images per scene: "image_prompt" shows the FIRST sentence of that scene, "image_prompt_2" shows the SECOND half. They must be different shots, like a film editor would cut: e.g. "I was 23, living alone in an old brick duplex" = shot 1: the young man in his room; shot 2: wide exterior of the old brick duplex at night. Mix close-ups, wide establishing shots of the location, objects, and over-the-shoulder views.
- Illustrated storybook / animated-film look, NOT a photo. The characters are fictional, so show them clearly with EXPRESSIVE FACES (worry, fear, confusion, relief). Faces sell the emotion.
- CONSISTENCY IS EVERYTHING: viewers must recognise the same people and the same rooms from shot to shot.
  - "characters": list every character once with a short "name" (e.g. "the night guard", "the old neighbor") and a fixed "look" (age, face, hair, exact clothes and colors, one prop), e.g. "a young man, mid 20s, short black hair, grey work jacket, flashlight".
  - "locations": list the 1-3 places the story happens with a short "name" (e.g. "the living room") and a fixed "look" (layout, furniture, colors, key objects), e.g. "cozy suburban living room, beige couch, old CRT TV on a wooden stand, tall lamp, staircase in the back".
  - In every image prompt, refer to characters by their exact name ("the night guard shines his flashlight at the old neighbor"). Their look is added automatically, so don't repeat it. Set each scene's "location" to one location name.
  - Keep the same outfits and the same rooms for the whole story unless the story truly moves.
- Lighting tells the story: warm, cozy lamp light at the start; darker, colder and more shadowy as the tension rises; darkest at the climax.
- Keep the threat mostly hidden until the climax: a shadow, a shape under the bed, a hand, eyes in the dark. Show it clearly at most once.
- No text or writing in the image. No blood or gore. Nobody is ever shown hurt.
- Scene 1's image must be the most striking, eerie image of the whole story (it is the thumbnail).

SOUND EFFECTS
- For each scene, set "sfx" to ONE sound from this list that is literally happening in that moment, or "none": {sfx_list}
- Use sound effects on 3 to 5 scenes only. Most important: the climax. Never on the hook scene.

OTHER FIELDS
- title: 3-7 word internal title.
- premise: one sentence summary (used to avoid repeating stories).
- hook_overlay: 2-5 word on-screen text shown big over the first seconds. It must be shocking on its own, not a title, e.g. "It texted from my phone", "I don't have a landlord", "He waved from under the ice". No emojis.
- twist_scene: the 0-based index of the scene where the twist hits.
- caption: line 1 = a searchable story title that says what happens, the way people would type it into TikTok search, e.g. "The Night Guard Checked the Cameras... and Saw Himself". Line 2 = a question that makes people comment (e.g. "Would you have checked?"). Max 180 characters. May use 1 emoji.
- hashtags: 5 hashtags without the # symbol, mixing broad (scarystories, horrortok) and specific.
- pinned_comment: a short comment the creator can pin to start discussion.

DO NOT REPEAT these recent stories (different premise, twist, and setting required):
{recent}
"""


EDITOR_PROMPT = """You are a strict story editor for a horror TikTok channel. Below is a draft (JSON).
Check it against this list, then return the improved story in the SAME JSON format.

CHECKLIST
1. Does the ending clearly pay off the hook? (If the hook mentions a habit, rule, object, or promise, the ending must explain it.)
2. Is it logical? The threat must follow one clear rule; no random events that are never explained; the viewer can retell the plot in one sentence.
3. Is there a real ending? Climax, then what happened after, then a final chilling line. Not a cliffhanger that just stops.
4. Does every scene move the story forward? Cut filler, keep the scariest concrete details.
5. THE HOOK: would the first 6 words alone stop a scroller? Does scene 1 open on the most shocking moment and raise one burning question? If it is generic, slow, or explains too much, rewrite scene 1 and hook_overlay until it hits hard (max 18 words).
6. Same rules as before: {rules}

If something fails, rewrite those scenes (and image_prompt, image_prompt_2 and sfx to match; the two image prompts must be different shots matching the first and second half of the scene). Keep what already works. Keep the characters and locations lists and each scene's location.
Keep {words} words total, the same number of scenes or 7-9, and keep sfx values from this list only: {sfx_list}

DRAFT:
{draft}
"""


def edit_story(story: dict, api_key: str, sfx_list: str, rules: str) -> dict:
    """Second pass: an editor checks logic, ending, and hook payoff, then rewrites."""
    draft = {k: story[k] for k in SCHEMA["properties"] if k in story}
    prompt = EDITOR_PROMPT.format(draft=json.dumps(draft, ensure_ascii=False, indent=1),
                                  sfx_list=sfx_list, rules=rules, words="130 to 160")
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
    if not 105 <= words <= 320:
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

SCENES_PROMPT = """You turn a finished horror narration script into a scene plan for a vertical TikTok video.

SCRIPT:
\"\"\"
{script}
\"\"\"

SPLIT IT INTO SCENES
- Split the script, in order, into 7 to 12 scenes of 1-3 sentences each, and put each part in "narration".
- COPY THE WORDS EXACTLY. Do not rewrite, shorten, add or reorder anything. Only remove markdown symbols, headings and quotation marks around dialogue if they would sound odd read aloud.
- Scene 1 must be the script's opening hook.

"""


def _prompt_files() -> list:
    from common import ROOT
    return sorted((ROOT / "prompts").glob("fiction*.txt"))


def _image_rules() -> str:
    """The image / sfx / caption rules from the built-in prompt, reused for the scene plan."""
    start, end = PROMPT.index("IMAGE PROMPTS"), PROMPT.index("DO NOT REPEAT")
    return PROMPT[start:end]


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
                if "404" in str(e) or ("BLOCKED" in str(e) and attempt >= 1) or ("503" in str(e) and attempt >= 1):
                    break
                time.sleep(6 * (attempt + 1))
    raise RuntimeError("Could not write a story:\n" + "\n".join(errors))


def _creator_story(history: list[dict], api_key: str, sfx_list: str, inspiration: str | None) -> dict:
    files = _prompt_files()
    used = [h.get("prompt_file") for h in history if h.get("prompt_file")]
    file = min(files, key=lambda f: (used.count(f.name), random.random()))  # rotate through the files
    lo, hi = CONFIG.get("story_words", [170, 220])
    recent = "\n".join(f"- {h['title']}: {h.get('premise', '')}" for h in history[-40:] if h.get("title")) or "- (none yet)"
    subgenre = pick_subgenre(history)
    prompt = file.read_text(encoding="utf-8").strip().replace("{subgenre}", subgenre) + f"""

## LENGTH
The narration must be {lo} to {hi} words in total (about {round(hi / 3)} seconds read aloud). Count them.

## CHANNEL RULES
- The main characters are adults.
- TikTok-safe: dark and tense, but no gore, no sexual content, no self-harm or suicide, nothing involving harm to children.
- No real people, real brands, or real named towns.

## ALREADY USED (make something completely different)
{recent}
"""
    if inspiration:
        prompt += ("\n## INSPIRATION\nTake only the core idea and the feeling of this piece and write a NEW, ORIGINAL story "
                   "from it: new characters, names, setting details, twist and ending. Never copy its sentences.\n\"\"\"\n"
                   + inspiration[:6000] + "\n\"\"\"\n")
    script, model = _run_text(prompt, api_key, lo, hi)
    log(f"Script written with {file.name} via {model} ({len(script.split())} words)")

    plan_prompt = SCENES_PROMPT.format(script=script) + _image_rules().format(sfx_list=sfx_list)
    story = _run_models(plan_prompt, api_key, temperature=0.4)
    story.update({"mode": "fiction", "subgenre": subgenre if "{subgenre}" in file.read_text(encoding="utf-8") else file.stem.replace("fiction_", "").replace("_", " "),
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

    if _prompt_files():
        story = _creator_story(history, api_key, sfx_list, inspiration)
        if inspiration and item:
            story["source"] = item["key"]
        words = sum(len(s["narration"].split()) for s in story["scenes"])
        log(f"Story '{story['title']}' ({words} words, {len(story['scenes'])} scenes) via {story['model']}")
        return story

    subgenre = pick_subgenre(history)
    recent = "\n".join(f"- {h['title']}: {h.get('premise', '')}" for h in history[-40:] if h.get("title")) or "- (none yet)"
    prompt = PROMPT.format(channel=CONFIG["channel_name"], subgenre=subgenre, recent=recent, sfx_list=sfx_list)
    if inspiration:
        prompt += (
            "\nINSPIRATION (from the creator). Take only the core idea and the feeling of this piece and write a NEW, "
            "ORIGINAL story from it: new characters, new names, new setting details, your own twist and ending. "
            "Never copy its sentences. Ignore the subgenre above if it doesn't fit.\n\"\"\"\n"
            + inspiration[:6000] + "\n\"\"\"\n")
    story = _run_models(prompt, api_key, temperature=1.0)
    rules = "pure fiction, TikTok-safe (no gore, self-harm, harm to children, sexual content), first person, plain spoken English, illustrated image prompts with a consistent character sheet and expressive faces"
    story = edit_story(story, api_key, sfx_list, rules)
    story.update({"mode": "fiction", "subgenre": subgenre})
    if inspiration and item:
        story["source"] = item["key"]
    words = sum(len(s["narration"].split()) for s in story["scenes"])
    log(f"Story '{story['title']}' ({words} words, {len(story['scenes'])} scenes) via {story['model']}")
    return story
