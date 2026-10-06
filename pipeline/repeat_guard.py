"""Repeat guard (Oct 5, after Lizzie Borden went out 4 times): no topic from the same case / topic / subgenre family
as any of the last `repeat_window` (15) videos, and no reused opening line. Checked against history.json AND the
videos waiting in the buffer (their caption.json), by every picker and once more on the finished story.

Families: a recent video's case / source name (e.g. "lizzie borden") found in the new topic's text, the same
subgenre, or a shared keyword family from config `topic_families` (e.g. every Bloody Mary prompt is one family).
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
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", str(s or "").lower())).strip()


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
    """Case / topic names of a recent video (urls and inbox paths are not names).

    Only checks SPECIFIC subjects (case, source) - NOT broad categories like subgenre.
    E.g. "Lizzie Borden" is specific, "legend / folklore" is too broad.
    """
    out = []
    for k in ("case", "source"):  # Removed "subgenre" - too broad, causes false positives
        v = entry.get(k)
        if isinstance(v, dict):
            v = v.get("title")
        v = _norm(v) if v and not str(v).startswith(("http", "inbox/")) else ""
        if len(v) >= 4:
            out.append(v)
    return out


def _families(text: str) -> set[str]:
    return {fam for fam, words in (CONFIG.get("topic_families") or {}).items()
            if any(_norm(w) and re.search(rf"\b{re.escape(_norm(w))}\b", text) for w in words)}


def repeat_of(*texts, history: list[dict]) -> str:
    """Why this topic repeats a recent video ("" = it doesn't)."""
    hay = _norm(" ".join(str(t or "") for t in texts))
    if not hay:
        return ""
    fams = _families(hay)
    for e in recent(history):
        title = e.get("title") or e.get("stamp") or "?"
        for name in _names(e):
            if re.search(rf"\b{re.escape(name)}\b", hay):
                return f"same topic as recent video '{title}' ({name})"
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
