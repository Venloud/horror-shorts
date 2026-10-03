"""Writes an original scary story + scene breakdown + TikTok caption with Gemini."""
import json
import random
import re
import time
from collections import Counter

import requests

from common import (CONFIG, env, gemini_model_out, gemini_out, log, mark_source, note_gemini_429, strip_marks,
                    trim_sources)

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

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
                    "image_location": {"type": "STRING"},
                    "image_location_2": {"type": "STRING"},
                    "image_location_3": {"type": "STRING"},
                    "image_location_4": {"type": "STRING"},
                    "image_source": {"type": "STRING"},
                    "image_source_2": {"type": "STRING"},
                    "image_source_3": {"type": "STRING"},
                    "image_source_4": {"type": "STRING"},
                    "image_query": {"type": "STRING"},
                    "image_query_2": {"type": "STRING"},
                    "image_query_3": {"type": "STRING"},
                    "image_query_4": {"type": "STRING"},
                },
                "required": ["narration", "image_prompt", "image_prompt_2", "image_prompt_3", "image_prompt_4", "sfx",
                             "image_location", "image_location_2", "image_location_3", "image_location_4",
                             "image_source", "image_source_2", "image_query", "image_query_2"],
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
        "hook_candidates": {"type": "ARRAY", "items": {"type": "STRING"}},
        "fact_ledger": {"type": "ARRAY", "items": {"type": "STRING"}},
        "hook_scores": {"type": "ARRAY", "items": {"type": "STRING"}},
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
{hooks}
If something fails, rewrite those scenes (and image_prompt, image_prompt_2 and sfx to match; the four image prompts must be different shots matching each quarter of the scene). Keep what already works. Keep the characters and locations lists, each scene's location and each image's image_location (update it if you change that image prompt).
Keep {words} words total, the same number of scenes or 7-9, and keep sfx values from this list only: {sfx_list}

DRAFT:
{draft}
"""


HOOKS_TASK = """7. HOOK CANDIDATES: score each candidate first sentence below from 1 to 10 (strangest or most shocking
detail in the first 6 words; the most ironic, specific or unbelievable real detail, not a summary of the event;
no date, year or place name; under 18 words; makes you NEED the next sentence). A candidate that is not literally
true per the story, or implies a cause/motive the source doesn't state, scores 0.
Put one line per candidate in "hook_scores" as "<score> | <sentence>", and start scene 1 with the highest-scoring
sentence, word for word.
{candidates}
"""


def edit_story(story: dict, api_key: str, sfx_list: str, rules: str) -> dict:
    """Second pass: an editor checks logic, ending, and hook payoff, then rewrites."""
    draft = {k: story[k] for k in SCHEMA["properties"] if k in story}
    cands = [c.strip() for c in story.get("hook_candidates") or [] if c.strip()]
    hooks = HOOKS_TASK.format(candidates="\n".join(f"- {c}" for c in cands)) if len(cands) >= 2 else ""
    prompt = EDITOR_PROMPT.format(draft=json.dumps(draft, ensure_ascii=False, indent=1),
                                  sfx_list=sfx_list, rules=rules, words="{} to {}".format(*CONFIG.get("story_words", [138, 152])), hooks=hooks)
    try:
        edited = _run_models(prompt, api_key, temperature=0.5)
        for k in ("characters", "locations", "fact_ledger"):  # keep the sheets + fact ledger if the editor dropped them
            if story.get(k) and not edited.get(k):
                edited[k] = story[k]
        log("Editor pass: story revised")
        if cands:
            edited["hook_candidates"] = cands
            use_best_hook(edited)
        return edited
    except Exception as e:  # noqa: BLE001
        log(f"Editor pass failed, keeping the first draft: {str(e)[:200]}")
        return story


def use_best_hook(story: dict) -> None:
    """Make scene 1 start with the editor's highest-scoring hook candidate (that isn't a slow opener)."""
    scored = []
    for line in story.get("hook_scores") or []:
        m = re.match(r"\s*(\d+(?:\.\d+)?)\s*\|\s*(.+)", str(line))
        if m:
            scored.append((float(m.group(1)), m.group(2).strip().strip('"')))
    if scored:
        log("Hook scores: " + " / ".join(f"{sc:g}: {txt[:60]}" for sc, txt in sorted(scored, reverse=True)))
    scored = [(sc, txt) for sc, txt in sorted(scored, reverse=True) if not hook_problem(txt)]
    if not scored or not story.get("scenes"):
        return
    best = scored[0][1]
    first = story["scenes"][0].get("narration", "")
    if first.lower().startswith(best.lower()[:40]):
        return
    end = re.search(r"[.!?…][\"”’)]?(?=\s|$)", first)
    rest = first[end.end():].strip() if end else ""
    story["scenes"][0]["narration"] = f"{best} {rest}".strip()
    log(f"Scene 1 now starts with the best-scoring hook: {best}")


RESIZE_PROMPT = """You are editing the narration of a short vertical video (JSON below). It is {now} words and must
be {want} words (+-5), so the voiceover lands in the target length. {how}
Rules: keep the same number of scenes and the same order; keep scene 1's FIRST sentence exactly; keep the exact
sentence "This is a true story." if it is there; do not add facts, names or events that are not already in the
story; keep the ending line's meaning. Only change image prompts of scenes whose content changed.
Never rewrite the factual content while changing the length: every number, name, date, place and factual claim
stays exactly the same (for true stories, the values in "fact_ledger" are locked). When shortening, remove
repetition and filler first; when extending, add only sensory or transitional wording the story already supports.
Return the whole story in the SAME JSON format.

STORY:
{draft}
"""


def resize_story(story: dict, api_key: str, want_words: int) -> dict:
    """Trim or extend the narration to about want_words, keeping structure and facts (used by the duration fit)."""
    now = sum(len(s["narration"].split()) for s in story["scenes"])
    how = ("Cut filler words and weaker details." if want_words < now else
           "Slow the telling down: add sensory detail and short beats that are already implied by the story.")
    draft = {k: story[k] for k in SCHEMA["properties"] if k in story}
    new = _run_models(RESIZE_PROMPT.format(now=now, want=want_words, how=how,
                                           draft=json.dumps(draft, ensure_ascii=False, indent=1)),
                      api_key, temperature=0.4)
    for k, v in story.items():  # keep everything the resize doesn't return (mode, source, flags...)
        new.setdefault(k, v)
    if new.get("mode") != "inbox-script":
        speak_numbers(new)
    got = sum(len(s["narration"].split()) for s in new["scenes"])
    log(f"Script resized: {now} -> {got} words (asked for {want_words})")
    return new


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
    if gemini_model_out(model):
        raise DailyLimit(f"{model} skipped: its daily quota is used up")
    body["contents"][0]["parts"][0]["text"] = strip_marks(prompt)
    _gemini_pace()
    r = requests.post(GEMINI_URL.format(model=model), json=body, timeout=120,
                      headers={"x-goog-api-key": api_key})
    if r.status_code == 429:
        note_gemini_429(r.text, model)
        if gemini_model_out(model):
            raise DailyLimit(f"{model} HTTP 429 daily quota: {r.text[:300]}")
        raise RateLimited(f"{model} HTTP 429 (per-minute limit): {r.text[:300]}", _retry_after(r))
    if r.status_code in (500, 502, 503, 504):
        raise Overloaded(f"{model} HTTP {r.status_code}: {r.text[:300]}")
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


class ApiBusy(RuntimeError):
    """Every writer is rate-limited / overloaded right now. NOT a topic problem: never switch topics on it; the
    build stops and the next one (or the checkpoint) tries again."""


class Overloaded(RuntimeError):
    """HTTP 500/502/503/504 ("model is currently experiencing high demand"): retry the same model with backoff."""


class RateLimited(RuntimeError):
    """A short rate limit (Gemini per-minute 429, Groq tokens/requests per MINUTE): wait and retry."""

    def __init__(self, msg: str, wait: float | None = None):
        super().__init__(msg)
        self.wait = wait


class DailyLimit(RuntimeError):
    """A per-DAY quota (Gemini PerDay 429, Groq TPD/RPD): this model is done for the run, next model."""


def _retry_after(r) -> float | None:
    """Seconds to wait from a Retry-After header, Gemini's retryDelay ("37s") or Groq's "try again in 1m2.5s"."""
    try:
        h = r.headers.get("retry-after")
        if h:
            return float(h)
    except (TypeError, ValueError):
        pass
    text = getattr(r, "text", "") or ""
    m = re.search(r'retryDelay"?\s*:\s*"(\d+(?:\.\d+)?)s"', text)
    if m:
        return float(m.group(1))
    m = re.search(r"try again in\s+(?:(\d+)m)?\s*(\d+(?:\.\d+)?)\s*(ms|s)\b", text, re.IGNORECASE)
    if m:
        secs = float(m.group(2)) / (1000 if m.group(3).lower() == "ms" else 1)
        return secs + 60 * int(m.group(1) or 0)
    return None


_OVERLOADED: set = set()  # a model that stayed 503 through a full 10/30/60 s backoff: skipped for the rest of the run


def model_chain(light: bool = False) -> list[str]:
    """Story writers in order: every Gemini model in config llm_models, strongest first (skipping ones whose DAILY
    quota is used up), then Groq (flag groq_backup, only if GROQ_API_KEY is set) as the last resort. Cloudflare's
    text models are never used. light=True (critic scores, premise pitches, packaging...): the "lite" models first,
    so small JSON calls don't use up the strong model's small free daily quota the story writing needs."""
    models = [m for m in CONFIG["llm_models"] if not gemini_model_out(m) and m not in _OVERLOADED]
    if light:
        models.sort(key=lambda m: "lite" not in m)
    if CONFIG.get("groq_backup", True) and env("GROQ_API_KEY", required=False):
        models.append("groq:" + CONFIG.get("groq_model", "openai/gpt-oss-120b"))
    if env("NVIDIA_API_KEY", required=False) or env("NVIDIA_NIM_API_KEY", required=False):
        models.append("nvidia:" + CONFIG.get("nvidia_text_model", "z-ai/glm-5.3-flash"))
    if env("MODELSCOPE_TOKEN", required=False) or env("MODELSCOPE_API_KEY", required=False):
        models.append("modelscope:" + CONFIG.get("modelscope_text_model", "Qwen/Qwen3.5-27B"))
    return models or list(CONFIG["llm_models"])


def _call_model(model: str, prompt: str, api_key: str, temperature: float = 1.0, as_json: bool = True, schema=None):
    if model.startswith("groq:"):
        return _call_groq(model[5:], prompt, temperature, as_json, schema)
    if model.startswith("nvidia:"):
        from providers import nvidia
        text = nvidia.chat(model[7:], prompt, temperature=temperature, as_json=as_json, schema=schema or SCHEMA)
        return json.loads(text) if as_json else text.strip()
    if model.startswith("modelscope:"):
        from providers import modelscope
        text = modelscope.chat(model[11:], prompt, temperature=temperature, as_json=as_json, schema=schema or SCHEMA)
        return json.loads(text) if as_json else text.strip()
    return _call_gemini(model, prompt, api_key, temperature, as_json, schema)


def _call_groq(model: str, prompt: str, temperature: float = 1.0, as_json: bool = True, schema=None):
    """Groq (OpenAI-compatible, JSON mode): same prompt; the response schema is spelled out in the prompt because
    JSON mode only guarantees valid JSON, not our fields."""
    if as_json:
        prompt += ("\n\nReply with ONLY one JSON object (no markdown) that follows this JSON schema exactly, "
                   "same field names:\n" + json.dumps(schema or SCHEMA))
    # Groq's free tier counts tokens per MINUTE: send a shorter source text (instructions stay whole)
    prompt = strip_marks(trim_sources(prompt, int(CONFIG.get("groq_source_chars", 3500))))
    body = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": min(1.0, temperature),
            "max_tokens": int(CONFIG.get("groq_max_tokens", 8000))}  # gpt-oss reasons first: room for both
    if as_json:
        body["response_format"] = {"type": "json_object"}
    for attempt in range(4):
        r = requests.post(GROQ_URL, json=body, timeout=120,
                          headers={"Authorization": f"Bearer {env('GROQ_API_KEY')}"})
        if r.status_code != 429:
            break
        text = r.text or ""
        # Only a per-DAY limit (tokens/requests per day) means Groq is done; per-MINUTE limits = wait + retry.
        if re.search(r"per day|\bTPD\b|\bRPD\b|tokens_per_day|requests_per_day", text, re.IGNORECASE):
            raise DailyLimit(f"groq:{model} HTTP 429 daily limit: {text[:300]}")
        wait = min(65.0, max(2.0, _retry_after(r) or 20.0 * (attempt + 1)))
        if attempt == 3:
            raise RateLimited(f"groq:{model} HTTP 429 (per-minute limit, 3 retries): {text[:300]}", wait)
        log(f"Groq rate limit (per minute): waiting {wait:.0f}s, then the same request again ({attempt + 1}/3)")
        time.sleep(wait)
    if r.status_code in (500, 502, 503, 504):
        raise Overloaded(f"groq:{model} HTTP {r.status_code}: {r.text[:300]}")
    if r.status_code != 200:
        raise RuntimeError(f"groq:{model} HTTP {r.status_code}: {r.text[:300]}")
    text = r.json()["choices"][0]["message"]["content"] or ""
    return json.loads(text) if as_json else text.strip()


def _writer(model: str) -> str:
    if model.startswith("groq:"):
        return f"groq ({model[5:]})"
    if model.startswith("nvidia:"):
        return f"nvidia ({model[7:]})"
    if model.startswith("modelscope:"):
        return f"modelscope ({model[11:]})"
    return f"gemini ({model})"


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
                and not str(h.get("mode", "")).startswith("inbox") and not h.get("remake_of"))
    return modes[count % len(modes)]


BACKOFF_503 = (10, 30, 60)  # overloaded model: retry the SAME model after 10 s, 30 s, 60 s, then the next model


def _with_models(call, what: str = "story", light: bool = False):
    """Run call(model) down model_chain() (every Gemini model first, Groq last):
    - 500/503 "high demand": same model again after 10 s, 30 s, 60 s, then the next model;
    - per-minute 429: wait the time the API asks for (max 65 s) and retry the same model (max 3 times);
    - per-DAY quota: next model at once; 404 / other errors: up to 3 tries; BLOCKED twice: next model.
    If every model failed only on rate limits / overload, raise ApiBusy (not a topic problem)."""
    errors, busy_only = [], True
    for model in model_chain(light):
        overloads = rates = attempt = 0
        while True:
            attempt += 1
            try:
                return call(model)
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                errors.append(f"{model}#{attempt}: {msg[:300]}")
                log(f"{what.capitalize()} attempt failed: {msg[:200]}")
                if isinstance(e, Overloaded) or ("503" in msg and "high demand" in msg.lower()):
                    if overloads < len(BACKOFF_503):
                        wait = BACKOFF_503[overloads]
                        overloads += 1
                        log(f"{model} is overloaded: trying it again in {wait}s ({overloads}/{len(BACKOFF_503)})")
                        time.sleep(wait)
                        continue
                    _OVERLOADED.add(model)  # still 503 after the whole backoff: don't wait on it again this run
                    log(f"{model} stayed overloaded through the backoff: skipping it for the rest of this run")
                    break
                if isinstance(e, RateLimited):
                    if rates < 3 and not model.startswith("groq:"):  # Groq already waited + retried 3 times
                        rates += 1
                        wait = min(65.0, max(2.0, e.wait or 20.0))
                        log(f"{model} rate limit: waiting {wait:.0f}s, then again ({rates}/3)")
                        time.sleep(wait)
                        continue
                    break
                if isinstance(e, DailyLimit):
                    break
                busy_only = False
                if "404" in msg or (model.startswith("groq:") and attempt >= 2):
                    break
                if "BLOCKED" in msg and attempt >= 2:
                    break
                if attempt >= 3:
                    break
                time.sleep(6 * attempt)
    detail = "\n".join(errors)
    if busy_only and errors:
        raise ApiBusy(f"Every writer is rate-limited or overloaded right now (not a topic problem):\n{detail}")
    raise RuntimeError(f"Could not write a {what}:\n{detail}")


def _run_models(prompt: str, api_key: str, temperature: float, patient: bool = True) -> dict:
    def call(model):
        story = _call_model(model, prompt, api_key, temperature)
        _validate(story)
        story["model"] = model
        story["writer"] = _writer(model)
        log(f"Written by {story['writer']}")
        if "lite" in model or model.startswith("groq:"):
            log(f"WARNING: story text written by {model}, a last-resort writer (the stronger Gemini models are out "
                "of daily quota or overloaded)")
        return story
    return _with_models(call)


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

SCORE_PROMPT = """You are a tough judge for a horror TikTok channel. Score this one-minute (61-68 second) narration script.
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
    for model in model_chain():
        try:
            r = _call_model(model, SCORE_PROMPT.replace("{script}", script), api_key, 0.2, as_json=True, schema=SCORE_SCHEMA)
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

# ---------- story upgrade (flags story_upgrade, critic_pass) ----------

UPGRADE_TRUE = """
STORY UPGRADE (true story)
- The hook is the strangest TRUE detail in the source. Never distort a fact to make it stronger.
- After watching, the viewer must be able to explain in one sentence what happened.
- Something new every 5-8 seconds: every scene adds at least one new verified fact (a detail, a number, a
  discovery). No filler, no repeating what was already said.
- Say the case, person or place name out loud early (scene 1 or 2), the way people search for it.
- No invented twists: a twist or reveal must be a real fact from the source.
- Caption line 1 = the phrase people type into search, e.g. "What happened to D.B. Cooper?"."""

UPGRADE_LORE = """
STORY UPGRADE (legend)
- A STORY WITH TENSION, never a fact list: one scenario (people, a place, something going wrong, a decision, a
  reveal, an ending) told the way the legend is told; every fact is woven into that scene. A script that reads
  like a list of facts ("X was a sign of Y. People believed Z.") fails.
- The hook is the most unsettling moment of that scenario, as the legend actually tells it. Never invent new lore.
- The viewer must be able to retell the legend in one sentence afterwards.
- Something new every 5-8 seconds: every scene moves the scenario forward with one new detail of the legend.
- Say the legend's name out loud early (scene 1 or 2), the way people search for it.
- Never talk about sources ("according to the sources", "from the sources", "folklore held", "according to
  folklore"): just tell it ("the story goes", "people swore").
- The creature is a character: in "characters" with a fixed look, and shown by name in 3+ shots incl. the hook shot.
- Caption line 1 = the phrase people type into search, e.g. "What is the Wendigo?"."""

STORY_SHAPES = {
    "discovery": "Someone finds something that should not exist; each detail about it makes it worse.",
    "strange rule": "An ordinary place or job has one strange rule; the story shows why the rule exists.",
    "gradual realization": "Small normal-looking details slowly add up to one horrifying realization.",
    "investigation": "Someone follows clues about one odd event; the last clue answers the hook.",
    "reversal": "The situation we think we understand flips: the victim, helper or threat was the opposite.",
    "uncanny normal": "Everything looks exactly normal, but one detail is wrong, and it keeps being wrong.",
}

UPGRADE_FICTION = """
## STORY UPGRADE
- The story is 90% normal, 10% wrong: an ordinary, believable situation with ONE thing that is wrong.
- Story shape for this one: {shape_name}: {shape}
- Build on this premise (already checked for clarity): {premise}
- The ending explains what happened (the viewer can say it in one sentence) and pays off the hook's first line.
- Caption line 1 = the phrase people would search, e.g. "The Guest Who Wasn't on the List"."""

PREMISE_PROMPT = """You pitch premises for a 50-second illustrated horror story ({kind}).
Story shape: {shape_name}: {shape}
{inspiration}
Already used (don't repeat): {recent}
Give 3 DIFFERENT premises. Each: ONE clear sentence with a concrete visual and a question the viewer needs
answered. 90% normal situation, 10% wrong. Adults only, no gore, no real people or real named towns.
Then judge each one strictly: "clarity" 1-10 (10 = crystal clear sentence, one burning question, one strong visual;
vague ones like "strange things happen in a house" get 3 or less) and "reason".
Return JSON: {{"premises": [{{"premise": "...", "question": "...", "visual": "...", "clarity": 0, "reason": "..."}}]}}"""

CRITIC_PROMPT = """You are a strict critic for a short illustrated horror / true-crime channel. Score this {kind}
story (JSON below) and give concrete reasons.
{rules}
Score (whole numbers): hook (max {m_hook}): the first sentence is the strangest {truth} detail, no date/place
opener; clarity (max {m_clarity}): the viewer can explain what happened in one sentence; pacing (max {m_pacing}):
something new every 5-8 seconds, no filler; name_early (max 10): the case/legend/place name is said in scene 1 or 2;
payoff (max 15): the ending answers the hook; integrity (max {m_integrity}): {integrity}.{story_rule}
Return JSON: {{"hook": 0, "clarity": 0, "pacing": 0, "name_early": 0, "payoff": 0, "integrity": 0,{story_key}
"what_happened": "one sentence", "reasons": ["concrete problem + concrete fix", ...]}}

STORY:
{draft}"""

CRITIC_MAX = {"hook": 20, "clarity": 20, "pacing": 20, "name_early": 10, "payoff": 15, "integrity": 15}
# legends: "story" = is this a story with tension (a scenario that escalates), not a list of facts
CRITIC_MAX_LEGEND = {"hook": 15, "clarity": 15, "pacing": 15, "name_early": 10, "payoff": 15, "integrity": 10,
                     "story": 20}
CRITIC_STORY = """
story (max 20): is this a STORY WITH TENSION? 20 = one concrete scenario (people, a place, something going wrong,
a decision, a reveal, an ending) that escalates scene by scene; 0-8 = a list of facts about the legend ("X was a
sign of Y. People believed Z. This was done to prevent W."), however well written. A fact list fails."""
SOURCE_TALK = re.compile(r"\b(according to (the )?(sources?|folklore|records)|from the sources?|the sources? (say|said|"
                         r"describe\w*|state\w*|mention\w*)|folklore (held|says|states|claims))\b", re.I)

CRITIC_REWRITE = """Rewrite this story (same JSON format) to fix these critic notes. Keep every fact, name, number
and the fact_ledger exactly; keep the number of scenes; keep scene 1's opening unless a note is about the hook.
{rules}
CRITIC NOTES:
{notes}

STORY:
{draft}"""


class StoryDiscarded(Exception):
    """The critic rejected a story after the allowed rewrites: throw it away, the next attempt tries again."""


def _json_call(prompt: str, api_key: str, temperature: float = 0.3) -> dict:
    """A small JSON answer (premise pitch, critic scores) from the model chain."""
    def call(model):
        if model.startswith("groq:"):
            return _call_groq(model[5:], prompt, temperature, True, {"type": "OBJECT"})
        if gemini_model_out(model):
            raise DailyLimit(f"{model}: daily quota used up")
        gen = {"temperature": temperature, "responseMimeType": "application/json"}
        _gemini_pace()
        r = requests.post(GEMINI_URL.format(model=model), timeout=90, headers={"x-goog-api-key": api_key},
                          json={"contents": [{"role": "user", "parts": [{"text": strip_marks(prompt)}]}],
                                "generationConfig": gen})
        if r.status_code == 429:
            note_gemini_429(r.text, model)
            if gemini_model_out(model):
                raise DailyLimit(f"{model} HTTP 429 daily quota")
            raise RateLimited(f"{model} HTTP 429 (per-minute limit)", _retry_after(r))
        if r.status_code in (500, 502, 503, 504):
            raise Overloaded(f"{model} HTTP {r.status_code}: {r.text[:200]}")
        if r.status_code != 200:
            raise RuntimeError(f"{model} HTTP {r.status_code}")
        parts = r.json()["candidates"][0]["content"]["parts"]
        return json.loads("".join(p.get("text", "") for p in parts))
    return _with_models(call, "JSON answer", light=True)


_PACE = {"last": 0.0}


def _gemini_pace() -> None:
    """Free-tier friendly: at least config gemini_min_interval seconds (4) between Gemini text calls."""
    gap = float(CONFIG.get("gemini_min_interval", 4)) - (time.time() - _PACE["last"])
    if gap > 0:
        time.sleep(gap)
    _PACE["last"] = time.time()


def pick_shape(history: list[dict]) -> str:
    """Rotate story shapes: the least recently used one (history `story_shape`)."""
    last_seen = {name: -1 for name in STORY_SHAPES}
    for n, h in enumerate(history):
        if h.get("story_shape") in last_seen:
            last_seen[h["story_shape"]] = n
    return min(STORY_SHAPES, key=lambda k: (last_seen[k], random.random()))


def pick_premise(history: list[dict], api_key: str, shape: str, kind: str, inspiration: str | None) -> dict:
    """Premise check before writing: one clear sentence with a question and a visual. Vague ones are rejected
    (clarity < 7); two rounds, then StoryDiscarded."""
    for round_ in range(2):
        ask = PREMISE_PROMPT.format(kind=kind, shape_name=shape, shape=STORY_SHAPES[shape],
                                    recent=recent_list(history)[-1500:],
                                    inspiration=("Inspired by (new original story, don't copy):\n" + inspiration[:1500])
                                    if inspiration else "")
        pitches = _json_call(ask, api_key, 0.9).get("premises") or []
        good = []
        for p in pitches:
            sent = str(p.get("premise", "")).strip()
            # one clear sentence (a two-beat line like "41 guests. 42 masks." is fine), a question, a visual
            ok = (sent and len(re.findall(r"[.!?](\s|$)", sent)) <= 2 and len(sent.split()) <= 40
                  and str(p.get("question", "")).strip() and len(str(p.get("visual", "")).split()) >= 3)
            score = int(p.get("clarity", 0) or 0) if ok else 0
            log(f"Premise ({score}/10): {sent[:140]}" + ("" if ok else " [rejected: not one clear sentence with a "
                                                                          "question and a visual]"))
            if score >= 7:
                good.append((score, p))
        if good:
            return max(good, key=lambda x: x[0])[1]
        log(f"Premise check round {round_ + 1}: all premises too vague")
    raise StoryDiscarded("no clear premise (every pitch was vague)")


def critic_pass(story: dict, api_key: str, kind: str, rules: str) -> dict:
    """One critic pass with scores + concrete reasons; up to 2 rewrites; still failing -> StoryDiscarded.
    kind: "true" (real events) or "legend". Rewrites keep every fact (the fact check runs after this)."""
    if not CONFIG.get("critic_pass", True):
        return story
    bar = int(CONFIG.get("critic_min_score", 75))
    truth = "TRUE" if kind == "true" else "legend's"
    integrity = ("only facts from the source, nothing invented, theories labelled" if kind == "true"
                 else "the legend as actually told, nothing invented")
    extra = UPGRADE_TRUE if kind == "true" else UPGRADE_LORE
    legend = kind != "true"
    maxes = CRITIC_MAX_LEGEND if legend else CRITIC_MAX
    for rnd in range(3):  # score, then up to 2 rewrites
        draft = json.dumps({k: story[k] for k in SCHEMA["properties"] if k in story}, ensure_ascii=False)
        try:
            r = _json_call(CRITIC_PROMPT.format(
                kind=kind, rules=extra, truth=truth, integrity=integrity, draft=draft,
                m_hook=maxes["hook"], m_clarity=maxes["clarity"], m_pacing=maxes["pacing"],
                m_integrity=maxes["integrity"], story_rule=CRITIC_STORY if legend else "",
                story_key=' "story": 0,' if legend else ""), api_key, 0.2)
        except Exception as e:  # noqa: BLE001
            log(f"Critic unavailable ({str(e)[:120]}); keeping the story")
            return story
        total = sum(max(0, min(int(r.get(k, 0) or 0), mx)) for k, mx in maxes.items())
        reasons = [str(x) for x in (r.get("reasons") or [])][:5]
        said = " ".join(sc.get("narration", "") for sc in story.get("scenes") or [])
        hard = []
        if legend and int(r.get("story", 0) or 0) < 12:  # a fact list fails whatever the total
            hard.append(f"story {r.get('story')}/20: this reads like a list of facts. Rewrite it as ONE scenario "
                        "with people, a place and rising tension (death, illness, suspicion, the grave opened, the "
                        "reveal, the remedy), weaving every fact into that scene")
        talk = SOURCE_TALK.search(said)
        if talk:
            hard.append(f"the narration says {talk.group(0)!r}: never talk about sources; just tell the legend")
        reasons = hard + reasons
        log(f"Critic {rnd + 1}: {total}/100 ({', '.join(f'{k} {r.get(k)}' for k in maxes)}). "
            f"What happened: {str(r.get('what_happened', ''))[:120]}. Notes: {' | '.join(reasons)[:400]}")
        story["critic_score"] = total
        if total >= bar and not hard:
            return story
        if rnd == 2:
            break
        try:
            new = _run_models(CRITIC_REWRITE.format(rules=rules[:6500], notes="\n".join(f"- {x}" for x in reasons),
                                                    draft=draft), api_key, temperature=0.5)
            for k in ("characters", "locations", "fact_ledger", "hook_candidates"):
                if story.get(k) and not new.get(k):
                    new[k] = story[k]
            story = {**story, **new}
            log(f"Critic rewrite {rnd + 1} done")
        except Exception as e:  # noqa: BLE001
            log(f"Critic rewrite failed ({str(e)[:120]}); keeping the story")
            return story
    raise StoryDiscarded(f"critic score {story.get('critic_score')}/100 after 2 rewrites (needs {bar})")



COLD_CASE_FILE = "fiction_cold_case.txt"


def _prompt_files() -> list:
    from common import ROOT
    # fiction_cold_case.txt is only for the "coldcase" mode, never picked for normal fiction
    return sorted(p for p in (ROOT / "prompts").glob("fiction*.txt") if p.name != COLD_CASE_FILE)


def _run_text(prompt: str, api_key: str, lo: int, hi: int, patient: bool = True) -> tuple[str, str]:
    def call(model):
        text = _call_model(model, prompt, api_key, 1.0, as_json=False)
        n = len(text.split())
        if not lo * 0.8 <= n <= hi * 1.3:
            raise ValueError(f"story length {n} words, wanted {lo}-{hi}")
        return text, model
    return _with_models(call)


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
The narration must be {lo} to {hi} words in total (about {round(lo / 2.3)}-{round(hi / 2.3)} seconds read aloud). Count them.

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
    prompt = prompt.replace("{place_note}", (
        "- Do not open with the location, date, year, job title or background. Open with the strangest thing that "
        "happened. Reveal where and when after the hook.\n"))
    shape, premise = None, None
    if CONFIG.get("story_upgrade", True):
        shape = pick_shape(history)
        try:
            premise = pick_premise(history, api_key, shape, "original cold case file" if cold_case else subgenre,
                                   inspiration)
        except StoryDiscarded:
            raise
        except Exception as e:  # noqa: BLE001 (premise check unavailable: write as before)
            log(f"Premise check unavailable ({str(e)[:120]}); writing without it")
        if premise:
            log(f"Shape: {shape}. Premise: {premise.get('premise')}")
            prompt += UPGRADE_FICTION.format(shape_name=shape, shape=STORY_SHAPES[shape],
                                             premise=f"{premise.get('premise')} (question: {premise.get('question')}; "
                                                     f"visual: {premise.get('visual')})")
    if inspiration:
        prompt += ("\n## INSPIRATION\nTake only the core idea and the feeling of this piece and write a NEW, ORIGINAL story "
                   "from it: new characters, names, setting details, twist and ending. Never copy its sentences.\n\"\"\"\n"
                   + mark_source(inspiration[:6000]) + "\n\"\"\"\n")
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
    story.update({"mode": "coldcase" if cold_case else "fiction", "subgenre": subgenre, "prompt_file": file.name, "script_model": model, "writer": _writer(model),
                  "score": score, "what_happened": review.get("what_happened", ""), "story_shape": shape,
                  "checked_premise": (premise or {}).get("premise")})
    return story


REAL_STORY_IMAGES = """

THIS SCRIPT IS A REAL STORY about real people. Real people are shown with normal visible faces in the channel's
illustrated style, matching only basic public facts (approximate age, hair, clothing, era). Do NOT try to copy a
real private person's actual face. Historical figures (dead 100+ years) may follow known portraits. Masked or
hooded figures are fine when the story fits (thieves, disguises). Each real person gets a "characters" entry with a
fixed look that is reused word-for-word in every shot they appear in. Match the real places and time period."""


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


def _true_story(facts: str, name: str, api_key: str, sfx_list: str, notes: str = "",
                holder: dict | None = None) -> dict:
    """Fact-locked retelling of a real story; the model may refuse unsafe topics with title SKIP.
    Research (Gemini + Google Search grounding) is appended to the source first; notes = owner instructions."""
    import mystery
    import research
    holder = {} if holder is None else holder
    facts = research.add_to(facts, holder, name, "true story", notes)
    prompt = mystery.TRUE_PROMPT.format(channel=CONFIG["channel_name"], case=name, facts=mark_source(facts),
                                        words="{} to {}".format(*CONFIG.get("story_words", [138, 152])),
                                        sfx_list=sfx_list)
    if CONFIG.get("story_upgrade", True):
        prompt += UPGRADE_TRUE
    if notes:
        prompt += "\n\nOWNER NOTES (instructions, not facts; facts only from the SOURCE):\n" + notes
    story = _run_models(prompt, api_key, temperature=0.6)
    flag = story.get("title", "").strip().upper()
    if flag == "INSPIRATION":
        raise UseAsInspiration(facts)
    if flag == "SKIP":
        raise RuntimeError("source is not a real story, skipping")
    rules = (f'scene 1 = the hook sentence, then the exact words "{TRUE_OPENER}"; '
             "ONLY facts from this source, never invent details; only call someone guilty if convicted or confessed; "
             "respectful; no gore; third person; plain English; real people drawn in the illustrated style from basic "
             "public facts only (never a copy of a private person's real face), each with a fixed character-sheet "
             "look; RESEARCH lines marked RUMOR only as rumor ('it was rumored', 'some say'), never as fact."
             + (("\nOWNER NOTES: " + notes[:1500]) if notes else "")
             + "\nSOURCE:\n" + mark_source(facts[:9000]))
    story = edit_story(story, api_key, sfx_list, rules)
    story = fix_hook(story, api_key, sfx_list, rules)
    story = critic_pass(story, api_key, "true", rules)  # before the fact check, which then checks any rewrite
    story = fact_check(story, facts, api_key)
    story["sources"] = holder.get("sources", [])
    log(f"True story '{story['title']}' ({len(story['scenes'])} scenes) via {story['model']}")
    return story


TRUE_OPENER = "This is a true story."
TRUE_MODES = ("case", "mystery", "inbox-true")  # real events; NOT lore (legends) and NOT fiction


def with_true_opener(text: str) -> str:
    """Put "This is a true story." right AFTER the hook sentence (never first: that's a slow opener).
    If the text already has it somewhere after the start (e.g. after a two-sentence hook), leave it there."""
    if re.search(r"\S.*?this is a true story", text.strip(), re.IGNORECASE | re.DOTALL) and not re.match(
            r"\s*this is a true story", text, re.IGNORECASE):
        return text.strip()
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
        scenes = story["scenes"]
        # Never said twice: if ANY scene already says it (an owner's script split by the planner put it in scene 2),
        # nothing is added; extra copies after the first are removed.
        pat = re.compile(r"\s*this is a true story[.!]?", re.IGNORECASE)
        seen = False
        for sc in scenes:
            text = sc.get("narration", "")
            parts = pat.split(text)
            hits = pat.findall(text)
            if not hits:
                continue
            keep = "" if seen else hits[0]
            out = parts[0] + keep + "".join(parts[1:])
            sc["narration"] = re.sub(r"\s{2,}", " ", out).strip()
            seen = True
        if not seen:
            scenes[0]["narration"] = with_true_opener(scenes[0].get("narration", ""))
    return story


FACT_PROMPT = """You are the fact checker of a TRUE-story video. These details in the narration are NOT found in the
SOURCE: {items}.
The story's "fact_ledger" lists the locked values; correct it too if one of its values is not in the SOURCE.
Fix each one from the SOURCE: use the exact number, amount, date, year, name, place or organization the source
gives, or drop the detail if the source doesn't have it. Change nothing else: same scenes, same order, about the
same length; keep scene 1's first sentence unless it contains one of these details; keep the exact sentence
"This is a true story."; keep image prompts unless the detail is in them. Write numbers the way they are spoken
("two hundred thousand dollars", "nineteen seventy-one"), never digits or slang ("twenty-k").
Return the whole story in the SAME JSON format.

SOURCE:
{source}

STORY:
{draft}
"""
_CAPS_OK = {"i", "this", "true", "story"}


def unsupported_details(text: str, source: str) -> list[str]:
    """Numbers (> 10), money, years, and capitalized names/places/organizations in the narration that don't
    appear in the source. Numbers match however they're written ($200,000 = two hundred thousand)."""
    import spoken_numbers as nums
    src_vals, src_low = nums.values(source), source.lower()
    items = []
    for m in re.finditer(r"\b(\d+|[a-z]+(?:-[a-z]+)?)[- ]?k\b", text, re.IGNORECASE):  # slang: "20k", "twenty-k"
        if m.group(1).isdigit() or nums.values(m.group(1).replace("-", " ")):
            items.append(f'the slang amount "{m.group(0)}" (say the full amount from the source)')
    for v in sorted(nums.values(text)):
        if v > 10 and v not in src_vals:
            items.append(f"the number {int(v) if v == int(v) else v:,}")
    for sent in re.split(r"(?<=[.!?])\s+", text):
        for w in re.findall(r"[A-Za-z][A-Za-z'.-]*", sent)[1:]:   # skip the sentence's first word
            name = re.sub(r"'s$|[.'-]+$", "", w)
            if name[:1].isupper() and name.lower() not in _CAPS_OK and name.lower() not in src_low:
                items.append(f'the name "{name}"')
    return list(dict.fromkeys(items))


def fact_check(story: dict, source: str, api_key: str, exact: bool = False) -> dict:
    """True stories, BEFORE voicing: every number/amount/date/year/name/place/organization must be in the source.
    Unsupported ones are corrected from the source by Gemini. exact=True (owner's TRUE SCRIPT): only log them."""
    text = " ".join(s["narration"] for s in story.get("scenes", []))
    ledger = [str(x) for x in story.get("fact_ledger") or []]
    if ledger:
        log(f"Fact ledger ({len(ledger)} values): " + " | ".join(ledger)[:600])
        bad = unsupported_details(" ".join(v.split(":", 1)[-1] for v in ledger), source)
        if bad:
            log(f"Fact ledger values NOT found in the source (ignored): {', '.join(bad)}")
    items = unsupported_details(text, source)  # the source is the authority; the ledger is extracted from it
    if not items:
        log("Fact check: every number and name in the narration is in the source")
        return story
    if exact:
        log(f"Fact check (owner's script, NOT changed), please double-check: {', '.join(items)}")
        return story
    log(f"Fact check: not in the source: {', '.join(items)}; correcting from the source")
    draft = {k: story[k] for k in SCHEMA["properties"] if k in story}
    try:
        fixed = _run_models(FACT_PROMPT.format(items=", ".join(items), source=mark_source(source[:8000]),
                                               draft=json.dumps(draft, ensure_ascii=False, indent=1)),
                            api_key, temperature=0.2)
    except Exception as e:  # noqa: BLE001
        log(f"Fact check correction failed ({str(e)[:150]}), keeping the story as it is")
        return story
    for k, v in story.items():
        fixed.setdefault(k, v)
    for old, new in zip(story["scenes"], fixed["scenes"]):
        if old["narration"] != new["narration"]:
            log(f"Fact check correction: '{old['narration']}' -> '{new['narration']}'")
    left = unsupported_details(" ".join(s["narration"] for s in fixed["scenes"]), source)
    log("Fact check: all fixed" if not left else f"Fact check: still not found in the source: {', '.join(left)}")
    return fixed


def speak_numbers(story: dict) -> None:
    """Digits -> spoken words in the narration ('$200,000' -> 'two hundred thousand dollars')."""
    import spoken_numbers as nums
    for s in story.get("scenes", []):
        new = nums.spoken(s.get("narration", ""))
        if new != s.get("narration"):
            s["narration"] = new


def _transient(e: Exception) -> bool:
    """API overload / quota / network trouble (or a critic discard): try again later, never a reason to drop a
    story for good."""
    if isinstance(e, StoryDiscarded):
        return True
    msg = str(e).lower()
    return any(k in msg for k in ("503", "429", "high demand", "quota", "timed out", "timeout", "connection",
                                  "rate-limited", "overloaded",
                                  "temporarily", "unavailable", "could not write a story"))


def write_story(history: list[dict]) -> dict:
    skipped: list[dict] = []
    story = _write_story(history, skipped)
    mark_true_story(story)
    if story.get("mode") != "inbox-script":  # the owner's exact words are never changed
        speak_numbers(story)
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
            if item.get("topic"):  # REMAKE / LORE / TRUE topic file
                return topic_story(history, item, api_key, sfx_list)
            if item["kind"] == "script":
                log("Inbox SCRIPT: narrating it exactly as written, only adding visuals")
                if item.get("true"):
                    text = with_true_opener(text)
                story = plan_scenes(text, api_key, sfx_list, real=item.get("true", False))
                story.update({"mode": "inbox-script", "source": item["key"], "subgenre": "creator script",
                              "true_story": bool(item.get("true"))})
                if item.get("true"):  # owner's own text: used as-is, never rewritten; just list what to double-check
                    import spoken_numbers as nums
                    vals = sorted(v for v in nums.values(text) if v > 10)
                    names = sorted({w for w in re.findall(r"(?<![.!?]\s)(?<!^)\b[A-Z][a-z]+(?:'s)?", text)})
                    log(f"TRUE SCRIPT used as-is (owner's text, not rewritten). Numbers: "
                        f"{', '.join(f'{int(v):,}' for v in vals) or 'none'}; names: {', '.join(names) or 'none'}")
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
            reason = f"{type(e).__name__}: {str(e)[:300]}"
            history = history + [{"source": item["key"]}]  # not again in this run
            if _transient(e) or item.get("kind") == "script" or item.get("topic"):
                # Gemini busy / quota / network, or the owner's own script: keep it queued for the next build.
                log(f"Inbox item {item['key']} NOT made this time, it stays queued for the next build. "
                    f"Reason: {reason}")
                if isinstance(e, ApiBusy):
                    raise
            else:
                log(f"Inbox item {item['key']} SKIPPED for good. Reason: {reason}")
                skipped.append({"source": item["key"], "skipped": True, "reason": reason})
            item = None

    # 2) FBI case files
    if mode == "case" and not inspiration:
        for _ in range(3):
            case = sources.next_case(history)
            try:
                story = _true_story(sources.case_facts(case), case["title"], api_key, sfx_list)
                story.update({"mode": "case", "case": case["title"], "subgenre": "true crime case file"})
                return story
            except ApiBusy:
                log(f"Case '{case['title']}' not made now (writers rate-limited / overloaded); it stays available")
                raise
            except UseAsInspiration as e:
                log(f"'{case['title']}' is too sensitive to retell: using it as inspiration for an original story")
                skipped.append({"case": case["title"], "skipped": True})
                inspiration = e.facts
                break
            except Exception as e:  # noqa: BLE001
                reason = f"{type(e).__name__}: {str(e)[:300]}"
                history = history + [{"case": case["title"]}]
                if _transient(e):
                    log(f"Case '{case['title']}' not made this time (stays available). Reason: {reason}")
                else:
                    log(f"Case '{case['title']}' skipped for good. Reason: {reason}")
                    skipped.append({"case": case["title"], "skipped": True, "reason": reason})
        log("Falling back to fiction today")

    # 3) Original fake case file (fiction; never gets the TRUE STORY label)
    if mode == "coldcase" and not inspiration:
        try:
            story = _creator_story(history, api_key, sfx_list, None, cold_case=True)
            words = sum(len(s["narration"].split()) for s in story["scenes"])
            log(f"Cold case '{story['title']}' ({words} words, {len(story['scenes'])} scenes) via {story['model']}")
            return story
        except ApiBusy:
            log("Cold case: the writers are rate-limited / overloaded: stopping (not a reason to switch topics)")
            raise
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


REMAKE_BLOCK = """
## REMAKE: THIS TOPIC WAS ALREADY MADE ONCE
Make a NEW video about the same legend. Same facts, a completely different story angle.
OLD VERSION (never reuse its hook, its opening line, its title, its ending or its scene-by-scene structure):
{old}
NEW ANGLE: {angle}
- Open on the new angle's strangest detail (a different first sentence, different hook overlay, different title).
- Build the scenes around the new angle; do not walk through the old video's beats in the old order.
- ANGLE / HOOK / OWNER NOTES are instructions, never facts: a detail they mention may only be used if the SOURCE
  (Wikipedia + RESEARCH lines) states it too; otherwise leave it out.
- Facts only from the SOURCE. If a source describes a custom for revenants/vampires in general, say so; never
  claim it was specific to this legend unless the source says that.
{notes}"""


def _too_close(a: str, b: str, limit: float = 0.6) -> bool:
    from difflib import SequenceMatcher
    na, nb = re.sub(r"[^a-z0-9 ]", "", a.lower()).split(), re.sub(r"[^a-z0-9 ]", "", b.lower()).split()
    if not na or not nb:
        return False
    return SequenceMatcher(None, na, nb).ratio() > limit or (len(na) >= 5 and na[:5] == nb[:5])


LORE_TOPIC_BLOCK = """
## OWNER'S TOPIC
ANGLE: {angle}
{hook}- ANGLE / HOOK / OWNER NOTES are instructions, never facts: a detail they mention may only be used if the
  SOURCE (Wikipedia + RESEARCH lines) states it too; otherwise leave it out.
- Facts only from the SOURCE (Wikipedia + RESEARCH lines). RUMOR lines only as rumor. If a source describes a
  custom for revenants / spirits in general, say so; never claim it belongs to this legend unless a source says so.
{notes}"""


def _wiki_sources(item: dict, topic: str, holder: dict) -> str:
    import mystery
    facts = ""
    for src in item.get("sources") or [topic]:
        try:
            facts += f"\n\n=== SOURCE: Wikipedia - {src} ===\n" + mystery.fetch_facts(src, 6000)
            holder.setdefault("sources", []).append({"title": f"Wikipedia: {src}", "url": mystery.wiki_url(src),
                                                     "domain": mystery.wiki_url(src).split("/")[2]})
        except Exception as e:  # noqa: BLE001
            log(f"Source '{src}' skipped ({str(e)[:120]})")
    if not facts:
        raise RuntimeError(f"{topic}: no Wikipedia source text could be read")
    return facts


_CHILD_WORDS = re.compile(r"\b(bab(y|ies)|infants?|newborns?|toddlers?|child(ren)?|kids?|little ones?)\b", re.I)
_HARM_WORDS = re.compile(r"\b(drain\w*|suck\w*|kill\w*|feed\w*|prey\w*|attack\w*|blood|bite\w*|devour\w*|"
                         r"murder\w*|eat\w*|harm\w*|die[sd]?|death)\b", re.I)


def child_harm(story: dict) -> str:
    """The first narration sentence that puts a child together with harm, or ''."""
    for sc in story.get("scenes") or []:
        for sent in re.split(r"(?<=[.!?])\s+", sc.get("narration", "")):
            if _CHILD_WORDS.search(sent) and _HARM_WORDS.search(sent):
                return sent
    return ""


def _true_line_after_hook(story: dict, hook: str) -> None:
    """A multi-sentence owner HOOK that opens scene 1 keeps "This is a true story." AFTER the whole hook."""
    scenes = story.get("scenes") or []
    if not hook or not scenes:
        return
    text = re.sub(r"\s*this is a true story[.!]?\s*", " ", scenes[0]["narration"], flags=re.IGNORECASE).strip()
    words = len(hook.split())
    head = " ".join(text.split()[:words])
    if not _too_close(head, hook, 0.8):
        return  # the story doesn't open with the owner's hook: mark_true_story places the line as usual
    rest = " ".join(text.split()[words:])
    scenes[0]["narration"] = f"{head} {TRUE_OPENER} {rest}".strip()


def topic_story(history: list[dict], item: dict, api_key: str, sfx_list: str) -> dict:
    """Inbox topic files: REMAKE (new lore video about a topic we already made: new angle / hook / structure /
    images), LORE (a legend) or TRUE (a real story). The topic comes from the file, so the "topic already used"
    pick (mystery.pick_case) is bypassed for that topic only. Sources: the listed Wikipedia pages + research."""
    import mystery
    topic, kind = item["topic"], item["kind"]
    notes = "\n".join(x for x in [item.get("text", "")] if x)
    holder: dict = {}
    if kind == "true":
        facts = _wiki_sources(item, topic, holder)
        brief = "\n".join(x for x in [
            f"ANGLE: {item['angle']}" if item.get("angle") else "",
            f"HOOK: scene 1 opens with this sentence if the SOURCE supports it: {item['hook']}" if item.get("hook") else "",
            notes] if x)
        story = _true_story(facts, topic, api_key, sfx_list, notes=brief, holder=holder)
        story.update({"mode": "inbox-true", "source": item["key"], "subgenre": "true story", "case": topic,
                      "true_story": True, "no_child_images": item.get("no_children", False)})
        _true_line_after_hook(story, item.get("hook", ""))
        return story

    old, avoid, num = {}, list(item.get("avoid", [])), ""
    if kind == "remake":
        old = next((h for h in reversed(history) if not h.get("skipped") and (
            str(h.get("case") or "").lower() == topic.lower() or topic.lower() in str(h.get("title", "")).lower())), {})
        avoid = [x for x in [old.get("title"), old.get("premise"), old.get("twist")] if x] + avoid
        num = f"#{old['video_number']}" if old.get("video_number") else f"posted {old.get('date', '?')}"
    angle = item.get("angle") or ("a different detail of the legend than the old video led with" if kind == "remake"
                                  else "the strangest detail of the legend as it is told")
    if kind == "remake":
        log(f"Remake of {old.get('title') or topic} ({num}): new angle '{angle[:110]}{'...' if len(angle) > 110 else ''}'")
    else:
        log(f"Inbox lore topic: {topic}; angle '{angle[:110]}'")
    facts = _wiki_sources(item, topic, holder)
    prompt, facts = mystery.build_prompt(CONFIG["channel_name"], {"title": topic, "source": "Wikipedia", "url": "",
                                                                  "text": facts}, sfx_list, "lore", holder=holder)
    hook = f"- HOOK: scene 1 opens with this sentence if the SOURCE supports it: {item['hook']}\n" if item.get("hook") else ""
    owner = ("OWNER NOTES (instructions, not facts):\n" + notes) if notes else ""
    block = (REMAKE_BLOCK.format(old="\n".join(f"- {x}" for x in avoid), angle=angle, notes=hook + owner)
             if kind == "remake" else LORE_TOPIC_BLOCK.format(angle=angle, hook=hook, notes=owner))
    rules = ("ONLY facts from this source, never invent details; legends clearly labelled as legends; RUMOR lines only "
             "as rumor; respectful to the culture it comes from; no gore; third person; plain English"
             + ("; NEW angle, never the old video's hook or opening" if kind == "remake" else "")
             + (("\nOWNER NOTES: " + notes[:1500]) if notes else "") + "\nSOURCE:\n" + mark_source(facts[:9000]))
    extra = ""
    for attempt in range(3):
        story = _run_models(prompt + UPGRADE_LORE + block + extra, api_key, temperature=0.8)
        story = edit_story(story, api_key, sfx_list, rules)
        story = fix_hook(story, api_key, sfx_list, rules)
        story = critic_pass(story, api_key, "legend", rules)
        opening = re.split(r"(?<=[.!?])\s+", story["scenes"][0]["narration"].strip())[0]
        reused = [x for x in avoid if _too_close(opening, x) or _too_close(story.get("hook_overlay", ""), x)
                  or _too_close(story.get("title", ""), x, 0.85)]  # a title may share the legend's name
        harm = child_harm(story) if item.get("no_children") else ""
        said = " ".join(sc.get("narration", "") for sc in story.get("scenes") or []).lower()
        banned = [b for b in item.get("ban", []) if b in said]
        if banned:
            log(f"Draft {attempt + 1} uses a banned (unsourced) detail ({banned[0]!r}); writing it again")
            extra = (f"\n\nYOUR LAST DRAFT MENTIONED {banned[0]!r}, which is NOT in the source. Leave it out "
                     "completely; use only facts the SOURCE states.")
            continue
        if not reused and not harm:
            break
        if harm:
            log(f"Draft {attempt + 1} describes harm to a child ({harm[:80]!r}); writing it again")
            extra = (f"\n\nYOUR LAST DRAFT DESCRIBED HARM TO A CHILD: {harm!r}. Never describe or show harm to a "
                     "child or infant; keep any victims off-screen or adult; focus on the creature, the night, the "
                     "village and the protections.")
            continue
        log(f"Draft {attempt + 1} reused the old version ({reused[0][:80]!r}); writing it again")
        extra = (f"\n\nYOUR LAST DRAFT REUSED THE OLD VIDEO: {reused[0]!r}. Use a different first sentence, "
                 "hook overlay and title built on the NEW ANGLE.")
    else:
        raise RuntimeError(f"{topic}: every draft reused the old video, described harm to a child or used a banned detail")
    story.update({"mode": "lore", "case": topic, "subgenre": "legend / folklore", "source": item["key"],
                  "true_story": False, "sources": holder.get("sources", []),
                  "no_child_images": item.get("no_children", False)})
    if kind == "remake":
        story.update({"remake_of": old.get("title") or topic, "remake_angle": angle})
    log(f"{'Remake' if kind == 'remake' else 'Lore'} '{story['title']}' ({len(story['scenes'])} scenes) via "
        f"{story.get('model')}; opening: {opening!r}")
    return story


def _real_story(history: list[dict], mode: str, api_key: str, sfx_list: str) -> dict | None:
    """A real legend (lore) or unsolved mystery, fact-locked to its Wikipedia source."""
    if True:
        import mystery
        for _ in range(3):
            case = mystery.pick_case(history, mode)
            try:
                holder: dict = {}
                prompt, facts = mystery.build_prompt(CONFIG["channel_name"], case, sfx_list, mode, holder=holder)
                if CONFIG.get("story_upgrade", True):
                    prompt += UPGRADE_TRUE if mode == "mystery" else UPGRADE_LORE
                story = _run_models(prompt, api_key, temperature=0.6)
                rules = ((f'scene 1 = the hook sentence, then the exact words "{TRUE_OPENER}"; ' if mode == "mystery" else "")
                         + "ONLY facts from this source, never invent details; theories/legends clearly labelled; "
                         "no accusing real people; respectful; no gore; third person; plain English.\nSOURCE:\n" + mark_source(facts[:6000]))
                story = edit_story(story, api_key, sfx_list, rules)
                story = fix_hook(story, api_key, sfx_list, rules)
                story = critic_pass(story, api_key, "true" if mode == "mystery" else "legend", rules)
                if mode == "mystery":  # real events: fact check (lore = legends, not checked)
                    story = fact_check(story, facts, api_key)
                lead = case if isinstance(case, dict) else None  # discovery lead: keep its source page
                story["sources"] = holder.get("sources", []) + ([{"title": lead["title"], "url": lead["url"]}]
                                                                if lead else [])
                story.update({"mode": mode, "case": lead["title"] if lead else case,
                              "subgenre": "real unsolved mystery" if mode == "mystery" else "legend / folklore"})
                if lead:
                    story.update({"source": lead["url"], "source_name": lead.get("source")})
                log(f"{mode.title()} '{story['title']}' ({len(story['scenes'])} scenes) via {story['model']}")
                return story
            except ApiBusy:
                log(f"{mode}: the writers are rate-limited / overloaded, not a topic problem: stopping here "
                    "(the next build tries again)")
                raise
            except Exception as e:  # noqa: BLE001
                log(f"{mode} mode failed ({str(e)[:200]}); trying another topic")
                history = history + ([{"case": case["title"], "source": case["url"]}] if isinstance(case, dict)
                                     else [{"case": case}])
    return None
