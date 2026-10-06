"""Shared helpers: paths, config, logging, retries."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config.json").read_text())
HISTORY_FILE = ROOT / "data" / "history.json"


def blocked_topic(*texts) -> str:
    """The config "blocked_topics" entry (case-insensitive) found in any of the texts, else "". Temporary hard stop
    for a topic that keeps repeating (Oct 5: Lizzie Borden posted 4 times while history.json was frozen)."""
    hay = " ".join(str(t or "") for t in texts).lower()
    for t in CONFIG.get("blocked_topics", []):
        if t and t.lower() in hay:
            return t
    return ""


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def env(name: str, required: bool = True, default: str = "") -> str:
    val = os.environ.get(name, default).strip()
    if required and not val:
        sys.exit(f"Missing required secret/env var: {name}")
    return val


def retry(fn, attempts: int = 3, wait: float = 5.0, what: str = "request"):
    last = None
    for i in range(1, attempts + 1):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            log(f"{what} failed (attempt {i}/{attempts}): {e}")
            if i < attempts:
                time.sleep(wait * i)
    raise RuntimeError(f"{what} failed after {attempts} attempts: {last}")


def run(cmd: list[str]) -> str:
    """Run a command, raise with stderr on failure."""
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd[:6])}...\n{p.stderr[-3000:]}")
    return p.stdout


def media_duration(path: Path) -> float:
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=nw=1:nk=1", str(path)])
    return float(out.strip())


def load_history() -> list[dict]:
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text() or "[]")
    return []


def save_history(items: list[dict]) -> None:
    # a story writer's retry markers (rejected topics, babddea's "[rejected N]") are never real videos
    items = [h for h in items if not h.get("rejected_this_run") and not str(h.get("title", "")).startswith("[rejected")]
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(items, indent=2, ensure_ascii=False))


# Gemini's free DAILY quota is per model. Only a 429 whose body names a per-DAY limit ("PerDay" quota id,
# "per day") marks THAT model out for the rest of the run; a per-minute 429 or a 503 "high demand" never does.
# When every Gemini model in llm_models is out, every module goes to Groq right away (writing, critic, image QA).
GEMINI = {"out": False, "models_out": set()}


def gemini_out() -> bool:
    return GEMINI["out"]


def gemini_model_out(model: str) -> bool:
    return GEMINI["out"] or model in GEMINI["models_out"]


def is_daily_quota(body: str) -> bool:
    """A 429 body that is really the per-DAY quota (not per-minute, not an overload)."""
    text = body or ""
    low = text.lower()
    per_day = "perday" in low.replace(" ", "") or "per day" in low or "per_day" in low or "daily" in low
    return per_day and "perminute" not in low.replace(" ", "")


def note_gemini_429(body: str, model: str | None = None) -> bool:
    """Call with the body of a Gemini 429. A per-day quota marks `model` out (every Gemini model if no model is
    given); returns True when Gemini as a whole is out. Per-minute limits only log."""
    if not is_daily_quota(body):
        log(f"Gemini{' ' + model if model else ''}: per-minute rate limit (429), not the daily quota")
        return GEMINI["out"]
    if not CONFIG.get("gemini_quota_switch", True):
        return GEMINI["out"]
    gems = [m for m in CONFIG.get("llm_models", []) if not m.startswith("groq:")]
    if model and model not in GEMINI["models_out"]:
        GEMINI["models_out"].add(model)
        log(f"Gemini {model}: daily quota used up (no more calls to it this run)")
    if (not model or all(m in GEMINI["models_out"] for m in gems)) and not GEMINI["out"]:
        GEMINI["out"] = True
        log("Gemini daily quota used up on every model: no more Gemini calls this run (Groq instead)")
    return GEMINI["out"]


# Source text inside prompts is wrapped in invisible markers, so a Groq call (small tokens-per-minute budget) can
# shorten just the source and keep every instruction; Gemini gets the full text with the markers removed.
SRC_OPEN, SRC_CLOSE = "\u2063\u2063", "\u2064\u2064"


def mark_source(text: str) -> str:
    return f"{SRC_OPEN}{text}{SRC_CLOSE}"


def strip_marks(prompt: str) -> str:
    return prompt.replace(SRC_OPEN, "").replace(SRC_CLOSE, "")


def trim_sources(prompt: str, limit: int) -> str:
    """Every marked source block cut to `limit` chars (at a sentence end if possible); markers removed."""
    import re as _re

    def cut(m):
        body = m.group(1)
        if len(body) <= limit:
            return body
        part = body[:limit]
        end = max(part.rfind(". "), part.rfind(".\n"))
        return (part[:end + 1] if end > limit * 0.6 else part) + "\n[source shortened]"
    return _re.sub(_re.escape(SRC_OPEN) + r"(.*?)" + _re.escape(SRC_CLOSE), cut, prompt, flags=_re.DOTALL)


def opening_line(story: dict) -> str:
    """The first spoken sentence (scene 1), for the repeat guard's 'no reused opening line' check."""
    import re
    scenes = story.get("scenes") or []
    text = str((scenes[0] or {}).get("narration", "") if scenes else "").strip()
    m = re.match(r"(.+?[.!?])(\s|$)", text)
    return (m.group(1) if m else text)[:200]
