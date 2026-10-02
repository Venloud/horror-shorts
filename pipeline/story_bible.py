"""Build a compact story bible for visual continuity.

Inspired by MuMuAINovel's outline, character/worldbuilding, timeline, and consistency concepts.
This is deliberately local and deterministic: it does not add another model call or copy the
GPL-3.0 application's code. The bible is generated from the story Night Files already wrote and
is injected into visual planning so characters, locations, beats, and the ending stay consistent.
"""
import re


def _clean(value, limit=240):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _unique(items):
    out = []
    seen = set()
    for item in items:
        key = item.lower()
        if item and key not in seen:
            seen.add(key)
            out.append(item)
    return out


def build(story: dict) -> dict:
    """Attach a small canonical story bible to story['_story_bible']."""
    scenes = story.get("scenes") or []
    characters = []
    for c in story.get("characters") or []:
        name = _clean(c.get("name"), 80)
        look = _clean(c.get("look"), 220)
        if name:
            characters.append({"name": name, "look": look})

    locations = []
    for loc in story.get("locations") or []:
        name = _clean(loc.get("name"), 100)
        look = _clean(loc.get("look"), 220)
        if name:
            locations.append({"name": name, "look": look})

    timeline = []
    for i, scene in enumerate(scenes):
        narration = _clean(scene.get("narration"), 300)
        location = _clean(scene.get("location"), 120)
        scene_chars = []
        low = narration.lower()
        for c in characters:
            if c["name"].lower() in low:
                scene_chars.append(c["name"])
        timeline.append({
            "scene": i + 1,
            "event": narration,
            "location": location,
            "characters": scene_chars,
        })

    twist_scene = story.get("twist_scene")
    try:
        twist_scene = int(twist_scene)
    except (TypeError, ValueError):
        twist_scene = max(1, len(scenes) - 1) if scenes else 1

    bible = {
        "title": _clean(story.get("title"), 120),
        "premise": _clean(story.get("premise"), 300),
        "setting": _clean(story.get("setting"), 220),
        "threat": _clean(story.get("threat"), 220),
        "twist": _clean(story.get("twist"), 260),
        "twist_scene": twist_scene,
        "characters": characters,
        "locations": locations,
        "timeline": timeline,
        "continuity_rules": [
            "Use the exact character names and keep each character's fixed look unchanged.",
            "Keep each shot in the scene's stated location unless the narration explicitly moves.",
            "Do not introduce a new person, creature, object, or location that the story does not establish.",
            "The twist scene must visually support the documented twist, not invent a different reveal.",
        ],
    }
    story["_story_bible"] = bible
    return bible


def summary(story: dict) -> str:
    bible = story.get("_story_bible") or build(story)
    chars = ", ".join(c["name"] for c in bible.get("characters") or []) or "none"
    return (f"Story bible: {bible.get('title') or '(untitled)'} | "
            f"characters: {chars} | twist scene: {bible.get('twist_scene')} | "
            f"timeline scenes: {len(bible.get('timeline') or [])}")
