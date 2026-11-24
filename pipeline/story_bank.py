"""Write-ahead story bank (owner-approved 2026-11-24).

Stories used to be written only at render time (two daily runs). When Gemini was overloaded at that moment, the lite
model wrote the story: 50 of the last 60 videos (Nov 2026). story_bank.yml now calls fill() every few hours with
NF_STRONG_WRITERS_ONLY=1, so only the strong writers (strong Gemini, NVIDIA, OpenRouter, ModelScope, Groq) can bank
a story, and the daily run takes the best banked story before writing one on the spot.

data/story_bank/<story_id>.json is written ONLY by story_bank.yml. main.py only reads it; a story it took is
recognised later by its story id (history, parked in data/failed_stories, buffered) and pruned by the next fill().
"""
from __future__ import annotations

import copy
import json
import os
from datetime import datetime, timedelta, timezone

from common import CONFIG, ROOT, log

BANK = ROOT / "data" / "story_bank"


def settings() -> dict:
    return {"enabled": True, "target": 3, "max_age_days": 21, **(CONFIG.get("story_bank") or {})}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load_all() -> list[tuple]:
    out = []
    for f in sorted(BANK.glob("*.json")) if BANK.exists() else []:
        try:
            out.append((f, json.loads(f.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            log(f"Story bank: {f.name} is unreadable, ignored")
    return out


def _lite(story: dict) -> bool:
    return "lite" in str(story.get("model") or story.get("writer") or "")


def _why_unusable(story: dict, history: list[dict], buffered: set | None = None) -> str | None:
    """Why a banked story can't be made (already used, parked, too old, lite-written), or None."""
    import checkpoint
    sid = story.get("story_id") or checkpoint.story_id(story)
    used = {h.get("story_id") for h in history} | {(h.get("title"), h.get("mode")) for h in history}
    if sid in used or (story.get("title"), story.get("mode")) in used:
        return "already made"
    if sid in (buffered or set()):
        return "already buffered"
    if (checkpoint.FAILED / sid).exists():
        return "parked in data/failed_stories"
    if _lite(story):
        return "written by a lite model"
    try:
        age = _now() - datetime.fromisoformat(story.get("banked_at"))
        if age > timedelta(days=float(settings()["max_age_days"])):
            return f"older than {settings()['max_age_days']} days"
    except (TypeError, ValueError):
        pass
    return None


def _rank(item: tuple) -> tuple:
    story = item[1]
    score = story.get("critic_score") or story.get("score") or 0
    try:
        score = float(score)
    except (TypeError, ValueError):
        score = 0.0
    return (-score, story.get("banked_at") or "")  # best critic score first, then the oldest


def take(history: list[dict], buffered: set | None = None) -> dict | None:
    """The best usable banked story (a copy; the file stays until fill() prunes it), or None."""
    if not settings()["enabled"]:
        return None
    from story import _final_problem
    for f, story in sorted(_load_all(), key=_rank):
        why = _why_unusable(story, history, buffered) or _final_problem(story, history)
        if why:
            log(f"Story bank: skipping '{story.get('title')}' ({why})")
            continue
        log(f"Story bank: using '{story.get('title')}' ({story.get('story_id')}, written by "
            f"{story.get('writer') or story.get('model')} at {story.get('banked_at')})")
        story = copy.deepcopy(story)
        story["from_story_bank"] = True
        return story
    return None


def prune(history: list[dict]) -> int:
    removed = 0
    for f, story in _load_all():
        why = _why_unusable(story, history)
        if why:
            log(f"Story bank: removing '{story.get('title')}' ({why})")
            f.unlink()
            removed += 1
    return removed


def fill() -> int:
    """Prune used stories, then write ONE story with strong writers only if the bank is below target.
    Returns 0 always (a writer outage just means nothing is banked this time)."""
    os.environ["NF_STRONG_WRITERS_ONLY"] = "1"
    from common import apply_length, load_history
    import checkpoint
    s = settings()
    history = load_history()
    prune(history)
    stock = [story for _, story in _load_all()]
    if not s["enabled"]:
        log("Story bank: disabled in config (story_bank.enabled)")
        return 0
    if len(stock) >= int(s["target"]):
        log(f"Story bank: {len(stock)} stories in stock (target {s['target']}): nothing to write")
        return 0
    from story import write_story
    try:
        story = write_story(history + stock)  # banked stories count as used topics: no two of the same
    except Exception as e:  # noqa: BLE001
        log(f"Story bank: nothing banked this time ({type(e).__name__}: {str(e)[:300]})")
        return 0
    if _lite(story):
        log(f"Story bank: '{story.get('title')}' came from {story.get('model')}: not banked")
        return 0
    length = apply_length(story)
    lo, hi = CONFIG.get("story_words", [80, 92])
    words = sum(len(sc.get("narration", "").split()) for sc in story.get("scenes", []))
    if story.get("mode") != "inbox-script" and not lo * 0.9 <= words <= hi * 1.1:
        # Fit the script to the video length now, while a strong writer answers (the render-time resize is what
        # failed on Nov 24). A failed resize keeps the story: the daily run's fit_duration still tries.
        from common import env
        from story import resize_story
        try:
            story = resize_story(story, env("GEMINI_API_KEY", required=False) or "", round((lo + hi) / 2))
            log(f"Story bank: resized {words} -> "
                f"{sum(len(sc.get('narration', '').split()) for sc in story.get('scenes', []))} words ({length})")
        except Exception as e:  # noqa: BLE001
            log(f"Story bank: resize failed ({type(e).__name__}: {str(e)[:150]}); the daily run will fit it")
    import explainer
    if explainer.style_for(story) == "explainer" and not story.get("explainer_adapted"):
        story = explainer.adapt(story)  # the second LLM pass also happens now, while a strong writer answers
    story["story_id"] = story.get("story_id") or checkpoint.story_id(story)
    story["banked_at"] = _now().isoformat(timespec="seconds")
    story["banked_length"] = length
    BANK.mkdir(parents=True, exist_ok=True)
    (BANK / f"{story['story_id']}.json").write_text(json.dumps(story, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"Story bank: banked '{story.get('title')}' ({story['story_id']}, {story.get('mode')}, written by "
        f"{story.get('writer') or story.get('model')}); {len(stock) + 1} in stock")
    return 0


if __name__ == "__main__":
    raise SystemExit(fill())
