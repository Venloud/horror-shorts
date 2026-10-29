"""Writes an original scary story + scene breakdown + TikTok caption with Gemini."""
import json
import random
import re
import time
from pathlib import Path
from collections import Counter

import requests

from common import (CONFIG, blocked_topic, env, gemini_model_out, gemini_out, is_gemini_auth_error, log, mark_source,
                    note_gemini_429, note_gemini_auth, strip_marks,
                    trim_sources)

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
STYLE_FILE = Path(__file__).resolve().parent.parent / "docs" / "NIGHT_FILES_STORYTELLING_STYLE.md"

def shared_style(prompt: str) -> str:
    """Use one checked-in voice/style standard across ALL model calls."""
    return "NIGHT FILES SHARED STYLE:\n" + STYLE_FILE.read_text(encoding="utf-8") + "\n\nTASK:\n" + prompt


SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "title": {"type": "STRING"},
        "premise": {"type": "STRING"},
        "central_question": {"type": "STRING"},
        "understanding_shift": {"type": "STRING"},
        "ending_payoff": {"type": "STRING"},
        "recurring_visual_motif": {"type": "STRING"},
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


def edit_story(story: dict, api_key: str, sfx_list: str, rules: str, kind: str | None = None,
               source: str | None = None) -> dict:
    """Second pass: an editor checks logic, ending, and hook payoff, then rewrites. With a kind, an edit that the
    objective checks measure as WORSE (e.g. moves the central event later) is dropped and the draft is kept."""
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
        if cands:
            edited["hook_candidates"] = cands
            use_best_hook(edited)
        if kind:
            before, after = writing_checks(story, kind, source), writing_checks(edited, kind, source)
            if check_score(after) < check_score(before):
                log(f"Editor pass measured worse ({check_score(before)} -> {check_score(after)}: {_brief(after)[:160]})"
                    "; keeping the draft")
                return story
        for k in ("writing", "writer_comparison", "model", "writer"):  # who wrote it stays on record
            if story.get(k) and not edited.get(k):
                edited[k] = story[k]
        log("Editor pass: story revised")
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
    """Pick a fresh subgenre, with an analytics-driven priority lane for proven topics."""
    import repeat_guard
    allowed = [s for s in CONFIG["subgenres"] if not blocked_topic(s)]
    subs = [s for s in allowed if not repeat_guard.repeat_of(s, history=history)] or allowed
    recent = [h.get("subgenre") for h in history[-len(subs):]]
    counts = Counter(recent)

    # Analytics can promote a proven content cluster without destroying the normal
    # least-recently/least-often-used rotation. A priority topic cannot repeat inside
    # the configured recent window, so a strong search signal does not become spam.
    priority = [s for s in CONFIG.get("priority_subgenres", []) if s in subs]
    probability = float(CONFIG.get("priority_subgenre_probability", 0))
    recent_window = max(0, int(CONFIG.get("priority_subgenre_recent_window", 0)))
    blocked = set(recent[-recent_window:]) if recent_window else set()

    if priority and probability > 0 and random.random() < probability:
        candidates = [s for s in priority if s not in blocked]
        if candidates:
            choice = random.choice(candidates)
            log(f"Priority topic selected: {choice}")
            return choice

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
        from common import GEMINI
        raise DailyLimit(f"{model} skipped: " + ("Gemini refused this run's key/project" if GEMINI.get("auth")
                                                  else "its daily quota is used up"))
    body["contents"][0]["parts"][0]["text"] = strip_marks(prompt)
    _gemini_pace()
    r = requests.post(GEMINI_URL.format(model=model), json=body, timeout=60,
                      headers={"x-goog-api-key": api_key})
    if is_gemini_auth_error(r.status_code, r.text):  # suspended project / bad key: Gemini is done for the run
        note_gemini_auth(r.status_code, r.text, f"story writer ({model})")
        raise DailyLimit(f"{model} HTTP {r.status_code} auth/permission: {r.text[:300]}")
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
    if env("OPENROUTER_API_KEY", required=False):
        for name in CONFIG.get("openrouter_models", []):
            if isinstance(name, str) and name.strip():
                models.append("openrouter:" + name.strip())
    return list(dict.fromkeys(models or list(CONFIG["llm_models"])))


def _call_model(model: str, prompt: str, api_key: str, temperature: float = 1.0, as_json: bool = True, schema=None, timeout_seconds=None):
    prompt = shared_style(prompt)
    if model.startswith("openrouter:"):
        return _call_openrouter(model[11:], prompt, temperature, as_json, schema)
    if model.startswith("groq:"):
        return _call_groq(model[5:], prompt, temperature, as_json, schema)
    if model.startswith("nvidia:"):
        from providers import nvidia
        text = nvidia.chat(model[7:], prompt, temperature=temperature, as_json=as_json, schema=schema or SCHEMA,
                           **({"timeout_seconds": timeout_seconds} if timeout_seconds is not None else {}))
        return json.loads(text) if as_json else text.strip()
    if model.startswith("modelscope:"):
        from providers import modelscope
        text = modelscope.chat(model[11:], prompt, temperature=temperature, as_json=as_json, schema=schema or SCHEMA)
        return json.loads(text) if as_json else text.strip()
    return _call_gemini(model, prompt, api_key, temperature, as_json, schema)


def _call_openrouter(model: str, prompt: str, temperature: float = 1.0, as_json: bool = True, schema=None):
    """Optional OpenRouter model fallback; unavailable without a configured key."""
    if as_json:
        prompt += "\n\nReturn ONLY a JSON object following this schema: " + json.dumps(schema or SCHEMA)
    payload = {"model": model, "messages": [{"role": "user", "content": strip_marks(prompt)}],
               "temperature": min(1.0, temperature), "max_tokens": int(CONFIG.get("openrouter_max_tokens", 8000))}
    if as_json:
        payload["response_format"] = {"type": "json_object"}
    r = requests.post(OPENROUTER_URL, json=payload, timeout=120,
                      headers={"Authorization": f"Bearer {env('OPENROUTER_API_KEY')}"})
    if r.status_code == 429:
        raise RateLimited(f"openrouter:{model} HTTP 429", _retry_after(r))
    if r.status_code in (500, 502, 503, 504):
        raise Overloaded(f"openrouter:{model} HTTP {r.status_code}")
    if r.status_code != 200:
        raise RuntimeError(f"openrouter:{model} HTTP {r.status_code}: {r.text[:200]}")
    content = r.json()["choices"][0]["message"]["content"] or ""
    return json.loads(content) if as_json else content.strip()


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
    if model.startswith("openrouter:"):
        return f"openrouter ({model[11:]})"
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
    import os
    forced = (os.environ.get("STORY_MODE") or "").strip().lower()
    if forced:  # test workflows only (explainer_test.yml story_mode input)
        return forced
    count = sum(1 for h in history if h.get("title") and not h.get("skipped")
                and not str(h.get("mode", "")).startswith("inbox") and not h.get("remake_of"))
    return modes[count % len(modes)]


BACKOFF_503 = (5,)  # one brief retry, then mark model unavailable for the rest of this run


def _with_models(call, what: str = "story", light: bool = False):
    """Run call(model) down model_chain() (every Gemini model first, Groq last):
    - 500/503 "high demand": retry once after 5 s, then skip this model for the remainder of this run;
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
                if isinstance(e, (Overloaded, requests.exceptions.Timeout)) or ("503" in msg and "high demand" in msg.lower()):
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



# ---------- bounded multi-model writing (owner, Oct 24) ----------
# One primary draft (writer chain: Gemini first, automatic fallback), at most ONE challenger draft (DeepSeek), ONE
# independent comparison by a model that wrote neither draft, at most ONE targeted revision. Objective checks
# (writing_checks) decide what is a real problem; subjective scores guide but never discard a finished story.

TITLE_GENERIC = set(("the a an of in at on and or to for from with by mysterious mystery strange unsolved true story "
                     "legend tale case curious secret dark haunting haunted last final real untold shocking creepy "
                     "night files file who what why how that this inside behind".split()))
TITLE_EVENTS = (  # a title's central event -> the words that tell it in the narration
    (r"disappear|vanish|missing|lost", r"disappear\w*|vanish\w*|missing|lost|never (?:seen|found|heard)|no trace"),
    (r"murder|killing|killer|slay", r"murder\w*|kill\w*|slain|stabbed|shot|strangled"),
    (r"death|died|dead", r"death|died|dead|dying|killed|body"),
    (r"crash|wreck|sinking|sank", r"crash\w*|wreck\w*|sank|sink\w*|went down"),
    (r"heist|robbery|theft|stolen", r"heist|rob\w*|theft|stole\w*|stolen|took"),
    (r"haunt|ghost|curse", r"haunt\w*|ghost\w*|curse\w*|spirit\w*|apparition"),
)
UNNATURAL = re.compile(r"\byou (?:watch|follow|witness|observe|see (?:her|him|them|how|as)|listen as|track how|"
                       r"look on as|stand (?:by|there) as)\b", re.IGNORECASE)
BIOGRAPHY = re.compile(r"\b(born in|was born|grew up|growing up|childhood|as a (?:child|girl|boy|kid)|early life|"
                       r"(?:her|his) parents|went to school)\b", re.IGNORECASE)
UNCERTAIN = re.compile(r"\b(theor\w*|believe\w*|rumou?r\w*|some (?:say|think|believe)|may have|might have|possibly|"
                       r"perhaps|unknown|never (?:found|solved|explained)|no one knows|nobody knows|evidence|"
                       r"suggest\w*|claim\w*|clue\w*|explanation\w*|still (?:unsolved|missing))\b", re.IGNORECASE)
FINAL_ANSWER = re.compile(r"\b(convicted|confessed|solved|found guilty|ruled|identified|turned out|the truth|"
                          r"was found|were found|revealed|explains?)\b", re.IGNORECASE)


def writing_kind(story: dict) -> str:
    """true (documented real events), lore (legends: told as belief) or fiction (invented: never as fact)."""
    if story.get("true_story") or story.get("mode") in TRUE_MODES:
        return "true"
    return "lore" if story.get("mode") == "lore" else "fiction"


def _narr(story: dict) -> str:
    if not story.get("scenes") and story.get("script"):
        return str(story["script"])
    return " ".join(sc.get("narration", "") for sc in story.get("scenes") or [])


def title_terms(title: str, case: str = "") -> tuple[list[str], str | None]:
    """(subject words the narration must say, event regex or None) from the title (+ the case name)."""
    words = re.findall(r"[A-Za-z][A-Za-z'.-]+", f"{title} {case}")
    events = "|".join(key for key, _ in TITLE_EVENTS)
    subject = [w.strip(".'").lower() for w in words if w[:1].isupper() and w.lower() not in TITLE_GENERIC
               and len(w) > 2 and not re.match(events, w.lower())]  # event words: checked with their synonyms
    low = (title or "").lower()
    event = next((rx for key, rx in TITLE_EVENTS if re.search(key, low)), None)
    return list(dict.fromkeys(subject)), event


# Continuity: a consequence the story states (death, a broken spine, unconsciousness, ropes, blindness) followed by the
# SAME character doing what that consequence rules out, with nothing in between that undoes it.
_REF = r"(?:he|she|they|him|her|his|their|them|[A-Z][a-z]+)"
INCAPACITY = [  # (state, pattern, what it rules out, what undoes it)
    ("dead", r"\b(?:killed|kills|dies|died|dead|lifeless|beheaded|decapitated|bled out|bleeds out|drowned|drowns|"
             r"stopped breathing|stops breathing|heart stopped|crushed to death|torn apart|ripped apart|eaten alive|"
             r"devoured|throat (?:was |is )?(?:slit|slashed|cut|torn (?:out|open)|ripped (?:out|open))|"
             r"neck (?:was |is )?(?:snapped|snaps|broken|broke)|"
             r"(?:tore|tears|ripped|rips|slit|slits|cut|cuts|slashed|slashes) (?:open )?(?:her|his|their|[A-Z][a-z]+'s) "
             r"throat(?: open| out)?|(?:snapped|snaps|broke|breaks) (?:her|his|their|[A-Z][a-z]+'s) neck)\b",
     "any", r"\b(?:ghost|spirit|came back|comes back|rose|rises|risen|returned from the dead|undead|revenant|"
            r"dream\w*|nightmare|vision|survived|survives|somehow|miraculous\w*|versions?|tellings?|"
            r"(?:legend|story|stories) (?:says?|claims?)|was not dead|wasn't dead|only pretended|faked|theor\w*|believ\w*|"
            r"some say|may have|might have|perhaps|earlier|before (?:that|this|then|she|he|they)|years before|"
            r"flashback|had been)\b"),
    ("paralysed", r"\b(?:paraly[sz]ed|(?:legs?|spine|back|ankles?|knees?) (?:was |were |is |are )?(?:broken|shattered|"
                  r"snapped|crushed)|(?:broke|breaks|snapped|snaps|shattered|crushed) (?:her|his|their|[A-Z][a-z]+'s) "
              r"(?:legs?|spine|back|ankles?)|could(?:n't| not) move)\b",
     "move", r"\b(?:healed|recovered|crawl\w*|drag\w* (?:her|him|them)sel\w+|limp\w*|feeling returned|"
             r"could move again|was carried|were carried|is carried)\b"),
    ("unconscious", r"\b(?:knocked (?:out|unconscious)|(?:lost|loses) consciousness|passed out|passes out|"
                    r"unconscious|blacked out|blacks out|fainted|faints)\b",
     "any", r"\b(?:woke|wakes|awoke|awakens?|awakened|came to|comes to|regained|opened (?:her|his|their) eyes|"
            r"hours later|the next (?:morning|day)|later)\b"),
    ("bound", r"\b(?:chained|shackled|tied (?:up|down|to)|bound (?:hand|to|with)|pinned (?:down|beneath|under|to)|"
              r"trapped (?:beneath|under)|nailed (?:shut|to))\b",
     "move", r"\b(?:broke free|breaks free|freed|frees|untied|unties|wriggled|slipped (?:free|out|loose)|pulled free|"
             r"cut (?:the|her|his|their) (?:ropes?|bonds|chains?)|loosened|let (?:her|him|them) go|released)\b"),
    ("blinded", r"\b(?:blinded|eyes (?:were |are )?(?:gouged|torn out|burned out|put out)|went blind|goes blind)\b",
     "see", r"\b(?:sight returned|could see again|healed|recovered)\b"),
]
_ACTIONS = {
    "move": r"\b(?:(?:ran|runs|run)(?! out of| low)|fled|flees|escaped|escapes|bolted|bolts|sprinted|sprints|raced|races|climbed|climbs|"
            r"walked|walks|jumped|jumps|leapt|leaps|dashed|dashes|got up|gets up|stood up|stands up|drove|drives|"
            r"stumbled|stumbles|hurried|hurries|chased|chases|made it (?:out|home|back))\b",
    "see": r"\b(?:saw|sees|see|watched|watches|read|reads|spotted|spots|noticed|notices|looked|looks)\b",
    "speak": r"\b(?:screamed|screams|shouted|shouts|said|says|whispered|whispers|told|tells|called|calls|spoke|speaks|"
             r"answered|answers)\b",
}
_ACTIONS["any"] = "|".join(_ACTIONS[k] for k in ("move", "see", "speak"))
_PRONOUN = {"he": "he", "him": "he", "his": "he", "she": "she", "her": "she", "they": "they", "them": "they",
            "their": "they"}
_NOT_NAMES = {"The", "A", "An", "This", "That", "Then", "When", "But", "And", "In", "On", "At", "It", "Its", "No",
              "One", "Every", "Some", "Nobody", "Something", "Someone", "There", "Her", "His", "She", "He", "They",
              "Their", "Him", "Them", "What", "Who", "Why", "How", "If", "As", "After", "Before", "By", "For", "Only"}


def _ref(token: str) -> str | None:
    if token.lower() in _PRONOUN and token not in ("Her", "His", "Their") or token in ("Her", "His", "Their", "He",
                                                                                       "She", "They", "Him", "Them"):
        return _PRONOUN.get(token.lower())
    return token if token[:1].isupper() and token not in _NOT_NAMES else None


def _victim(sentence: str, m: re.Match) -> str | None:
    """Who the consequence happened to: the word right after an active verb ("killed her"), the owner of the body
    part ("her neck snapped"), else the nearest person before it ("Mara was knocked out")."""
    inside = re.search(r"\b(her|his|their|[A-Z][a-z]+(?='s))\b", m.group(0))
    if inside and inside.start() > 0:
        return _ref(inside.group(1))
    after = re.match(r"\s+(" + _REF + r")\b", sentence[m.end():])
    if after and m.group(0).split()[0].lower() in ("killed", "kills", "beheaded", "decapitated", "drowned", "drowns",
                                                   "blinded", "paralysed", "paralyzed", "chained", "shackled"):
        return _ref(after.group(1))
    before = re.findall(r"\b(" + _REF + r")\b", sentence[:m.start()])
    owner = re.search(r"\b(her|his|their|[A-Z][a-z]+'s)\s+$", sentence[:m.start()])
    if owner:
        return _ref(owner.group(1).removesuffix("'s"))
    third = re.search(r"\b(?:her|his|their|[A-Z][a-z]+'s)\s+(?:\w+\s+){0,2}?([a-z]+)\s+(?:was |is |were |are )?$",
                      sentence[:m.start()], re.IGNORECASE)
    if third:  # "her husband died": the consequence is someone else's
        return None
    for tok in reversed(before):
        r = _ref(tok)
        if r:
            return r
    return None


def _actor(sentence: str, verb_at: int) -> str | None:
    """The subject of an action: the last person named before the verb, within the clause."""
    clause = re.split(r"[,;:]|\b(?:and|but|while|as|when)\b", sentence[:verb_at])[-1]
    for tok in reversed(re.findall(r"\b(" + _REF + r")\b", clause)):
        if tok.lower() in ("him", "her", "them", "his", "their"):  # objects / possessives are not the subject
            continue
        r = _ref(tok)
        if r:
            return r
    return None


def continuity_findings(text: str) -> list[dict]:
    """Contradictions inside one story, quoted: e.g. "her spine snapped" ... later "she ran for the door" with no
    recovery in between. Deterministic and conservative: same character reference only (a name or the same pronoun),
    a stated consequence only (never a guess about an injury's severity)."""
    sents = [x.strip() for x in re.split(r"(?<=[.!?])\s+", text) if x.strip()]
    out, seen = [], set()
    for i, s in enumerate(sents):
        for state, rx, rules_out, undo in INCAPACITY:
            for m in re.finditer(rx, s, re.IGNORECASE):
                who = _victim(s, m)
                if not who:
                    continue
                names = [t for t in re.findall(r"\b[A-Z][a-z]+\b", " ".join(sents[max(0, i - 1):i]) + " " +
                                                s[:m.start()]) if _ref(t) == t]
                alias = {who} | ({names[-1]} if who in ("he", "she") and names else set())
                for j in range(i, len(sents)):
                    later = sents[j] if j > i else s[m.end():]
                    act = None
                    for a in re.finditer(_ACTIONS[rules_out], later, re.IGNORECASE):
                        if re.search(undo, later[:a.start()], re.IGNORECASE):
                            break
                        if _actor(later, a.start()) in alias:
                            act = a
                            break
                    if re.search(undo, later, re.IGNORECASE) and not act:
                        break  # undone (woke, broke free, a ghost...) before any contradiction
                    if act:
                        key = (state, who, j)
                        if key not in seen:
                            seen.add(key)
                            out.append({"code": "contradiction", "severity": "revise",
                                        "detail": f"'{s[max(0, m.start() - 30):m.end() + 12].strip()}' ({who}: {state}), "
                                                  f"then '{later[max(0, act.start() - 30):act.end() + 20].strip()}' "
                                                  "with nothing that undoes it"})
                        break
    return out


def writing_checks(story: dict, kind: str | None = None, source: str | None = None) -> list[dict]:
    """Deterministic, evidence-based checks of a script (no LLM). Each: {code, severity, detail} with severity
    serious (demonstrable: blocks if it survives the revision), revise (one targeted revision) or advisory.
    Never a judgement of taste: every finding quotes or locates what it found."""
    kind = kind or writing_kind(story)
    out = []
    text = _narr(story)
    low = text.lower()
    words = low.split()
    n = max(1, len(words))

    def first_at(rx: str) -> float | None:
        m = re.search(rx, low)
        return None if not m else len(low[:m.start()].split()) / n

    title = str(story.get("title") or "")
    if title and title.upper() not in ("SKIP", "INSPIRATION"):
        subject, event = title_terms(title, str(story.get("case") or ""))
        if subject:
            at = min((first_at(rf"\b{re.escape(w)}") for w in subject if first_at(rf"\b{re.escape(w)}") is not None),
                     default=None)
            if at is None:  # fiction titles are invented after the script: a creative title is not a wrong story
                out.append({"code": "off_title", "severity": "serious" if kind != "fiction" else "revise",
                            "detail": f"the title's subject ({', '.join(subject[:3])}) is never said"})
            elif at > 0.25:
                out.append({"code": "late_subject", "severity": "revise",
                            "detail": f"the title's subject is first named {at:.0%} into the narration"})
        if event:
            at = first_at(event)
            if at is None:
                out.append({"code": "off_title", "severity": "serious" if kind != "fiction" else "revise",
                            "detail": f"the title promises '{re.search(r'[a-z]+', event).group(0)}...', the narration "
                                      "never tells it"})
            elif at > 0.35:
                out.append({"code": "late_event", "severity": "revise",
                            "detail": f"the title's central event first appears {at:.0%} into the narration"})
            bio = first_at(BIOGRAPHY.pattern)
            if at is not None and bio is not None and bio < at and at > 0.2:
                out.append({"code": "setup_first", "severity": "revise",
                            "detail": f"biography ('{BIOGRAPHY.search(low).group(0)}') comes before the central "
                                      "event"})
    for m in UNNATURAL.finditer(text):
        out.append({"code": "unnatural_voice", "severity": "revise", "detail": f"'{m.group(0)}'"})
    grams = Counter(" ".join(words[k:k + 4]) for k in range(len(words) - 3))
    rep = [g for g, c in grams.items() if c >= 3 and len([w for w in g.split() if len(w) > 3]) >= 2]
    if rep:
        out.append({"code": "repetitive", "severity": "advisory", "detail": f"'{rep[0]}' x{grams[rep[0]]}"})
    starts = Counter(s.split()[0].lower() for s in re.split(r"(?<=[.!?])\s+", text) if s.split())
    common = [w for w, c in starts.items() if c >= 4 and w not in ("the", "this", "it")]
    if common:
        out.append({"code": "repetitive", "severity": "advisory",
                    "detail": f"{starts[common[0]]} sentences open with '{common[0]}'"})
    out += continuity_findings(text)  # revise-level: one targeted revision, never a block
    if text.count("?") > 3:
        out.append({"code": "forced_questions", "severity": "advisory", "detail": f"{text.count('?')} questions"})
    tail = " ".join(sc.get("narration", "") for sc in (story.get("scenes") or [])[-2:])
    if kind == "true" and story.get("mode") in ("mystery", "inbox-true") and tail \
            and not UNCERTAIN.search(tail) and not FINAL_ANSWER.search(tail):
        out.append({"code": "empty_ending", "severity": "advisory",
                    "detail": "the ending names no evidence, theory, outcome or open fact"})
    if kind == "fiction" and re.search(r"\b(this is a true story|true story|really happened|based on real)\b", low):
        out.append({"code": "fiction_as_fact", "severity": "serious",
                    "detail": "an invented story presents itself as true"})
    if kind == "true" and source:
        import spoken_numbers as nums
        src = nums.values(source)
        bad = sorted(int(v) for v in nums.values(text) if v > 10 and v not in src)
        if bad:  # numbers / years are precise evidence; capitalised names are only logged by fact_check
            out.append({"code": "unsupported_fact", "severity": "serious",
                        "detail": "not in the source: " + ", ".join(f"{v:,}" for v in bad[:6])})
    return out


def check_score(checks: list[dict]) -> int:
    """Objective quality for ranking drafts: 100 minus 30 per serious, 10 per revise, 3 per advisory finding."""
    weight = {"serious": 30, "revise": 10, "advisory": 3}
    return max(0, 100 - sum(weight.get(c["severity"], 0) for c in checks))


def _severity(checks: list[dict], level: str) -> list[dict]:
    return [c for c in checks if c["severity"] == level]


def _record(story: dict) -> dict:
    return story.setdefault("writing", {"llm_calls": 0, "revisions": 0})


def _available(model: str) -> bool:
    if model.startswith("groq:"):
        return bool(env("GROQ_API_KEY", required=False))
    if model.startswith("nvidia:"):
        return bool(env("NVIDIA_API_KEY", required=False) or env("NVIDIA_NIM_API_KEY", required=False))
    if model.startswith("modelscope:"):
        return bool(env("MODELSCOPE_TOKEN", required=False) or env("MODELSCOPE_API_KEY", required=False))
    if model.startswith("openrouter:"):
        return bool(env("OPENROUTER_API_KEY", required=False))
    return not gemini_model_out(model) and model not in _OVERLOADED


def _family(model: str) -> str:
    """deepseek / gemini / gpt-oss / qwen / glm...: a judge of the same family as an author is not independent."""
    m = model.lower()
    for fam in ("deepseek", "gemini", "gpt-oss", "qwen", "glm", "llama"):
        if fam in m:
            return fam
    return m


def judge_models(authors: set) -> list[str]:
    """Independent critics: config writer_judge_models first (GPT-OSS 120B), then any other available model; never
    a model (or model family) that wrote one of the drafts."""
    fams = {_family(a) for a in authors if a}
    pref = [m for m in CONFIG.get("writer_judge_models", []) if isinstance(m, str) and _available(m)]
    out = [m for m in pref + model_chain(light=True)  # model_chain already lists only providers with a key
           if m not in authors and _family(m) not in fams]
    return list(dict.fromkeys(out))


def challenger_wanted(draft: dict, checks: list[dict]) -> bool:
    """config writer_challenge_policy: on_problems (default: only when the first draft has a demonstrable problem
    or came from a last-resort writer, so the extra call is likely to pay off), always, off."""
    policy = str(CONFIG.get("writer_challenge_policy", "on_problems")).lower()
    if not CONFIG.get("writer_challenge_enabled", True) or policy == "off":
        return False
    if policy == "always":
        return True
    model = str(draft.get("model") or draft.get("script_model") or "")
    weak = "lite" in model or model.startswith(("groq:", "modelscope:", "openrouter:"))
    return weak or bool(_severity(checks, "serious") or _severity(checks, "revise"))


JUDGE_PROMPT = """You are an INDEPENDENT script editor for Night Files, a short dark-documentary storytelling channel.
You wrote neither draft. Compare them for a {kind} story ({genre_rule}).
Judge each 0-10 on: title_alignment (it is about what the title promises, from the start), hook (the first line is the
most gripping relevant detail), pacing (every beat adds something new), accuracy (only the supplied facts; theory,
rumor and fact kept apart), coherence, suspense, clarity (a viewer can say what happened), payoff (a real ending or an
honest unresolved question), natural_voice (spoken, conversational, no "you watch / you follow" stage directions).
Quote the exact words that justify your biggest differences. If the drafts are equally good, choose A.
OBJECTIVE CHECKS (measured by code, trust them):
A: {checks_a}
B: {checks_b}
Return JSON: {{"winner": "A" or "B", "reason": "...", "evidence": ["quote + why", ...],
"scores": {{"A": {{"title_alignment": 0, "hook": 0, "pacing": 0, "accuracy": 0, "coherence": 0, "suspense": 0,
"clarity": 0, "payoff": 0, "natural_voice": 0}}, "B": {{...}}}}}}
TITLE: {title}
CONTEXT (source facts / writing brief):
{context}
DRAFT A:
{a}
DRAFT B:
{b}"""

GENRE_RULES = {
    "true": "documented events: only sourced facts, never invented quotes, motives or certainty",
    "lore": "a legend: told as what people believed, never as proven fact, nothing invented beyond the tradition",
    "fiction": "original fiction: consistent internal rules and an earned ending; it must never claim to be true",
}


def _brief(checks: list[dict]) -> str:
    return "; ".join(f"{c['severity']} {c['code']}: {c['detail']}" for c in checks) or "no problems found"


def compare_drafts(a: dict, b: dict, context: str, api_key: str, kind: str, source: str | None = None) -> dict:
    """Pick the stronger of two drafts. Objective checks first (a draft with fewer SERIOUS problems always wins);
    otherwise one independent judge (max 2 attempts on provider failure); no judge = the objective score decides,
    ties keep A. Returns {"winner", "reason", "judge", "evidence", "scores", "checks"}."""
    ca, cb = writing_checks(a, kind, source), writing_checks(b, kind, source)
    sa, sb = len(_severity(ca, "serious")), len(_severity(cb, "serious"))
    result = {"checks": {"A": ca, "B": cb}, "objective": {"A": check_score(ca), "B": check_score(cb)}}
    if sa != sb:
        return {**result, "winner": "A" if sa < sb else "B", "judge": "objective checks",
                "reason": f"serious problems: A {sa}, B {sb} ({_brief(_severity(ca if sa > sb else cb, 'serious'))})"}
    authors = {a.get("model") or a.get("script_model") or "", b.get("model") or b.get("script_model") or ""}
    for judge in judge_models(authors)[:2]:
        try:
            v = _call_model(judge, JUDGE_PROMPT.format(
                kind=kind, genre_rule=GENRE_RULES[kind], checks_a=_brief(ca), checks_b=_brief(cb),
                title=a.get("title") or b.get("title") or "", context=context[-9000:],
                a=json.dumps(_draft_view(a), ensure_ascii=False)[:12000],
                b=json.dumps(_draft_view(b), ensure_ascii=False)[:12000]),
                api_key, temperature=0.1, as_json=True, schema={"type": "OBJECT"})
            if not isinstance(v, dict) or v.get("winner") not in ("A", "B"):
                raise ValueError("invalid verdict")
            return {**result, "winner": v["winner"], "judge": judge, "reason": str(v.get("reason", ""))[:400],
                    "evidence": [str(x)[:200] for x in (v.get("evidence") or [])][:5], "scores": v.get("scores")}
        except Exception as exc:  # noqa: BLE001
            log(f"Independent critic {judge} unavailable: {str(exc)[:130]}")
    oa, ob = result["objective"]["A"], result["objective"]["B"]
    return {**result, "winner": "B" if ob > oa else "A", "judge": "objective checks (no independent critic)",
            "reason": f"objective score A {oa}, B {ob}"}


def _draft_view(d: dict) -> dict:
    if d.get("script") and not d.get("scenes"):
        return {"title": d.get("title", ""), "script": d["script"]}
    return {k: d[k] for k in ("title", "hook_overlay", "scenes", "fact_ledger") if k in d}


def challenge_draft(draft: dict, prompt: str, api_key: str, kind: str, source: str | None = None) -> dict:
    """At most ONE challenger draft (config writer_challenger_model, DeepSeek) and ONE independent comparison.
    The challenger gets the SAME prompt (same verified facts and rules). Any failure keeps the valid first draft."""
    checks = writing_checks(draft, kind, source)
    rec = _record(draft)
    rec.update({"kind": kind, "primary": draft.get("model") or draft.get("script_model"),
                "checks_primary": checks})
    if not challenger_wanted(draft, checks):
        rec["challenger"] = "skipped (first draft has no demonstrable problem)"
        return draft
    primary = draft.get("model") or draft.get("script_model") or ""
    configured = [CONFIG.get("writer_challenger_model", "nvidia:deepseek-ai/deepseek-v4.1-flash")]
    configured += CONFIG.get("writer_challenger_fallbacks", [])
    # One primary challenger and one alternative at most, never the original writer
    # or a model from its family. A timed-out provider cannot stall all subsequent candidates.
    choices = [m for m in configured if isinstance(m, str) and m != primary
               and _family(m) != _family(primary) and _available(m)]
    if not choices:
        rec["challenger"] = "unavailable (no independent configured challenger)"
        return draft
    candidate = None
    challenger = None
    failures = []
    for model in choices[:2]:
        try:
            rec["llm_calls"] += 1
            timeout = float(CONFIG.get("writer_challenger_timeout_seconds", 30))
            opts = {"timeout_seconds": timeout} if model.startswith("nvidia:") else {}
            if draft.get("script") and not draft.get("scenes"):
                candidate_text = _call_model(model, prompt, api_key, 1.0, as_json=False, **opts)
                trial = {"title": draft.get("title", ""), "script": candidate_text.strip()}
                if not 60 <= len(trial["script"].split()) <= 400:
                    raise ValueError("challenger script length invalid")
            else:
                trial = _call_model(model, prompt, api_key, temperature=0.6, **opts)
                _validate(trial)
                if str(trial.get("title", "")).upper() in ("SKIP", "INSPIRATION"):
                    raise ValueError("challenger declined the story")
            trial["model"], trial["writer"] = model, _writer(model)
            candidate, challenger = trial, model
            break
        except Exception as exc:
            failures.append(f"{model}: {type(exc).__name__}: {str(exc)[:110]}")
            log(f"Writer challenger {model} unavailable: {str(exc)[:130]}; trying next provider")
    if candidate is None:
        rec["challenger"] = "failed: " + "; ".join(failures)[:350]
        return draft
    verdict = compare_drafts(draft, candidate, prompt, api_key, kind, source)
    rec["llm_calls"] += 0 if verdict["judge"].startswith("objective") else 1
    chosen = candidate if verdict["winner"] == "B" else draft
    if chosen is candidate:
        for k in ("characters", "locations", "fact_ledger", "hook_candidates"):
            if draft.get(k) and not candidate.get(k):
                candidate[k] = draft[k]
        chosen["writing"] = rec
    rec.update({"challenger": challenger, "judge": verdict["judge"], "selected": verdict["winner"],
                "reason": verdict["reason"], "evidence": verdict.get("evidence", []),
                "objective": verdict["objective"]})
    chosen["writer_comparison"] = {"primary": primary, "challenger": challenger, "judge": verdict["judge"],
                                   "selected": verdict["winner"], "reason": verdict["reason"][:300]}
    log(f"Writer comparison ({kind}): draft {verdict['winner']} selected by {verdict['judge']}: "
        f"{verdict['reason'][:160]}")
    return chosen


def challenge_true_story(draft: dict, prompt: str, api_key: str) -> dict:
    """PR #23's entry point, now the true-story case of challenge_draft."""
    return challenge_draft(draft, prompt, api_key, "true")


TARGETED_REVISION = """Revise this {kind} story (same JSON format) to fix ONLY these measured problems. Keep every
fact, name, number, quote and the fact_ledger exactly; keep the number of scenes and the TRUE STORY line if present;
change as little as possible.
{genre_rule}
PROBLEMS (fix each one):
{problems}
{rules}
STORY:
{draft}"""


def targeted_revision(story: dict, api_key: str, kind: str, rules: str, notes: list[str] | None = None,
                      source: str | None = None, force: bool = False) -> dict:
    """At most config writer_max_revisions (1) revision per story, only for measured problems (or the critic's
    concrete notes). Accepted only if the objective checks don't get worse; otherwise the story stays as it was."""
    rec = _record(story)
    checks = writing_checks(story, kind, source)
    problems = [f"{c['code']}: {c['detail']}" for c in checks if c["severity"] in ("serious", "revise")]
    problems += [n for n in (notes or []) if n]
    if not problems or (not force and rec["revisions"] >= int(CONFIG.get("writer_max_revisions", 1))):
        return story  # force: the final narration check's one revision of a blocking problem (main.py)
    draft = json.dumps({k: story[k] for k in SCHEMA["properties"] if k in story}, ensure_ascii=False)
    try:
        rec["revisions"] += 1
        rec["llm_calls"] += 1
        new = _run_models(TARGETED_REVISION.format(kind=kind, genre_rule=GENRE_RULES[kind], rules=rules[:6000],
                                                   problems="\n".join(f"- {p}" for p in problems[:8]), draft=draft),
                          api_key, temperature=0.4)
    except Exception as exc:  # noqa: BLE001
        log(f"Targeted revision failed ({str(exc)[:120]}); keeping the story")
        return story
    after = writing_checks(new, kind, source)
    if check_score(after) < check_score(checks) or len(_severity(after, "serious")) > len(_severity(checks, "serious")):
        log(f"Targeted revision made it worse ({check_score(checks)} -> {check_score(after)}): kept the original")
        rec["revision_rejected"] = _brief(after)[:300]
        return story
    for k in ("characters", "locations", "fact_ledger", "hook_candidates", "writing"):
        if story.get(k) and not new.get(k):
            new[k] = story[k]
    merged = {**story, **new}
    _record(merged)["checks_after_revision"] = after
    log(f"Targeted revision: {check_score(checks)} -> {check_score(after)} (fixed: {'; '.join(problems)[:200]})")
    return merged


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


def final_script_gate(story: dict, api_key: str) -> dict:
    """The FINAL spoken narration (after every rewrite, the explainer adaptation and duration fitting), keyed to its
    SHA-256 so a changed narration is checked again. Blocks ONLY on demonstrable serious problems found by the
    objective checks (the title's subject / event never told, numbers or years not in the source, invented fiction
    presented as true). The LLM editor's approval and ratings are ADVISORY: recorded for analytics, a low rating or an
    unavailable editor never stops a finished, safe video."""
    import hashlib
    spoken = "\n".join(sc.get("narration", "") for sc in story.get("scenes") or [])
    digest = hashlib.sha256(spoken.encode("utf-8")).hexdigest()
    previous = story.get("final_script_approval") or {}
    # A saved approval for the same words only spares the advisory LLM call. The objective checks always run again
    # and a narration once blocked stays blocked: a resumed checkpoint can never carry a rejected script past here.
    cached = previous if previous.get("sha256") == digest and previous.get("checked") is True else None
    kind = writing_kind(story)
    checks = writing_checks(story, kind, story.get("_fact_source"))
    serious = _severity(checks, "serious")
    if not serious and cached and cached.get("blocked"):
        serious = _severity(cached.get("checks") or [], "serious") or [
            {"code": "previous_block", "severity": "serious", "detail": "this exact narration was blocked before"}]
    approval = {"sha256": digest, "checked": True, "kind": kind, "checks": checks, "blocked": bool(serious)}
    if cached:
        approval.update({k: cached[k] for k in ("editor", "approved", "ratings", "reasons") if k in cached})
        story["final_script_approval"] = approval
        if serious:
            raise StoryDiscarded("Final narration has a serious problem: " + _brief(serious)[:260])
        return story
    prompt = (
        "You are the FINAL script editor for Night Files. Review the final spoken text only. Do not rewrite it. "
        "Reply as JSON with keys approved (boolean), reasons (array of short, concrete strings quoting the text), "
        "title_alignment (0-10), narrative_logic (0-10), payoff (0-10), fact_integrity (0-10), natural_voice (0-10). "
        "Judge genre appropriately: " + GENRE_RULES[kind] + ".\nTITLE: " + str(story.get("title", "")) +
        "\nMODE: " + str(story.get("mode", "")) +
        "\nMEASURED BY CODE: " + _brief(checks) +
        "\nFACT LEDGER: " + json.dumps(story.get("fact_ledger") or [], ensure_ascii=False)[:10000] +
        "\nFINAL SPOKEN NARRATION:\n" + spoken)
    try:
        result = _json_call(prompt, api_key, temperature=0.1, light=False)
        ratings = {}
        for name in ("title_alignment", "narrative_logic", "payoff", "fact_integrity", "natural_voice"):
            try:
                ratings[name] = int(result.get(name, 0))
            except (ValueError, TypeError):
                ratings[name] = 0
        approval.update({"editor": "available", "approved": result.get("approved") is True, "ratings": ratings,
                         "reasons": [str(v) for v in (result.get("reasons") or [])][:8]})
    except Exception as exc:  # noqa: BLE001 (unavailable editor = no extra approval, the objective checks stand)
        approval.update({"editor": "unavailable: " + str(exc)[:160], "approved": None})
    story["final_script_approval"] = approval
    log(f"Final narration check ({kind}): measured {_brief(checks)[:300]}; editor "
        f"{approval.get('ratings') or approval['editor']} (advisory)")
    if serious:
        raise StoryDiscarded("Final narration has a serious problem: " + _brief(serious)[:260])
    return story


class StoryDiscarded(Exception):
    """The critic rejected a story after the allowed rewrites: throw it away, the next attempt tries again."""


def _json_call(prompt: str, api_key: str, temperature: float = 0.3, light: bool = True) -> dict:
    """A small JSON answer using the same shared style and provider fallbacks."""
    def call(model):
        if model.startswith(("groq:", "nvidia:", "modelscope:", "openrouter:")):
            return _call_model(model, prompt, api_key, temperature, True, {"type": "OBJECT"})
        if gemini_model_out(model):
            raise DailyLimit(f"{model}: daily quota used up")
        gen = {"temperature": temperature, "responseMimeType": "application/json"}
        _gemini_pace()
        r = requests.post(GEMINI_URL.format(model=model), timeout=90, headers={"x-goog-api-key": api_key},
                          json={"contents": [{"role": "user", "parts": [{"text": strip_marks(shared_style(prompt))}]}],
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
    return _with_models(call, "JSON answer", light=light)


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
    (clarity < 7); two rounds, then the clearest pitch anyway (never a discard)."""
    best = None
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
        best = max(((int(p.get("clarity", 0) or 0), p) for p in pitches if str(p.get("premise", "")).strip()),
                   key=lambda x: x[0], default=None)
    if best:  # advisory: the clearest pitch we have, the story is still written
        log(f"Premise check: using the clearest pitch ({best[0]}/10)")
        return best[1]
    return {}


def critic_pass(story: dict, api_key: str, kind: str, rules: str, source: str | None = None) -> dict:
    """ONE critic call (scores + concrete reasons) and at most one targeted revision (shared budget
    writer_max_revisions) for a below-bar score, measured problems or a hard legend rule. ADVISORY: a low score is
    recorded (critic_score, writing.critic) and guides the revision; it never discards a finished story.
    kind: "true" (real events) or "legend"."""
    if not CONFIG.get("critic_pass", True):
        return story
    bar = int(CONFIG.get("critic_min_score", 75))
    truth = "TRUE" if kind == "true" else "legend's"
    integrity = ("only facts from the source, nothing invented, theories labelled" if kind == "true"
                 else "the legend as actually told, nothing invented")
    extra = UPGRADE_TRUE if kind == "true" else UPGRADE_LORE
    legend = kind != "true"
    maxes = CRITIC_MAX_LEGEND if legend else CRITIC_MAX
    draft = json.dumps({k: story[k] for k in SCHEMA["properties"] if k in story}, ensure_ascii=False)
    rec = _record(story)
    try:
        rec["llm_calls"] += 1
        r = _json_call(CRITIC_PROMPT.format(
            kind=kind, rules=extra, truth=truth, integrity=integrity, draft=draft,
            m_hook=maxes["hook"], m_clarity=maxes["clarity"], m_pacing=maxes["pacing"],
            m_integrity=maxes["integrity"], story_rule=CRITIC_STORY if legend else "",
            story_key=' "story": 0,' if legend else ""), api_key, 0.2)
    except Exception as e:  # noqa: BLE001
        log(f"Critic unavailable ({str(e)[:120]}); objective checks only")
        rec["critic"] = {"available": False}
        return targeted_revision(story, api_key, "true" if kind == "true" else "lore", rules, source=source)
    total = sum(max(0, min(int(r.get(k, 0) or 0), mx)) for k, mx in maxes.items())
    reasons = [str(x) for x in (r.get("reasons") or [])][:5]
    hard = []
    if legend and int(r.get("story", 0) or 0) < 12:  # a fact list gets the one revision, whatever the total
        hard.append(f"story {r.get('story')}/20: this reads like a list of facts. Rewrite it as ONE scenario "
                    "with people, a place and rising tension (death, illness, suspicion, the grave opened, the "
                    "reveal, the remedy), weaving every fact into that scene")
    talk = SOURCE_TALK.search(_narr(story))
    if talk:
        hard.append(f"the narration says {talk.group(0)!r}: never talk about sources; just tell the legend")
    checks = writing_checks(story, "true" if kind == "true" else "lore", source)
    log(f"Critic (advisory): {total}/100 ({', '.join(f'{k} {r.get(k)}' for k in maxes)}). "
        f"What happened: {str(r.get('what_happened', ''))[:120]}. Notes: {' | '.join(hard + reasons)[:400]}. "
        f"Measured: {_brief(checks)[:200]}")
    story["critic_score"] = total
    rec["critic"] = {"available": True, "score": total, "bar": bar, "notes": (hard + reasons)[:6]}
    if total >= bar and not hard and not _severity(checks, "serious") and not _severity(checks, "revise"):
        return story
    return targeted_revision(story, api_key, "true" if kind == "true" else "lore", rules,
                             notes=hard + (reasons if total < bar else []), source=source)



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
                                   inspiration) or None
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
    kind = "fiction"
    script, model = _run_text(prompt, api_key, lo, hi)
    draft = {"title": "", "script": script, "script_model": model, "model": model}  # titled later by plan_scenes
    draft = challenge_draft(draft, prompt, api_key, kind)  # optional DeepSeek draft + independent comparison
    script, model = draft["script"], draft.get("model") or model
    rec = _record(draft)
    try:
        score, review = score_script(script, api_key)
        rec["llm_calls"] += 1
    except Exception as e:  # noqa: BLE001
        log(f"Scoring unavailable ({str(e)[:120]}); keeping this draft")
        score, review = None, {"what_happened": "(not scored)", "fixes": ""}
    measured = writing_checks({"script": script}, kind)
    slow = hook_problem(script) if cold_case else None
    if slow:  # cold case: a date/year/place opener is a measured problem
        measured.append({"code": "slow_hook", "severity": "revise", "detail": f"the first sentence {slow}"})
    log(f"Draft ({file.name}, {len(script.split())} words): {score if score is not None else '?'}/100 (advisory). "
        f"What happened: {review.get('what_happened', '')[:140]}. Measured: {_brief(measured)[:200]}")
    needs = (score is not None and score < bar) or _severity(measured, "revise") or _severity(measured, "serious")
    if needs and rec["revisions"] < int(CONFIG.get("writer_max_revisions", 1)):
        rec["revisions"] += 1
        fixes = "; ".join([str(review.get("fixes", ""))] + [f"{c['code']}: {c['detail']}" for c in measured
                                                            if c["severity"] != "advisory"])
        ask = (prompt + f"\n\n## YOUR LAST DRAFT SCORED {score}/100. REWRITE IT ONCE.\n"
               f"Fix these: {fixes}\n"
               "Keep what worked, fix what didn't, and make sure the viewer can say what happened in one sentence.\n"
               "LAST DRAFT:\n\"\"\"\n" + script + "\n\"\"\"\n")
        try:
            new_script, new_model = _run_text(ask, api_key, lo, hi)
            rec["llm_calls"] += 1
            after = writing_checks({"script": new_script}, kind)
            try:
                new_score, new_review = score_script(new_script, api_key)
                rec["llm_calls"] += 1
            except Exception:  # noqa: BLE001
                new_score, new_review = None, review
            better = check_score(after) >= check_score(measured) and (
                new_score is None or score is None or new_score >= score)
            log(f"Rewrite: {new_score}/100, measured {check_score(after)} vs {check_score(measured)}: "
                + ("kept" if better else "the first draft stays"))
            if better:
                script, model, score, review = new_script, new_model, new_score, new_review
        except Exception as e:  # noqa: BLE001
            log(f"Rewrite failed ({str(e)[:120]}); keeping the first draft")
    if score is not None and score < bar:  # ADVISORY: the story is still made (owner, Oct 24)
        log(f"Story scored {score}/100 (bar {bar}): made anyway, the score is kept for analytics")
    else:
        log(f"Story passed with {score}/100")

    story = plan_scenes(script, api_key, sfx_list)
    story["writing"] = rec
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
    if story.get("title", "").strip().upper() not in ("SKIP", "INSPIRATION"):
        story = challenge_draft(story, prompt, api_key, "true", facts)
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
    story = edit_story(story, api_key, sfx_list, rules, "true", facts)
    story = fix_hook(story, api_key, sfx_list, rules)
    story = critic_pass(story, api_key, "true", rules, facts)  # before the fact check, which then checks any rewrite
    story = fact_check(story, facts, api_key)
    story["_fact_source"] = facts[:20000]  # the final narration check compares numbers / years with it
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
    import spoken_numbers as nums
    ledger_years = {v for v in nums.values(" ".join(ledger)) if 1000 <= v <= 2100}
    if ledger_years:  # a year the ledger doesn't have is wrong even if the source mentions it somewhere (Oct 21:
        for v in sorted(nums.values(text)):  # Le Prince "nineteen ninety" for 1890 got through)
            if 1000 <= v <= 2100 and v not in ledger_years:
                items.append(f"the year {int(v)} (the fact_ledger's years are {', '.join(str(int(y)) for y in sorted(ledger_years))})")
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


def _final_problem(story: dict, history: list[dict]) -> str:
    """Last line of defence on the FINISHED story (the pickers already check every topic before a word is
    written): a blocked topic, a recent repeat that only shows in the written title, or a reused opening line."""
    hit = blocked_topic(story.get("title"), story.get("case"), story.get("premise"), story.get("source"),
                        " ".join(sc.get("narration", "") for sc in story.get("scenes") or []))
    if hit:
        return f"blocked topic ({hit})"
    import repeat_guard
    from common import opening_line
    return (repeat_guard.repeat_of(story.get("title"), story.get("case"), story.get("subgenre"),
                                   story.get("source") if not str(story.get("source") or "").startswith("http") else "",
                                   history=history, allow=(story.get("cluster"),))
            or repeat_guard.opening_reused(opening_line(story), history))


def write_story(history: list[dict]) -> dict:
    """Write one story. Repeats are caught when the topic is PICKED (repeat_guard in next_case / pick_case /
    pick_subgenre / next_inbox), before any script is written; the check here runs on the finished story and allows
    ONE retry with the rejected topic excluded (babddea's 5 full-story attempts cost up to 5 stories of quota).
    The excluded topic lives only in this local list for the pickers; it never reaches history.json."""
    skipped: list[dict] = []
    rejected: list[str] = []
    for attempt in (1, 2):
        pick_history = history + [{"case": t, "title": t, "rejected_this_run": True} for t in rejected]
        story = _write_story(pick_history, skipped)
        why = _final_problem(story, history)
        if not why:
            break
        log(f"Story '{story.get('title')}' rejected after writing (attempt {attempt}/2): {why}")
        rejected.append(story.get("case") or story.get("title") or "?")
    else:
        raise RuntimeError(f"Story '{story.get('title')}' repeats a recent video or is blocked: {why}: discarded "
                           f"(rejected this run: {', '.join(rejected)})")
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
    import os
    try:
        if os.environ.get("STORY_MODE") and not os.environ.get("INBOX_FILE"):
            raise LookupError("STORY_MODE forced (test): inbox skipped")
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


def _owner_fields(story: dict, item: dict) -> None:
    """Inbox headers that go with the finished story: TITLE (the owner's title, also the YouTube title) and CLUSTER
    (an owner-scheduled topic cluster: repeat_guard lets its own videos through, see repeat_guard.repeat_of)."""
    if item.get("title"):
        story["title"] = item["title"]
        story["fixed_title"] = item["title"]
    if item.get("cluster"):
        story["cluster"] = item["cluster"]
    if item.get("ban"):
        story["ban"] = list(item["ban"])  # checked again by any later rewrite (explainer.adapt)


def ban_hits(bans, text: str) -> list[str]:
    """Banned phrases in the text, also with up to 2 extra words in between ("because of his SUDDEN disappearance"
    slipped past an exact match in the Le Prince test of Oct 21)."""
    low = re.sub(r"[^a-z0-9' ]+", " ", (text or "").lower())
    hits = []
    for b in bans or []:
        words = re.sub(r"[^a-z0-9' ]+", " ", str(b).lower()).split()
        if words and re.search(r"\b" + r"(?:\s+\S+){0,2}?\s+".join(map(re.escape, words)) + r"\b", low):
            hits.append(b)
    return hits


def topic_story(history: list[dict], item: dict, api_key: str, sfx_list: str) -> dict:
    """Inbox topic files: REMAKE (new lore video about a topic we already made: new angle / hook / structure /
    images), LORE (a legend) or TRUE (a real story). The topic comes from the file, so the "topic already used"
    pick (mystery.pick_case) is bypassed for that topic only. Sources: the listed Wikipedia pages + research."""
    import mystery
    topic, kind = item["topic"], item["kind"]
    notes = "\n".join(x for x in [item.get("text", "")] if x)
    holder: dict = {}
    old = {}
    if kind == "remake":
        old = next((h for h in reversed(history) if not h.get("skipped") and (
            str(h.get("case") or "").lower() == topic.lower() or topic.lower() in str(h.get("title", "")).lower())), {})
    # TRUE files, and REMAKEs of a TRUE video (Oct 19: Le Prince was a mystery, not a legend): fact-locked true story
    if kind == "true" or (kind == "remake" and (old.get("true_story") or old.get("mode") in TRUE_MODES)):
        avoid = [x for x in [old.get("title"), old.get("premise"), old.get("twist")] if x] + list(item.get("avoid", []))
        if kind == "remake":
            log(f"Remake of TRUE story {old.get('title') or topic} (posted {old.get('date', '?')}): new angle "
                f"'{item.get('angle', '')[:110]}'")
        facts = _wiki_sources(item, topic, holder)
        brief = "\n".join(x for x in [
            f"ANGLE: {item['angle']}" if item.get("angle") else "",
            f"HOOK: scene 1 opens with this sentence if the SOURCE supports it: {item['hook']}" if item.get("hook") else "",
            ("THE OLD VIDEO (never reuse its opening, hook overlay or structure):\n" + "\n".join(f"- {x}" for x in avoid))
            if avoid else "",
            ("NEVER use these words or ideas: " + "; ".join(item["ban"])) if item.get("ban") else "",
            notes] if x)
        extra = ""
        for attempt in range(3):
            story = _true_story(facts, topic, api_key, sfx_list, notes=brief + extra, holder=holder)
            opening = re.split(r"(?<=[.!?])\s+", story["scenes"][0]["narration"].strip())[0]
            reused = [x for x in avoid if _too_close(opening, x) or _too_close(story.get("hook_overlay", ""), x)]
            said = " ".join(sc.get("narration", "") for sc in story.get("scenes") or []).lower()
            banned = ban_hits(item.get("ban"), said)
            if not reused and not banned:
                break
            why = f"used {banned[0]!r}" if banned else f"reused the old video ({reused[0][:80]!r})"
            log(f"Draft {attempt + 1} {why}; writing it again")
            extra = (f"\n\nYOUR LAST DRAFT {why.upper()}. " + ("Leave it out completely." if banned else
                     "Use a different first sentence and hook overlay built on the ANGLE."))
        else:
            raise RuntimeError(f"{topic}: every draft reused the old video or used a banned word")
        story.update({"mode": "inbox-true", "source": item["key"], "subgenre": "true story", "case": topic,
                      "true_story": True, "no_child_images": item.get("no_children", False)})
        if kind == "remake":
            story.update({"remake_of": old.get("title") or topic, "remake_angle": item.get("angle", "")})
        _true_line_after_hook(story, item.get("hook", ""))
        _owner_fields(story, item)
        return story

    avoid, num = list(item.get("avoid", [])), ""
    if kind == "remake":
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
        story = challenge_draft(story, prompt + UPGRADE_LORE + block + extra, api_key, "lore")
        story = edit_story(story, api_key, sfx_list, rules, "lore")
        story = fix_hook(story, api_key, sfx_list, rules)
        story = critic_pass(story, api_key, "legend", rules)
        opening = re.split(r"(?<=[.!?])\s+", story["scenes"][0]["narration"].strip())[0]
        reused = [x for x in avoid if _too_close(opening, x) or _too_close(story.get("hook_overlay", ""), x)
                  or _too_close(story.get("title", ""), x, 0.85)]  # a title may share the legend's name
        harm = child_harm(story) if item.get("no_children") else ""
        said = " ".join(sc.get("narration", "") for sc in story.get("scenes") or []).lower()
        banned = ban_hits(item.get("ban"), said)
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
    _owner_fields(story, item)
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
                kind = "true" if mode == "mystery" else "lore"
                src = facts if mode == "mystery" else None
                story = challenge_draft(story, prompt, api_key, kind, src)
                rules = ((f'scene 1 = the hook sentence, then the exact words "{TRUE_OPENER}"; ' if mode == "mystery" else "")
                         + "ONLY facts from this source, never invent details; theories/legends clearly labelled; "
                         "no accusing real people; respectful; no gore; third person; plain English.\nSOURCE:\n" + mark_source(facts[:6000]))
                story = edit_story(story, api_key, sfx_list, rules, kind, src)
                story = fix_hook(story, api_key, sfx_list, rules)
                story = critic_pass(story, api_key, "true" if mode == "mystery" else "legend", rules, src)
                if mode == "mystery":  # real events: fact check (lore = legends, not checked)
                    story = fact_check(story, facts, api_key)
                    story["_fact_source"] = facts[:20000]
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
