"""Reusable, narration-grounded numbered clue overlays for Night Files.

No API calls, invented evidence, new asset dependency or change to shot timing.
A board exists ONLY when the narrator announces a 2-4-item list and explicitly
enumerates every item in order. The current illustrations remain visible below it.
"""
from __future__ import annotations

import re
from functools import lru_cache

from PIL import Image, ImageDraw

NUMBER = {"two": 2, "three": 3, "four": 4, "2": 2, "3": 3, "4": 4}
ORDINALS = ("first", "second", "third", "fourth")
LIST_NOUNS = {"clues", "reasons", "signs", "facts", "details", "steps", "things"}
LEAD = {"the", "a", "an", "that", "there", "it", "they", "we"}
TRAIL = {"into", "with", "from", "at", "to", "and", "but", "by", "in", "on", "of", "for", "as", "than"}


def _word(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


def _label(words: list[dict], ordinal_at: int) -> str:
    """Use ONLY contiguous narration words, not an AI-generated explanation."""
    items = []
    for w in words[ordinal_at + 1:ordinal_at + 19]:
        value = str(w.get("word") or "").strip()
        if not _word(value):
            continue
        items.append(_word(value))
        if re.search(r"[.!?;]$", value):
            break
    while items and items[0] in LEAD:
        items.pop(0)
    if not items:
        return ""
    if "no" in items:
        pos = items.index("no")
        # A long institutional prefix can bury the evidence; prefer the spoken
        # negated finding (e.g., "no barometric drop") where it is contiguous.
        if pos >= 3:
            items = items[pos:]
    # Use a meaningful complete spoken phrase, not the first four words.
    # "handwriting matched no harbor" loses the clue: the CLERK must remain.
    # Stop before an explanatory subordinate clause, if one follows.
    for ix, word in enumerate(items):
        if ix >= 3 and word in ("who", "whose", "which", "because", "although", "while"):
            items = items[:ix]
            break
        if ix >= 4 and word == "long" and items[ix + 1:ix + 2] == ["before"]:
            items = items[:ix]
            break
    chosen = []
    for word in items:
        candidate = " ".join(chosen + [word])
        if chosen and len(candidate) > 48 and len(chosen) >= 3:
            break
        chosen.append(word)
    while len(chosen) > 2 and chosen[-1] in TRAIL:
        chosen.pop()
    return " ".join(chosen).upper()


def plan(narration: dict) -> dict | None:
    """Return one exact-word-timed list, otherwise None (no visual change)."""
    words = narration.get("words") or []
    if not isinstance(words, list) or len(words) < 9:
        return None
    tokens = [_word(w.get("word", "")) for w in words]
    for idx, count_word in enumerate(tokens):
        count = NUMBER.get(count_word)
        if count is None or idx + 2 >= len(tokens):
            continue
        noun = next((tokens[j] for j in range(idx + 1, min(idx + 5, len(tokens)))
                     if tokens[j] in LIST_NOUNS), None)
        if not noun:
            continue
        try:
            started = float(words[idx].get("start", 0))
        except (TypeError, ValueError):
            continue
        cues, cursor = [], idx + 1
        valid = True
        for ordinal in ORDINALS[:count]:
            match = next((j for j in range(cursor, len(tokens)) if tokens[j] == ordinal), None)
            if match is None:
                valid = False
                break
            try:
                when = float(words[match].get("start", 0))
            except (TypeError, ValueError):
                valid = False
                break
            if when <= started or when - started > 36:
                valid = False
                break
            label = _label(words, match)
            if not label:
                valid = False
                break
            cues.append({"at": when, "label": label, "ordinal": ordinal, "index": match})
            cursor = match + 1
        if not valid:
            continue
        last = cues[-1]["index"]
        end = cues[-1]["at"] + 5.0
        for w in words[last + 2:last + 26]:
            value = str(w.get("word") or "")
            if re.search(r"[.!?;]$", value):
                try:
                    end = float(w.get("end", w.get("start", end))) + 0.85
                except (TypeError, ValueError):
                    pass
                break
        end = min(max(end, cues[-1]["at"] + 1.1), cues[-1]["at"] + 8.0)
        return {"start": started, "end": end, "count": count,
                "noun": noun.upper(), "cues": cues}
    return None


@lru_cache(maxsize=48)
def _state_image(labels: tuple[str, ...], noun: str, accent: tuple[int, int, int], shown: int) -> Image.Image:
    """Cache each stable board state. Unspoken future clues remain unreadable."""
    import noir
    count = len(labels)
    w, h = 840, 120 + count * 119  # x=120..960, clear of the social-app button column
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer, "RGBA")
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=30, fill=(13, 17, 24, 221),
                        outline=(187, 177, 170, 103), width=2)
    title = f"{count} {noun}"  # both count and list type were spoken
    d.text((35, 26), title, font=noir.font("cond", 62), fill=(241, 235, 228, 245))
    d.rectangle((35, 94, w - 36, 98), fill=accent + (168,))
    for i, label in enumerate(labels):
        top = 108 + i * 119
        active = i < shown
        d.rounded_rectangle((24, top, w - 24, top + 104), radius=15,
                            fill=(62, 58, 63, 224) if active else (35, 39, 45, 175))
        d.text((45, top + 21), f"{i + 1:02d}",
               font=noir.font("mono", 48),
               fill=accent + (255,) if active else (151, 145, 141, 145))
        d.line((151, top + 19, 151, top + 84), fill=accent + (255,) if active else (96, 96, 98, 130), width=4)
        if active:
            f, lines = noir.fit(label, "cond", 605, 2, 45, 30)
            for row, text in enumerate(lines):
                d.text((180, top + 13 + row * (f.size + 1)), text, font=f, fill=(246, 239, 232, 250))
        else:
            d.text((180, top + 31), "···", font=noir.font("cond", 45), fill=(150, 150, 151, 125))
    return layer


def apply(frame: Image.Image, schedule: dict | None, t: float, accent: tuple[int, int, int]) -> Image.Image:
    """Animate list entries once when spoken, leaving normal shots/captions intact."""
    if not schedule or t < schedule["start"] or t >= schedule["end"]:
        return frame
    import noir
    cues = schedule["cues"]
    labels = tuple(c["label"] for c in cues)
    count = sum(t >= c["at"] for c in cues)
    board = _state_image(labels, schedule["noun"], tuple(accent), count)
    if count and t < cues[count - 1]["at"] + 0.26:
        before = _state_image(labels, schedule["noun"], tuple(accent), count - 1)
        board = Image.blend(before, board, noir.ease((t - cues[count - 1]["at"]) / 0.26))
    opacity = min(noir.ease((t - schedule["start"]) / 0.3),
                  noir.ease((schedule["end"] - t) / 0.35))
    if opacity < 1.0:
        board = board.copy()
        board.putalpha(board.getchannel("A").point(lambda x: int(x * max(0.0, opacity))))
    if frame.mode != "RGBA":
        frame = frame.convert("RGBA")
    frame.alpha_composite(board, ((frame.width - board.width) // 2, 236))
    return frame
