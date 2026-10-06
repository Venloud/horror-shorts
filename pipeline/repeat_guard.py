"""Repeat guard (Oct 5, after Lizzie Borden went out 4 times): no topic from the same case / topic / subgenre family
as any of the last `repeat_window` (15) videos, and no reused opening line. Checked against history.json AND the
videos waiting in the buffer (their caption.json), by every picker and once more on the finished story.

Families: a recent video's specific subject (case / source / title with generic words like "The Legend of" removed,
e.g. "lizzie borden", "strigoi") found in the new topic's text or vice versa, the same subgenre for fiction / coldcase
only, or a shared keyword family from config `topic_families` (e.g. every Bloody Mary prompt is one family).
Never raises: an unreadable buffer only means the check uses history alone.
"""
import difflib
import json
import re
import tempfile
from pathlib import Path

from common import CONFIG, log

_BUFFER: dict = {"metas": None}


def _norm(s) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()  # Gévaudan -> gevaudan
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", s.lower())).strip()


# Words that say what KIND of video it is, never WHO/WHAT it is about ("The Romanian Legend of the Strigoi").
_GENERIC = set("""the a an of in on at and legend legends folklore myth myths tale tales story stories true mystery
mysterious unsolved disappearance vanishing murder murders kidnapping case file files strange curse haunting incident
heist century real german romanian japanese mexican haitian caribbean irish english cornish american french""".split())


def _subject(text) -> str:
    """The specific subject of a case / title: "(folklore)" dropped, the part after the last "of" for
    "<kind> of <subject>" titles, generic words removed. "The Romanian Legend of the Strigoi" -> "strigoi",
    "Disappearance of Jim Thompson" -> "jim thompson", "Bloody Mary (folklore)" -> "bloody mary"."""
    t = _norm(re.sub(r"\(.*?\)", " ", str(text or "")))
    if " of " in f" {t} ":
        tail = t.rsplit(" of ", 1)[-1]
        if any(w not in _GENERIC for w in tail.split()):
            t = tail
    return " ".join(w for w in t.split() if w not in _GENERIC)


def buffer_metas() -> list[dict]:
    """caption.json of every video waiting in the buffer (read once per run)."""
    if _BUFFER["metas"] is None:
        metas = []
        try:
            import buffer
            for v in buffer.videos():
                with tempfile.TemporaryDirectory() as d:
                    metas.append(json.loads(buffer.download(v["json"], Path(d) / "m.json").read_text()))
        except Exception as e:  # noqa: BLE001
            log(f"Repeat guard: buffer not readable ({type(e).__name__}), checking history only")
        _BUFFER["metas"] = metas
    return _BUFFER["metas"]


def recent(history: list[dict]) -> list[dict]:
    """The last N videos that were made (buffered or posted, not skipped) + everything waiting in the buffer."""
    n = int(CONFIG.get("repeat_window", 15))
    made = [h for h in history if not h.get("skipped") and (h.get("buffered") or h.get("posted"))]
    return made[-n:] + buffer_metas()


def _names(entry: dict) -> list[str]:
    """The specific subjects of a recent video: its case, source (not urls / inbox paths) and title subject.
    Subgenre only for made-up stories (fiction / coldcase), where it is a real concept ("lost in the deep woods");
    for lore / mystery / case it is just the mode label ("legend / folklore"), which made every legend block every
    other legend (Oct 5: Baba Yaga rejected as 'the same topic' as the Cornish Owlman)."""
    texts = [entry.get("case"), entry.get("title")]
    src = entry.get("source")
    if isinstance(src, dict):
        src = src.get("title")
    if src and not str(src).startswith(("http", "inbox/")):
        texts.append(src)
    out = [_subject(t) for t in texts if t]
    if entry.get("mode") in ("fiction", "coldcase") and entry.get("subgenre"):
        out.append(_norm(entry["subgenre"]))
    return [n for n in dict.fromkeys(out) if len(n) >= 4]


def _families(text: str) -> set[str]:
    return {fam for fam, words in (CONFIG.get("topic_families") or {}).items()
            if any(_norm(w) and re.search(rf"\b{re.escape(_norm(w))}\b", text) for w in words)}


def _has(phrase: str, text: str) -> bool:
    return bool(phrase) and re.search(rf"\b{re.escape(phrase)}\b", text) is not None


def repeat_of(*texts, history: list[dict]) -> str:
    """Why this topic repeats a recent video ("" = it doesn't). A recent subject found in the new topic's text
    ("lizzie borden" in "The Lizzie Borden Mystery"), or the new topic's own subject found in a recent subject
    ("baba yaga" in "baba yaga witch woods"; one-word subjects need 6+ letters so "witch" alone blocks nothing),
    or a shared `topic_families` keyword."""
    raw = [str(t or "") for t in texts if t]
    hay = _norm(" ".join(raw))
    if not hay:
        return ""
    hay_s = " ".join(w for w in hay.split() if w not in _GENERIC)
    mine = [x for x in (_subject(t) for t in raw) if len(x.split()) >= 2 or len(x) >= 6]
    fams = _families(hay)
    for e in recent(history):
        title = e.get("title") or e.get("stamp") or "?"
        for name in _names(e):
            if _has(name, hay) or _has(name, hay_s):
                return f"same topic as recent video '{title}' ({name})"
            for m in mine:
                if _has(m, name):
                    return f"same topic as recent video '{title}' ({m})"
        shared = fams & _families(_norm(" ".join(str(e.get(k) or "") for k in ("title", "case", "subgenre", "source"))))
        if shared:
            return f"same topic family ({', '.join(sorted(shared))}) as recent video '{title}'"
    return ""


def opening_reused(opening: str, history: list[dict]) -> str:
    """An opening line that (nearly) repeats one already used, anywhere in history or the buffer."""
    a = _norm(opening)
    if len(a) < 12:
        return ""
    for e in history + buffer_metas():
        b = _norm(e.get("opening"))
        if b and (a == b or a.split()[:8] == b.split()[:8] or difflib.SequenceMatcher(None, a, b).ratio() >= 0.85):
            return f"opening line reused from '{e.get('title')}' (\"{e.get('opening')}\")"
    return ""
