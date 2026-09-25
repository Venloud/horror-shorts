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
                },
                "required": ["narration", "image_prompt"],
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

STRUCTURE (follow exactly)
1. SCENE 1 = THE HOOK (spoken, 1-2 sentences, max 25 words). It must make a scroller stop in 2 seconds AND tell them what this story is about. Speak to the viewer or make a bold promise. Good patterns:
   - "If you ever [specific situation], don't [action]. I did, and [consequence hint]."
   - "I worked [job] for [time], and there was one rule I was never allowed to break."
   - "This is the scariest thing that ever happened to me, and it started with [small ordinary detail]."
   - "There's a reason I don't [ordinary thing] anymore."
   Never open mid-action. Never open with "So", "One night", or "This happened".
2. SCENE 2 = CONTEXT (1-2 sentences): who I am, where I was, when. Grounded and ordinary, e.g. "I was nineteen, working nights at a gas station off an empty highway."
3. SCENES 3+ = the story: build tension with concrete details (sounds, small wrong things). Put a twist around 75% through.
4. LAST SCENE = a chilling final line that lands hard or makes people replay. Do not explain the twist. No moral, no "and I never went back".

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


def write_story(history: list[dict]) -> dict:
    api_key = env("GEMINI_API_KEY")
    mode = pick_mode(history)

    if mode == "mystery":
        import mystery
        for _ in range(3):
            case = mystery.pick_case(history)
            try:
                prompt = mystery.build_prompt(CONFIG["channel_name"], case)
                story = _run_models(prompt, api_key, temperature=0.6)
                story.update({"mode": "mystery", "case": case, "subgenre": "real unsolved mystery"})
                log(f"Mystery '{story['title']}' ({len(story['scenes'])} scenes) via {story['model']}")
                return story
            except Exception as e:  # noqa: BLE001
                log(f"Mystery mode failed ({e}); trying another case")
                history = history + [{"case": case}]
        log("Falling back to fiction today")

    subgenre = pick_subgenre(history)
    recent = "\n".join(f"- {h['title']}: {h.get('premise', '')}" for h in history[-40:] if h.get("title")) or "- (none yet)"
    prompt = PROMPT.format(channel=CONFIG["channel_name"], subgenre=subgenre, recent=recent)
    story = _run_models(prompt, api_key, temperature=1.0)
    story.update({"mode": "fiction", "subgenre": subgenre})
    words = sum(len(s["narration"].split()) for s in story["scenes"])
    log(f"Story '{story['title']}' ({words} words, {len(story['scenes'])} scenes) via {story['model']}")
    return story
