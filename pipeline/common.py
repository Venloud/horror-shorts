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


# Shared state lives on main, whichever branch a workflow was started from (owner, Oct 31: the fixing-it branch runs
# the same workflow): history, counters, missed slot, YouTube / Buffer ledgers, parked stories and the inbox are
# read from origin/main at the start and pushed back to main by push_state.sh (merged entry by entry against the
# main commit they were read from: .state_base). The buffer / youtube-pending releases are repo-wide already.
STATE_BRANCH = "main"
SHARED_STATE = ("data/history.json", "data/counter.json", "data/missed_slot.json", "data/youtube_pending.json",
                "data/buffer_backfill_queue.json", "data/backfill.json", "data/tiktok_posted.txt",
                "data/failed_stories", "data/series", "inbox")


def current_branch() -> str:
    ref = os.environ.get("GITHUB_REF_NAME", "").strip()
    if ref:
        return ref
    p = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    return p.stdout.strip()


def sync_shared_state(force: bool = False) -> str | None:
    """In Actions on any branch but main: replace this checkout's shared-state files with origin/main's and record
    that commit in .state_base (push_state.sh merges against it). Returns the main commit, None when not needed
    (on main, or outside Actions unless force). Never raises: a failed sync stops the build instead of risking a
    duplicate story from stale history."""
    if not force and (not os.environ.get("GITHUB_ACTIONS") or current_branch() in ("", STATE_BRANCH)):
        return None
    git = lambda *a: subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True)  # noqa: E731
    for _ in range(3):
        if git("fetch", "-q", "origin", STATE_BRANCH).returncode == 0:
            break
        time.sleep(4)
    sha = git("rev-parse", f"origin/{STATE_BRANCH}").stdout.strip()
    if not sha:
        raise RuntimeError(f"shared state: could not read origin/{STATE_BRANCH} (refusing to build on stale history)")
    import shutil
    for rel in SHARED_STATE:
        target = ROOT / rel
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
        if git("cat-file", "-e", f"{sha}:{rel}").returncode == 0:
            r = git("restore", f"--source={sha}", "--worktree", "--", rel)
            if r.returncode:
                raise RuntimeError(f"shared state: could not restore {rel} from {STATE_BRANCH}: {r.stderr[:200]}")
    (ROOT / ".state_base").write_text(sha + "\n")
    log(f"Shared state: branch {current_branch() or '?'} reads history / counters / ledgers / inbox from "
        f"{STATE_BRANCH} {sha[:8]} and saves back to {STATE_BRANCH}")
    return sha


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


_AUTH_MARKERS = ("permission_denied", "api_key_invalid", "api key not valid", "consumer_suspended", "suspended",
                 "has been disabled", "service_disabled", "billing", "api key expired", "unauthenticated")


def is_gemini_auth_error(status: int, body: str) -> bool:
    """401 / 403, or a 400 that says the key is invalid / the project is suspended: Gemini is unusable this run
    (unlike a 429 or 503, waiting never helps)."""
    low = (body or "").lower()
    return status in (401, 403) or (status == 400 and any(m in low for m in _AUTH_MARKERS))


def note_gemini_auth(status: int, body: str, where: str) -> None:
    """First auth / permission failure in a run: every Gemini call is skipped from now on (writer -> Groq, image QA ->
    Groq vision, research -> Wikipedia only), and ONE ntfy alert says so."""
    if GEMINI.get("auth"):
        return
    GEMINI["out"] = True
    GEMINI["auth"] = f"HTTP {status}: {(body or '')[:200]}"
    log(f"Gemini AUTH/PERMISSION error in {where} ({GEMINI['auth']}): no more Gemini calls this run, Groq instead")
    try:
        from notify import notify_text
        notify_text("Night Files: Gemini key/project refused (HTTP %d)" % status,
                    f"Gemini answered {GEMINI['auth']} (in {where}). This run skips Gemini (Groq writes, Groq vision "
                    "checks images, research is Wikipedia only). Check the Google AI Studio / Cloud project behind "
                    "GEMINI_API_KEY.", warn=True)
    except Exception as e:  # noqa: BLE001
        log(f"Gemini auth alert not sent ({e})")


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
