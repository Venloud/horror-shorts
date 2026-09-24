"""Writes an original scary story + scene breakdown + TikTok caption with Gemini."""
import json
import random
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
The story is read aloud by a calm, low narrator over dark images. Write an ORIGINAL story.

SUBGENRE FOR TODAY: {subgenre}

HARD RULES
- Pure fiction. No real people, real crimes, real victims, real brands, or real named towns/addresses.
- TikTok-safe: tension and dread, not gore. No graphic violence, no self-harm, no suicide, nothing involving harm to children, no sexual content.
- First person, past tense ("I"), plain spoken English like someone telling it at 2am. Short sentences. No fancy words.
- 150 to 190 words of narration total. This is strict; count them.
- Sentence 1 is the HOOK: it must make someone stop scrolling within 2 seconds. Start mid-situation with a specific, unsettling detail. Never start with "So", "One night", "This happened", or "I never believed".
- Build tension with concrete details (sounds, small wrong things). Put a twist around 70-80% of the way through.
- The LAST line must land hard: a chilling reveal or a line that makes people replay. Do not explain the twist. No moral, no "and I never went back".
- Split the narration into 7 to 9 scenes. Each scene is 1-3 sentences, and each needs an image.

IMAGE PROMPTS
- One per scene, describing a single still frame that matches that moment. Concrete subject + setting + lighting + camera angle.
- Show places, objects, silhouettes, and shadows. Faces should be hidden, in shadow, blurred, or turned away. No text, signs, or writing in the image. No blood or gore.
- Keep the same main setting and character look consistent across scenes (repeat key details like "the narrator, a man in a grey hoodie").

OTHER FIELDS
- title: 3-7 word internal title.
- premise: one sentence summary (used to avoid repeating stories).
- hook_overlay: 3-7 word on-screen text for the first seconds, curiosity-driven, e.g. "Never answer the second knock". No emojis.
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


def _call_gemini(model: str, prompt: str, api_key: str) -> dict:
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 1.0,
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
    if not 5 <= len(scenes) <= 11:
        raise ValueError(f"bad scene count {len(scenes)}")
    words = sum(len(s["narration"].split()) for s in scenes)
    if not 110 <= words <= 240:
        raise ValueError(f"narration length {words} words out of range")
    if not 0 <= int(story.get("twist_scene", 0)) < len(scenes):
        story["twist_scene"] = max(0, len(scenes) - 2)


def write_story(history: list[dict]) -> dict:
    api_key = env("GEMINI_API_KEY")
    subgenre = pick_subgenre(history)
    recent = "\n".join(f"- {h['title']}: {h.get('premise', '')}" for h in history[-40:]) or "- (none yet)"
    prompt = PROMPT.format(channel=CONFIG["channel_name"], subgenre=subgenre, recent=recent)

    errors = []
    for model in CONFIG["llm_models"]:
        for attempt in range(3):
            try:
                story = _call_gemini(model, prompt, api_key)
                _validate(story)
                story["subgenre"] = subgenre
                story["model"] = model
                words = sum(len(s["narration"].split()) for s in story["scenes"])
                log(f"Story '{story['title']}' ({words} words, {len(story['scenes'])} scenes) via {model}")
                return story
            except Exception as e:  # noqa: BLE001
                errors.append(f"{model}#{attempt + 1}: {e}")
                log(f"Story attempt failed: {e}")
    raise RuntimeError("Could not write a story:\n" + "\n".join(errors))
