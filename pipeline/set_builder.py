"""Setting builder (owner request 2026-11-24, scene upgrade step 1).

Before any picture is made, one LLM pass designs the story's SETS: as many distinct places as the story really
moves through (no fixed count), each built in layers like a multiplane camera: background, midground, foreground
framing, light source, one signature detail and a leading line. Every shot is then assigned to one set and given
its own eye-catching focal detail. images.build_prompt() uses this so a place looks the same every time it is
shown, and each frame has a clear subject, depth (dark textured foreground, softer paler background) and a line
that leads the eye to the subject.

Never invents story facts: sets only describe places the narration already names or implies. Any failure leaves
the story as written (story["set_builder"] = "off"); the tag goes to history.json for the read-out.
"""
from __future__ import annotations

import json
import re

from common import CONFIG, log

SHOT_KEYS = {"a": "image_prompt", "b": "image_prompt_2", "c": "image_prompt_3", "d": "image_prompt_4"}
LOC_KEYS = {"a": "image_location", "b": "image_location_2", "c": "image_location_3", "d": "image_location_4"}
FOCAL_KEYS = {"a": "image_focal", "b": "image_focal_2", "c": "image_focal_3", "d": "image_focal_4"}

PROMPT = """You are the production designer of a short illustrated horror / true-mystery video.
Design the SETS (places) for the shots below, then assign every shot to one set.

SETS
- One set per DISTINCT place the story really moves through: as many as the story needs (often 2-6), never padding.
  The same place seen again is the SAME set. Never invent a place, event or object the narration doesn't name or
  imply. {era}
- Build each set in layers, concrete and visual (what a camera sees), max 14 words per field:
  "background" (far: sky, horizon, far walls; pale, misty, soft), "midground" (where the subject stands),
  "foreground" (near framing element: branches, a door frame, reeds, a railing; dark and textured),
  "light" (one motivated light source and its colour), "detail" (one eye-catching signature detail that makes this
  place memorable), "leading_line" (a line in the set that pulls the eye to the subject: a path, a river bank,
  a corridor, a rope, rails).
SHOTS
- For every shot: "set" = the set name, or "none" for a close-up of an object / document with no place.
  "focal" = the ONE thing the eye must land on first (max 10 words, from the shot itself).

STORY: {title}
NARRATION + SHOTS:
{shots}

Return JSON: {{"sets": [{{"name": "...", "background": "...", "midground": "...", "foreground": "...", "light": "...",
"detail": "...", "leading_line": "..."}}], "shots": [{{"id": "1a", "set": "...", "focal": "..."}}]}}"""


def enabled() -> bool:
    return bool((CONFIG.get("set_builder") or {"enabled": True}).get("enabled", True))


def _shot_list(story: dict) -> tuple[str, list[str]]:
    lines, ids = [], []
    for i, sc in enumerate(story.get("scenes") or []):
        lines.append(f"Scene {i + 1} narration: {sc.get('narration', '')}")
        for letter, key in SHOT_KEYS.items():
            if str(sc.get(key) or "").strip():
                sid = f"{i + 1}{letter}"
                ids.append(sid)
                lines.append(f"  shot {sid}: {sc[key]}")
    return "\n".join(lines), ids


def _clean(v, n: int = 14) -> str:
    return " ".join(re.sub(r"\s+", " ", str(v or "")).strip().rstrip(".").split()[:n])


def set_look(s: dict) -> str:
    """The locked look of a set as image-prompt text: far to near, then light and the signature detail."""
    parts = [s.get("background"), s.get("midground"), s.get("detail"),
             f"{s['foreground']} in the dark foreground" if s.get("foreground") else "",
             f"{s['leading_line']} leading the eye" if s.get("leading_line") else "", s.get("light")]
    return ", ".join(p for p in parts if p)


def build(story: dict) -> dict:
    """Design the sets and assign every shot. Never raises; on failure the story is unchanged ('off')."""
    if story.get("set_builder"):
        return story  # already built (banked / resumed story)
    if not enabled() or not story.get("scenes"):
        story["set_builder"] = "off"
        return story
    shots, ids = _shot_list(story)
    if not ids:
        story["set_builder"] = "off"
        return story
    era = f"Era / setting: {story['setting']}." if story.get("setting") else ""
    try:
        from common import env
        from story import _json_call
        out = _json_call(PROMPT.format(era=era, title=story.get("title", ""), shots=shots),
                         env("GEMINI_API_KEY", required=False) or "", temperature=0.4, light=False)
        sets = [{k: _clean(s.get(k), 40 if k == "name" else 14) for k in
                 ("name", "background", "midground", "foreground", "light", "detail", "leading_line")}
                for s in out.get("sets") or [] if _clean(s.get("name"))]
        names = {s["name"].lower(): s for s in sets}
        assigned = {str(x.get("id", "")).strip().lower(): x for x in out.get("shots") or []}
        if not sets or len(assigned) < len(ids) * 0.6:
            raise ValueError(f"{len(sets)} sets, {len(assigned)} of {len(ids)} shots assigned")
    except Exception as e:  # noqa: BLE001
        log(f"Set builder: skipped ({str(e)[:160]}); shots keep the writer's locations")
        story["set_builder"] = "off"
        return story
    old = {str(l.get("name", "")).lower(): l for l in story.get("locations") or []}
    story["locations"] = [{"name": s["name"], "look": set_look(s), "layers": s} for s in sets] + \
        [l for n, l in old.items() if n not in names]  # keep writer locations the builder didn't replace
    used = set()
    for i, sc in enumerate(story["scenes"]):
        for letter, key in SHOT_KEYS.items():
            a = assigned.get(f"{i + 1}{letter}")
            if not a or not str(sc.get(key) or "").strip():
                continue
            name = _clean(a.get("set"), 40)
            if name.lower() in names:
                sc[LOC_KEYS[letter]] = names[name.lower()]["name"]
                used.add(name.lower())
            elif name.lower() in ("none", "", "n/a"):
                sc[LOC_KEYS[letter]] = "none"
            if _clean(a.get("focal"), 10):
                sc[FOCAL_KEYS[letter]] = _clean(a.get("focal"), 10)
    story["set_builder"] = f"{len(used)} sets"
    log(f"Set builder: {len(sets)} sets ({', '.join(s['name'] for s in sets)}), {len(assigned)} shots assigned")
    return story


def composition(story: dict, scene_i: int, letter: str) -> str:
    """Composition words for one shot (only when the set builder ran): its focal subject first, then depth."""
    if not str(story.get("set_builder") or "").endswith("sets"):
        return ""
    focal = (story["scenes"][scene_i] or {}).get(FOCAL_KEYS.get(letter or "a", "image_focal"))
    words = CONFIG.get("set_builder", {}).get("composition") or (
        "clear focal point, layered depth with a dark textured foreground, a midground subject and a pale misty "
        "background, subject rim-lit so its silhouette separates from the background")
    return ", ".join(p for p in (f"the eye drawn first to {focal}" if focal else "", words) if p)


def summary(story: dict) -> str:
    return json.dumps([l.get("name") for l in story.get("locations") or []])
