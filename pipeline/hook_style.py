"""Hook-style experiment (owner idea 2026-11-24): rotate how scene 1 opens and tag every video with it.

Styles: "control" (today's opener: the strangest detail), "true_story" (opens with "This is a true story."),
"did_you_know", "date", "description" (paint the key image) and "ending_first" (how it ends, then rewind).
The rotation picks the least-used eligible style in history, so the styles get equal samples. Only the opening of
scene 1 and the hook overlay are rewritten, from facts already in the script; any failure keeps the script as it
was and tags it "control". The style is saved in history.json ("hook_style") for the analytics read-out.
"""
from __future__ import annotations

import re

from common import CONFIG, log

STYLES = {
    "true_story": ('Open with the exact words "This is a true story." and then, in the same breath, the strangest '
                   "true detail of the case."),
    "did_you_know": ('Open with a "Did you know..." question built on the strangest verified fact in the script '
                     "(one sentence, no answer yet)."),
    "date": ("Open with the exact date (or year) the key event happened, taken from the script, followed at once by "
             'what went wrong, e.g. "On the night of <date>, <the strange event>."'),
    "description": ("Open by painting the single most unsettling image of the story in plain, concrete words "
                    "(what a witness would have SEEN), present tense, before any explanation."),
    "ending_first": ("Open with how it ENDS (the final outcome, without the explanation), then turn back with a "
                     'short bridge such as "But it started with..." so the rest of the script tells how it got there.'),
}
TRUE_ONLY = {"true_story", "date"}  # fiction / legends are never called true and have no real date

PROMPT = """You rewrite ONLY the opening (the hook) of a short horror / true-mystery video.
HOOK STYLE: {rule}
Rules:
- Use ONLY facts, names, numbers and dates that already appear in the SCRIPT below. Never invent a detail.
- Rewrite only scene 1. Keep its length within a few words of the original ({words} words) and keep everything it
  says after the hook (the rest of scene 1 may be lightly reworded so it still flows).
- Scenes 2+ are NOT returned and must still follow naturally. Plain spoken English, no lists.
- "hook_overlay": the on-screen hook text for this opening, max 8 words.
{true_note}
SCRIPT (scene by scene):
{script}

Return JSON: {{"scene1": "the new narration of scene 1", "hook_overlay": "..."}}"""


def settings() -> dict:
    return {"enabled": True, "styles": ["control", *STYLES], **(CONFIG.get("hook_styles") or {})}


def eligible(story: dict) -> list[str]:
    from story import TRUE_MODES
    real = story.get("mode") in TRUE_MODES or bool(story.get("true_story"))
    text = " ".join(sc.get("narration", "") for sc in story.get("scenes") or [])
    out = []
    for s in settings()["styles"]:
        if s != "control" and s not in STYLES:
            continue
        if s in TRUE_ONLY and not real:
            continue
        if s == "date" and not re.search(r"\b(1[5-9]|20)\d\d\b|nineteen|eighteen|twenty|"
                                         r"january|february|march|april|may|june|july|august|september|"
                                         r"october|november|december", text, re.IGNORECASE):
            continue  # no date in the script to open with
        out.append(s)
    return out or ["control"]


def pick(story: dict, history: list[dict]) -> str:
    """The least-used eligible style so far (ties: the order in settings), for balanced samples."""
    used = [h.get("hook_style") for h in history if h.get("hook_style")]
    return min(eligible(story), key=lambda s: (used.count(s), settings()["styles"].index(s)))


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+", text))


def apply(story: dict, history: list[dict]) -> dict:
    """Rewrite scene 1's opening in the next hook style. Never raises: on any problem the script stays as written."""
    if story.get("hook_style"):
        return story  # already styled (a banked or resumed story)
    if story.get("mode") == "inbox-script" or not settings()["enabled"] or not story.get("scenes"):
        story["hook_style"] = "owner" if story.get("mode") == "inbox-script" else "control"
        return story
    style = pick(story, history)
    if style == "control":
        story["hook_style"] = "control"
        log("Hook style: control (strangest-detail opener, unchanged)")
        return story
    first = story["scenes"][0].get("narration", "")
    script = "\n".join(f"{i + 1}. {sc.get('narration', '')}" for i, sc in enumerate(story["scenes"]))
    from story import TRUE_MODES, _json_call
    real = story.get("mode") in TRUE_MODES or bool(story.get("true_story"))
    prompt = PROMPT.format(rule=STYLES[style], words=len(first.split()), script=script,
                           true_note="- This is a TRUE story: every word must match the script's facts exactly."
                           if real else "- This is fiction: never call it true.")
    try:
        from common import env
        out = _json_call(prompt, env("GEMINI_API_KEY", required=False) or "", temperature=0.5, light=False)
        new = re.sub(r"\s+", " ", str(out.get("scene1") or "")).strip()
        problem = None
        if not new:
            problem = "empty answer"
        elif not 0.6 <= len(new.split()) / max(1, len(first.split())) <= 1.5:
            problem = f"length {len(new.split())} words vs {len(first.split())}"
        elif _numbers(new) - _numbers(script):
            problem = f"new numbers {sorted(_numbers(new) - _numbers(script))}"
        elif style == "true_story" and not new.lower().startswith("this is a true story"):
            problem = "does not open with the true-story line"
        elif style == "did_you_know" and not new.lower().startswith("did you know"):
            problem = "does not open with 'Did you know'"
        if problem:
            raise ValueError(problem)
    except Exception as e:  # noqa: BLE001
        log(f"Hook style {style}: rewrite failed ({str(e)[:150]}); keeping the original opener (control)")
        story["hook_style"] = "control"
        return story
    story["scenes"][0]["narration"] = new
    if out.get("hook_overlay"):
        story["hook_overlay"] = str(out["hook_overlay"]).strip()
    story["hook_style"] = style
    story["hook_line"] = first_sentence(new)
    log(f"Hook style: {style}: {new[:140]}")
    return story


def first_sentence(text: str) -> str:
    m = re.match(r"(.+?[.!?])(\s|$)", (text or "").strip())
    return (m.group(1) if m else (text or "")).strip()


def keep(story: dict) -> dict:
    """After a resize, put the styled hook sentence back if the resize changed it."""
    hook = story.get("hook_line")
    if not hook or not story.get("scenes"):
        return story
    text = story["scenes"][0].get("narration", "")
    if text.startswith(hook):
        return story
    rest = text[len(first_sentence(text)):].strip()
    story["scenes"][0]["narration"] = f"{hook} {rest}".strip()
    log(f"Hook style {story.get('hook_style')}: hook sentence restored after the resize")
    return story
