"""Narration-first choice of editor graphics, with no model call or invented evidence.

Image matching and rights checks remain in the existing media pipeline.
"""
from __future__ import annotations
import re

OBJECTS = {
    "newspaper": r"\bnewspapers?\b",
    "key": r"\bkeys?\b",
    "letter": r"\bletters?\b",
    "photograph": r"\b(?:photograph|photos?|pictures?)\b",
    "weapon": r"\b(?:mattock|hatchet|hammer|axe|knife|weapon)\b",
}
FOOTPRINTS = re.compile(r"\b(?:footprints?|tracks?)\b", re.I)
NO_RETURN = re.compile(
    r"\b(?:no|none|never|without)\b.{0,65}\b(?:back|out|return\w*|leav\w*|lead\w*)\b|"
    r"\b(?:no|none)\b.{0,35}\b(?:footprints?|tracks?)\b", re.I)
DATE = re.compile(
    r"\b(?:in|on|during)\s+(?:(?:late|early|mid)\s+)?"
    r"(?:january|february|march|april|may|june|july|august|september|october|november|december)\b|"
    r"\b(?:18|19|20)\d{2}\b", re.I)


def select(narration: str, *, first_scene: bool = False, places: list[str] | None = None) -> dict:
    """Plan narration-grounded motion graphics. Never invent evidence or coordinates."""
    narration = str(narration or "")
    found = []
    trail = FOOTPRINTS.search(narration)
    if trail and NO_RETURN.search(narration):
        found.append({"at": trail.group(0), "template": "footprint_route", "fields": {}})
    for obj, rx in OBJECTS.items():
        m = re.search(rx, narration, re.I)
        if m:
            found.append({"at": m.group(0), "template": "clue_object",
                          "fields": {"object": obj, "label": m.group(0)}})
    place = None
    for item in places or []:
        if not isinstance(item, str):
            continue
        m = re.search(r"\b" + re.escape(item.strip()) + r"\b", narration, re.I) if item.strip() else None
        if m and (place is None or m.start() < place.start()):
            place = m
    if place:
        found.append({"at": place.group(0), "template": "location_tag",
                      "fields": {"place": place.group(0)}})
    found.sort(key=lambda p: narration.lower().find(p["at"].lower()))
    has_date = bool(DATE.search(narration))
    method = "image"
    if not first_scene and (len(found) > 1 or has_date or
                            (found and found[0]["template"] == "location_tag")):
        method = "graphic_first"
    return {"method": method, "graphics": found[:3],
            "reason": ("illustrate distinct facts using clean graphics" if method == "graphic_first"
                       else "retain relevant cinematic imagery")}
