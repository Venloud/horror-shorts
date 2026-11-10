"""Night Files editing rules: read what a shot's narration is doing and pick the restrained technique for it.

Pure functions over narration text, shared by pipeline/explainer.py (camera move, light grade, information cards).
Nothing here is scene-specific: the same cues work for any story. Most shots get no special treatment at all;
stillness is a normal, intended choice rather than a fallback.
"""
import re

# What the narration is doing in a shot (whole-word cues, case-insensitive).
CUES = {
    # someone moves toward a place or thing: a slow push-in follows them
    "approach": r"\b(approach\w*|walk(?:ed|s|ing)? (?:toward|towards|up|into|down)|step(?:ped|s)? (?:inside|into|closer)|"
                r"enter(?:ed|s|ing)?|closer|crept|moved toward|stood (?:outside|before|in front)|hallway|corridor|"
                r"staircase|doorway|abandoned|front door)\b",
    # a small object or record carries the information: tight closeup on it
    "detail": r"\b(letter|note|diary|journal|photo\w*|phone|screen|message|text|key|ring|footprint\w*|fingerprint\w*|"
              r"handwriting|signature|document\w*|record\w*|report|file|newspaper|article|map|clock|watch|tape|"
              r"recording|camera footage|envelope|receipt|ticket|label|tag|scratch(?:es)?|mark(?:s|ings)?)\b",
    # the frightening realisation lands: hold still, no movement
    "reveal": r"\b(realiz\w*|realis\w*|understood|recogni\w*|it was (?:her|him|them)|staring back|face|eyes|"
              r"standing (?:there|behind)|was already|had been dead|wasn't alone|was not alone|silence|didn't move|"
              r"waiting|watching|still there)\b",
    # emptiness or scale: pull back to isolate
    "isolation": r"\b(alone|empty|nobody|no one|deserted|miles|vast|entire (?:town|house|street)|whole (?:town|house)|"
                 r"silent (?:town|street|house)|middle of nowhere|for (?:days|weeks|years))\b",
    # warm practical light in frame: keep the warmth
    "warm": r"\b(lamp|candle\w*|fire\w*|fireplace|kitchen|porch light|streetlight|lantern|torch|flashlight|"
            r"sunset|dinner|bulb|neon)\b",
    # night and cold places: deeper blue shadows
    "night": r"\b(night|midnight|dark\w*|moon\w*|fog|mist|rain\w*|snow\w*|forest|woods|basement|cellar|attic|"
             r"3 a\.?m|(?:two|three|four) in the morning|cold)\b",
}
_RX = {k: re.compile(v, re.IGNORECASE) for k, v in CUES.items()}
HYPOTHETICAL = re.compile(r"\b(if|might|would|could|imagine|whether|maybe|perhaps)\b", re.IGNORECASE)

# Information worth a card. Only words the narrator actually said go on it (see info_card).
INFO = [
    ("CONTRADICTION", r"\b(but (?:the|her|his|their) (?:records?|file|police|report|death certificate|photo\w*)|"
                      r"never existed|didn't match|did not match|had been dead (?:for|since)|was impossible|"
                      r"no record of|wasn't there|was not there)\b"),
    ("DOCUMENT", r"\b(letter|diary|journal|report|death certificate|birth certificate|police file|case file|"
                 r"newspaper|article|record\w*|document\w*|note (?:said|read))\b"),
    ("EVIDENCE", r"\b(evidence|fingerprint\w*|footprint\w*|blood|camera footage|security footage|recording|"
                 r"dna|autopsy|tape)\b"),
    ("DISCOVERY", r"\b(discovered|found out|turned out|was revealed|investigators found|police found|"
                  r"they found|she found|he found)\b"),
]
_INFO = [(label, re.compile(rx, re.IGNORECASE)) for label, rx in INFO]

MOVES = ("push", "pan", "pull", "closeup", "still")


def tags(text: str) -> set:
    """Which cues the shot's narration carries."""
    return {k for k, rx in _RX.items() if rx.search(text or "")}


def camera_move(text: str, last: str = "", moving_run: int = 0) -> str:
    """One camera move for a story picture, from what its narration is doing.

    reveal -> still (the moment lands without motion); detail -> closeup; approach -> push;
    isolation -> pull. With no cue the camera alternates a slow push with a still hold, and after two moving shots
    in a row it holds still, so the video never moves constantly. A move is never repeated back to back except
    'still', which may follow a reveal hold only once."""
    t = tags(text)
    if "reveal" in t:
        want = "still"
    elif "detail" in t:
        want = "closeup"
    elif "approach" in t:
        want = "push"
    elif "isolation" in t:
        want = "pull"
    elif moving_run >= 2 or last not in ("still", ""):
        want = "still"
    else:
        want = "push"
    if want == last and want != "still":
        want = "still"
    return want


def grade(text: str) -> str:
    """The scene's light: 'warm' (a practical light source is in the story), 'night' (cold blue shadows) or
    'dusk' (the gentle default split-tone). Chosen per scene, never one filter for the whole video."""
    t = tags(text)
    if "warm" in t:
        return "warm"
    if "night" in t:
        return "night"
    return "dusk"


# per-channel split-tone strengths (shadow lift toward blue, highlight push toward warm)
GRADES = {"night": {"shadow": (-6, 4, 22), "high": (6, 0, -8), "mix": 0.9},
          "dusk": {"shadow": (-3, 2, 12), "high": (8, 3, -6), "mix": 0.7},
          "warm": {"shadow": (-2, 2, 10), "high": (16, 7, -10), "mix": 0.8}}


def grade_lut(name: str) -> list[int]:
    """A 768-entry Pillow point table: shadows cooled toward blue, highlights warmed, midtones untouched."""
    g = GRADES.get(name, GRADES["dusk"])
    out = []
    for ch in range(3):
        for v in range(256):
            x = v / 255.0
            shadow = (1 - x) ** 2 * g["shadow"][ch]
            high = x ** 2 * g["high"][ch]
            out.append(max(0, min(255, int(round(v + g["mix"] * (shadow + high))))))
    return out


def _sentence(text: str, pos: int) -> str:
    starts = [m.end() for m in re.finditer(r"[.!?]\s+", text[:pos])]
    a = starts[-1] if starts else 0
    m = re.search(r"[.!?](\s|$)", text[pos:])
    b = pos + m.end() if m else len(text)
    return text[a:b].strip()


def info_card(text: str) -> dict | None:
    """A card for a clear information reveal in this narration, or None. The card body is the narrator's own
    sentence, trimmed to its words around the cue: nothing is paraphrased or invented. Hypotheticals never count."""
    for label, rx in _INFO:
        m = rx.search(text or "")
        if not m:
            continue
        sent = _sentence(text, m.start())
        if not sent or HYPOTHETICAL.search(sent):
            continue
        # the comma-delimited clause holding the cue, so the card reads as a whole phrase
        off = text.find(sent)
        cut = [0] + [k + 1 for k, ch in enumerate(sent) if ch in ",;:"] + [len(sent) + 1]
        rel = m.start() - off
        lo = max(c for c in cut if c <= rel)
        hi = min(c for c in cut if c > rel)
        words = sent[lo:hi - 1].strip(" ,;:.!?").split()
        if len(words) < 3:
            continue
        cue_at = len(sent[lo:rel].split())
        a = max(0, min(cue_at - 4, len(words) - 12))
        body = " ".join(words[a:a + 12]).strip(" ,;:")
        return {"label": label, "text": body, "cue": m.group(0), "char": m.start()}
    return None
