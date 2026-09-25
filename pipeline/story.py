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
                    "sfx": {"type": "STRING"},
                },
                "required": ["narration", "image_prompt", "sfx"],
            },
        },
        "twist_scene": {"type": "INTEGER"},
        "caption": {"type": "STRING"},
        "hashtags": {"type": "ARRAY", "items": {"type": "STRING"}},
        "pinned_comment": {"type": "STRING"},
    },
    "required": ["title", "premise", "hook_overlay", "scenes", "twist_scene",
                 "caption", "hashtags", "pinned_comment"],
}

PROMPT = """You write viral short-form horror stories for a faceless TikTok channel called "{channel}".
The story is read aloud by a calm, low narrator over dark painted images. Write an ORIGINAL story.

SUBGENRE FOR TODAY: {subgenre}

STRUCTURE (follow exactly). The story must be COMPLETE and LOGICAL, like a good campfire story.
First, silently plan: (a) the threat and its ONE clear rule (what it is, what it wants, what triggers it), (b) the hook's promise, (c) the ending that pays off that promise. Then write.
1. SCENE 1 = THE HOOK (spoken, 1-2 sentences, max 25 words): a strong promise that stops the scroll. Patterns:
   - "If you ever [specific situation], don't [action]. I did, and [consequence hint]."
   - "I worked [job] for [time], and there was one rule I was never allowed to break."
   - "There's a reason I [strange habit] every night."
   Never open mid-action. Never open with "So", "One night", or "This happened".
2. SCENE 2 = CONTEXT (1-2 sentences): who I am, where I was, when. Grounded and ordinary.
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
- TikTok-safe: tension and dread, not gore. No graphic violence, no self-harm, no suicide, nothing involving harm to children, no sexual content.
- First person, past tense, plain spoken English like someone telling it at 2am. Short sentences. No fancy words.
- 170 to 210 words of narration total. This is strict; count them.
- 8 to 10 scenes total. Each scene is 1-3 sentences and gets one image.

IMAGE PROMPTS
- One per scene, describing a single painted frame for that moment: subject + setting + lighting + composition.
- Dark oil-painting look, NOT a photo. Describe it like a painting ("painted scene of...").
- Show places, objects, silhouettes, and shadows. Faces hidden, in shadow, or turned away. No text or writing in the image. No blood or gore.
- Keep the setting and the main character's look consistent (repeat key details like "the narrator, a young man in a grey hoodie").
- Scene 1's image must be the most striking, eerie image of the whole story (it is the thumbnail).

SOUND EFFECTS
- For each scene, set "sfx" to ONE sound from this list that is literally happening in that moment, or "none": {sfx_list}
- Use sound effects on 3 to 5 scenes only. Most important: the climax. Never on the hook scene.

OTHER FIELDS
- title: 3-7 word internal title.
- premise: one sentence summary (used to avoid repeating stories).
- hook_overlay: 3-6 word on-screen title shown big during the hook, curiosity-driven, e.g. "The rule I broke" or "Never answer the second knock". No emojis.
- twist_scene: the 0-based index of the scene where the twist hits.
- caption: TikTok caption, 1-2 short lines, ending with a question that makes people comment (e.g. "Would you have opened it?"). Max 150 characters. May use 1 emoji.
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
5. Is the hook strong enough to stop a scroller in 2 seconds?
6. Same rules as before: {rules}

If something fails, rewrite those scenes (and image prompts / sfx to match). Keep what already works.
Keep {words} words total, the same number of scenes or 8-10, and keep sfx values from this list only: {sfx_list}

DRAFT:
{draft}
"""


def edit_story(story: dict, api_key: str, sfx_list: str, rules: str) -> dict:
    """Second pass: an editor checks logic, ending, and hook payoff, then rewrites."""
    draft = {k: story[k] for k in SCHEMA["required"] if k in story}
    prompt = EDITOR_PROMPT.format(draft=json.dumps(draft, ensure_ascii=False, indent=1),
                                  sfx_list=sfx_list, rules=rules, words="170 to 210")
    try:
        edited = _run_models(prompt, api_key, temperature=0.5)
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


def _call_gemini(model: str, prompt: str, api_key: str, temperature: float = 1.0) -> dict:
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "responseMimeType": "application/json",
            "responseSchema": SCHEMA,
        },
    }
    r = requests.post(GEMINI_URL.format(model=model), json=body, timeout=120,
                      headers={"x-goog-api-key": api_key})
    if r.status_code != 200:
        raise RuntimeError(f"{model} HTTP {r.status_code}: {r.text[:400]}")
    data = r.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text)


def _validate(story: dict) -> None:
    scenes = story.get("scenes") or []
    if not 6 <= len(scenes) <= 12:
        raise ValueError(f"bad scene count {len(scenes)}")
    words = sum(len(s["narration"].split()) for s in scenes)
    if not 140 <= words <= 250:
        raise ValueError(f"narration length {words} words out of range")
    if not 0 <= int(story.get("twist_scene", 0)) < len(scenes):
        story["twist_scene"] = max(0, len(scenes) - 2)


def pick_mode(history: list[dict]) -> str:
    """Rotate through the story modes in config (e.g. fiction, mystery, fiction, mystery...)."""
    modes = CONFIG.get("story_modes", ["fiction"])
    last = next((h.get("mode", "fiction") for h in reversed(history)), None)
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
                time.sleep(8 * (attempt + 1))
    raise RuntimeError("Could not write a story:\n" + "\n".join(errors))


def sfx_names() -> str:
    from common import ROOT
    names = sorted(p.stem for p in (ROOT / "assets" / "sfx").glob("*.mp3"))
    return ", ".join(names + ["none"])


def write_story(history: list[dict]) -> dict:
    api_key = env("GEMINI_API_KEY")
    mode = pick_mode(history)
    sfx_list = sfx_names()

    if mode in ("mystery", "lore"):
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

    subgenre = pick_subgenre(history)
    recent = "\n".join(f"- {h['title']}: {h.get('premise', '')}" for h in history[-40:] if h.get("title")) or "- (none yet)"
    prompt = PROMPT.format(channel=CONFIG["channel_name"], subgenre=subgenre, recent=recent, sfx_list=sfx_list)
    story = _run_models(prompt, api_key, temperature=1.0)
    rules = "pure fiction, TikTok-safe (no gore, self-harm, harm to children, sexual content), first person, plain spoken English, painted image prompts with hidden faces"
    story = edit_story(story, api_key, sfx_list, rules)
    story.update({"mode": "fiction", "subgenre": subgenre})
    words = sum(len(s["narration"].split()) for s in story["scenes"])
    log(f"Story '{story['title']}' ({words} words, {len(story['scenes'])} scenes) via {story['model']}")
    return story
