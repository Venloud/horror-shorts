"""Hollywood: the editor's context library and director (owner, Oct 31).

Not an AI: a library of context -> motion-graphic links (data/hollywood/library.json) and a loop that runs EVERY
sentence of the narration against it, line by line (a whole body of text at once would give inaccurate context).
Places come from the offline geo pack (assets/geo): every 1-4 word combination of a sentence is looked up, and the
graphic goes only as deep as the narrator does (country -> pin + flag; state / province -> zoom + red outline; city
-> pin at the city). Its memory (data/hollywood/memory.json, shared state on main) grows after every video: which
entries fired, every place it resolved (cached for the next lookup) and the phrases no entry matched yet, counted,
so new library entries can be added where stories keep needing them.

Used by explainer.plan_effects (candidates) and main.py (learn, after a video enters the buffer). Story-agnostic.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from common import ROOT, log

LIB = ROOT / "data" / "hollywood" / "library.json"
MEMORY = ROOT / "data" / "hollywood" / "memory.json"
GEO = ROOT / "assets" / "geo"
# words that are also place names but rarely mean the place in a story sentence
NOT_PLACES = {"chad", "jordan", "georgia", "victoria", "florence", "paris", "lincoln", "washington", "jersey",
              "turkey", "china", "guinea", "niger", "nice", "split", "reading", "mobile", "normal", "orange", "york",
              "independence", "liberty", "hope", "eden", "eureka", "darwin", "hamilton", "wellington", "regina",
              "virginia", "carolina", "victoria", "alexandria", "sydney", "austin", "dallas", "phoenix", "aurora"}
TRUSTED_ALONE = {"china", "turkey", "georgia", "jordan", "paris", "virginia", "washington", "sydney", "phoenix"}


def library() -> list[dict]:
    try:
        return json.loads(LIB.read_text(encoding="utf-8")).get("entries", [])
    except (OSError, ValueError):
        return []


@lru_cache(maxsize=1)
def counter_kinds() -> dict:
    """{"people": [...], "bullets": [...], "shots": [...]} counted nouns from the library."""
    try:
        c = json.loads(LIB.read_text(encoding="utf-8")).get("counters") or {}
    except (OSError, ValueError):
        c = {}
    return {k: set(v) for k, v in c.items() if not k.startswith("_") and isinstance(v, list)}


def hits_of(n: str) -> int:
    """'twice' -> 2, 'three times' -> 3, 'once' -> 1, '4' -> 4; 0 when unclear."""
    import spoken_numbers as nums
    n = (n or "").lower().replace(" times", "").strip()
    if n == "once":
        return 1
    if n == "twice":
        return 2
    vals = nums.values(n)
    return int(next(iter(vals))) if len(vals) == 1 and 1 <= next(iter(vals)) <= 20 else 0


def memory() -> dict:
    try:
        return json.loads(MEMORY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"videos": 0, "entries": {}, "places": {}, "unmatched": {}, "log": []}


# ---------------------------------------------------------------- sentences + word timing

def sentences(narration: dict) -> list[dict]:
    """[{"text", "idx": word indexes, "offs": char offset of each word in text, "scene"}], one per spoken sentence."""
    out, cur = [], []
    for k, w in enumerate(narration["words"]):
        cur.append(k)
        nxt = narration["words"][k + 1] if k + 1 < len(narration["words"]) else None
        if re.search(r"[.!?…]['\"”’)]*$", w["word"]) or nxt is None or nxt.get("scene") != w.get("scene"):
            text, offs = "", []
            for j in cur:
                offs.append(len(text))
                text += narration["words"][j]["word"] + " "
            out.append({"text": text, "idx": cur, "offs": offs, "scene": w.get("scene", 0)})
            cur = []
    return out


def word_at(sent: dict, char: int) -> int:
    import bisect
    return sent["idx"][max(0, bisect.bisect_right(sent["offs"], char) - 1)]


# ---------------------------------------------------------------- places

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower().replace("-", " ")).strip()


@lru_cache(maxsize=1)
def gazetteer() -> dict:
    """lowercase name -> list of {level, iso2, name, lon, lat, (rings for admin1)} from assets/geo."""
    g: dict = {}

    def add(name, rec):
        n = _norm(name)
        if len(n) >= 3:
            g.setdefault(n, []).append(rec)
            if n.startswith("the "):
                g.setdefault(n[4:], []).append(rec)
    try:
        for c in json.loads((GEO / "countries.json").read_text()):
            for n in c["names"]:
                add(n, {"level": "country", "iso2": c["iso2"], "name": c["name"], "lon": c["lon"], "lat": c["lat"]})
        for a in json.loads((GEO / "admin1.json").read_text()):
            for n in a["names"]:
                add(n, {"level": "region", "iso2": a["iso2"], "name": a["name"], "type": a["type"], "lon": a["lon"],
                        "lat": a["lat"], "rings": a["rings"]})
        for c in json.loads((GEO / "cities.json").read_text()):
            add(c["name"], {"level": "city", "iso2": c["iso2"], "name": c["name"], "admin1": c["admin1"],
                            "lon": c["lon"], "lat": c["lat"], "rank": c["rank"]})
    except (OSError, ValueError):
        return {}
    return g


def _country(iso2: str) -> dict | None:
    for recs in gazetteer().values():
        for r in recs:
            if r["level"] == "country" and r["iso2"] == iso2:
                return r
    return None


def find_places(story: dict, narration: dict) -> list[dict]:
    """Every place the narration names, in spoken order, first mention only: every 1-4 word capitalised
    combination of each sentence is looked up. A name that is also a common word / person name only counts when
    the story's setting / ledger / title also names it; a story character's name is never a place."""
    gz = gazetteer()
    if not gz:
        return []
    words = narration["words"]
    people = {_norm(p) for c in story.get("characters") or [] for p in str(c.get("name") or "").split()}
    context = _norm(" ".join([str(story.get("setting") or ""), str(story.get("title") or ""),
                              " ".join(map(str, story.get("fact_ledger") or []))]))
    said_iso = set()
    found, seen = [], set()
    for sent in sentences(narration):
        toks = [re.sub(r"^[^\w]+|[^\w]+$", "", words[k]["word"]) for k in sent["idx"]]
        k = 0
        while k < len(toks):
            hit = None
            for n in range(4, 0, -1):
                span = toks[k:k + n]
                if len(span) < n or not span or not all(t[:1].isupper() or t.lower() in ("of", "the", "de")
                                                         for t in span) or not span[0][:1].isupper():
                    continue
                key = _norm(" ".join(span))
                if key not in gz or key in people or (key in NOT_PLACES and key not in context
                                                      and key not in TRUSTED_ALONE):
                    continue
                if k == 0 and n == 1 and key in NOT_PLACES:
                    continue  # a sentence-initial capital is not evidence of a name
                recs = gz[key]
                rec = (next((r for r in recs if r["level"] == "country"), None)
                       or next((r for r in recs if r["level"] == "region" and r["iso2"] in said_iso), None)
                       or next((r for r in recs if r["level"] == "city" and r["iso2"] in said_iso), None)
                       or next((r for r in recs if r["level"] == "region"), None)
                       or min((r for r in recs if r["level"] == "city"), key=lambda r: r.get("rank", 9), default=None))
                if rec:
                    hit = (n, rec, " ".join(span))
                    break
            if hit:
                n, rec, said = hit
                said_iso.add(rec["iso2"])
                uid = (rec["level"], rec["iso2"], rec["name"])
                if uid not in seen:
                    seen.add(uid)
                    found.append(dict(rec, said=said, word=sent["idx"][k], scene=sent["scene"]))
                k += n
            else:
                k += 1
    return found


def merge_places(places: list[dict]) -> list[dict]:
    """One graphic per sentence of places: "Fort Lauderdale, Florida" = Florida outlined + the pin at Fort
    Lauderdale; a country with its region or city = that region / city (the deepest the narration went)."""
    out, by_scene = [], {}
    for p in places:
        by_scene.setdefault((p["scene"], p["iso2"]), []).append(p)
    for group in by_scene.values():
        city = next((p for p in group if p["level"] == "city"), None)
        region = next((p for p in group if p["level"] == "region"), None)
        country = next((p for p in group if p["level"] == "country"), None)
        best = dict(city or region or country)
        if city and region:
            best.update(rings=region.get("rings"), region_name=region["name"],
                        said=f"{city['said']}, {region['said']}", level="city_in_region")
        elif (city or region) and country:
            best["said"] = f"{best['said']}, {country['said']}"
        best["word"] = min(p["word"] for p in group)
        out.append(best)
    return sorted(out, key=lambda p: p["word"])


def place_fields(p: dict) -> dict:
    """noir globe_pin fields for one place, only as deep as the narration: a country = pin + flag at the country;
    a region = zoom + red outline; a city = pin at the city (country map)."""
    f = {"lon": p["lon"], "lat": p["lat"], "iso2": p["iso2"], "label": p["said"], "level": p["level"]}
    if p["level"] in ("region", "city_in_region"):
        f["region_rings"] = p.get("rings") or []
        f["region_name"] = p.get("region_name") or p["name"]
    return f


# ---------------------------------------------------------------- the director

def _fill(template: str, m: re.Match, phrase: str) -> str:
    out = template
    for k, v in m.groupdict().items():
        out = out.replace("{" + k + "}", (v or "").strip())
    return out.replace("{phrase}", phrase)


def direct(story: dict, narration: dict, graphics_by_scene: dict, hypothetical: re.Pattern | None = None,
           phrase_of=None) -> list[dict]:
    """Effect candidates (explainer.plan_effects format) from the library + places, sentence by sentence."""
    import noir
    words = narration["words"]
    cands, used = [], {}
    true = bool(story.get("true_story"))
    places = find_places(story, narration)
    for p in merge_places(places)[:3]:  # big place moments: the first few named places, as deep as said
        land_t = words[p["word"]]["start"]
        lead = 1.6
        cands.append({"kind": "globe_pin", "start": land_t - lead, "dur": lead + 1.8, "anchor": land_t, "prio": 1,
                      "big": True, "source": "place", "fields": dict(place_fields(p), land=lead)})
    for sent in sentences(narration):
        text = sent["text"]
        for e in library():
            if used.get(e["id"], 0) >= int(e.get("max_per_video", 1)):
                continue
            if set(e.get("skip_if_graphic") or []) & graphics_by_scene.get(sent["scene"], set()):
                continue
            m = next((m for rx in e.get("when", []) for m in [re.search(rx, text, re.IGNORECASE)] if m), None)
            if not m:
                continue
            if e.get("not_hypothetical") and hypothetical and hypothetical.search(text):
                continue
            if e.get("not_negated") and re.search(r"\bnever\b", text, re.IGNORECASE):
                continue
            phrase = _note_text(text, m, phrase_of)
            fields = {k: _fill(v, m, phrase) if isinstance(v, str) else v for k, v in (e.get("fields") or {}).items()}
            if e["graphic"] == "ocean_crossing":
                ends = _crossing_ends(fields.get("water", ""), places, sent)
                if not ends:
                    continue
                fields.update(ends, label="THE " + fields.get("water", "").upper(),
                              vehicle="ship" if re.search(r"\bsail|ship|boat|rowed|swam|drift", text, re.I) else "plane")
            if e["graphic"] == "stamp":
                fields["text"] = fields.get("text", "").upper().replace("WENT MISSING", "MISSING")
                if fields["text"] not in noir.STAMPS:
                    continue
            if e["graphic"] == "sticky_note" and not fields.get("text"):
                continue
            if e["graphic"] == "hit_profile":
                fields["hits"] = hits_of(fields.pop("n", ""))
                if not fields["hits"]:
                    continue
            t = words[word_at(sent, m.start())]["start"]
            lead = float(e.get("lead", 0.3))
            dur = float(e.get("dur", 2.4))
            if e["graphic"] == "stamp":
                fields["land"] = lead
            if e["graphic"] == "sticky_note":
                fields["land"] = lead
            if e["graphic"] == "ocean_crossing":
                fields["travel"] = max(0.8, dur - 1.0)
            prio = {3: 2, 2: 3, 1: 6}.get(int(e.get("importance", 2)), 4)
            cands.append({"kind": e["graphic"], "start": t - lead, "dur": dur, "anchor": t, "prio": prio, "big": True,
                          "source": e["id"], "fields": fields, "sfx_extra": e.get("sfx") or []})
            used[e["id"]] = used.get(e["id"], 0) + 1
    crossings = [c for c in cands if c["kind"] == "ocean_crossing"]
    for c in crossings:  # a crossing already shows the places of its sentence (its two ends): no globe there
        c["prio"] = 1
        sent = next((x for x in sentences(narration) if any(words[k]["start"] == c["anchor"] for k in x["idx"])), None)
        if sent:
            cands = [g for g in cands if not (g["kind"] == "globe_pin" and
                                               any(abs(words[k]["start"] - g["anchor"]) < 1e-6 for k in sent["idx"]))]
    if true:  # a true story never animates a label the narration didn't say (fields come from matched words)
        cands = [c for c in cands if c["kind"] != "sticky_note" or c["fields"].get("text")]
    return cands


def _note_text(text: str, m: re.Match, phrase_of) -> str:
    """What the sticky note says: what follows a colon / "written on", else the clause's key phrase, else the
    matched clause's first words. Only the narration's own words."""
    after = text[m.end():]
    colon = re.search(r"[:\-–]\s*(.+)", after)
    if colon:
        return colon.group(1).strip(" .\"'“”")[:60]
    p = phrase_of(text) if phrase_of else ""
    if p:
        return p
    return " ".join(text[m.start():].split()[:6]).strip(" .,")


def _crossing_ends(water: str, places: list[dict], sent: dict) -> dict | None:
    """From -> to: two distant places named in this sentence, else the last place named before it -> the first
    one in it ("left Shannon, Ireland ... flew over the Atlantic toward Gander"), else the water's own coasts."""
    import math
    import noir
    merged = merge_places(places)
    far = lambda a, b: math.hypot(a["lon"] - b["lon"], a["lat"] - b["lat"]) > 8  # noqa: E731
    mine = [p for p in merged if p["word"] in sent["idx"]]
    before = [p for p in merged if p["word"] < sent["idx"][0]]
    if len(mine) >= 2 and far(mine[0], mine[-1]):
        return {"from": [mine[0]["lon"], mine[0]["lat"]], "to": [mine[-1]["lon"], mine[-1]["lat"]]}
    if mine and before and far(before[-1], mine[0]):
        return {"from": [before[-1]["lon"], before[-1]["lat"]], "to": [mine[0]["lon"], mine[0]["lat"]]}
    key = next((k for k in noir.OCEAN_ENDS if k in water.lower()), None)
    if not key:
        return None
    a, b = noir.OCEAN_ENDS[key]
    return {"from": list(a), "to": list(b)}


# ---------------------------------------------------------------- memory: it gets better after each video

def _phrases(text: str, explainer) -> list[str]:
    """The sentence's key phrases, else its pairs of neighbouring content words ("lighthouse keeper", "iron
    door"): what a future library entry could be keyed on."""
    out = [p["text"].lower() for p in explainer.key_phrases(text, limit=2, min_score=1.5)]
    if out:
        return out
    toks = [w for w in re.findall(r"[a-z][a-z'-]+", text.lower())]
    content = [w if (len(w) > 3 and w not in explainer.FUNCTION) else None for w in toks]
    return list(dict.fromkeys(f"{a} {b}" for a, b in zip(content, content[1:]) if a and b))[:3]


def learn(story: dict, stamp: str = "") -> None:
    """After a video entered the buffer: count which library entries fired, cache every place it resolved and
    count the sentences' key phrases no entry matched (a review list for new entries). Never raises."""
    try:
        mem = memory()
        mem["videos"] = int(mem.get("videos", 0)) + 1
        fired = story.get("explainer_effects") or []
        for e in fired:
            src = e.get("source") or e.get("kind")
            row = mem.setdefault("entries", {}).setdefault(src, {"fired": 0})
            row["fired"] += 1
            row["last"] = stamp
            if e.get("kind") == "globe_pin":
                f = e.get("fields") or {}
                pl = mem.setdefault("places", {}).setdefault(str(f.get("label")), {"times": 0})
                pl.update(iso2=f.get("iso2"), level=f.get("level"), lon=f.get("lon"), lat=f.get("lat"))
                pl["times"] += 1
        hit_scenes = {e.get("scene") for e in fired}
        for i, sc in enumerate(story.get("scenes") or []):
            if i in hit_scenes:
                continue
            import explainer
            for k in _phrases(sc.get("narration", ""), explainer):
                mem.setdefault("unmatched", {})[k] = mem["unmatched"].get(k, 0) + 1
        mem["unmatched"] = dict(sorted(mem.get("unmatched", {}).items(), key=lambda kv: -kv[1])[:400])
        mem.setdefault("log", []).append({"stamp": stamp, "story_id": story.get("story_id"),
                                          "effects": [e.get("source") or e.get("kind") for e in fired]})
        mem["log"] = mem["log"][-60:]
        MEMORY.parent.mkdir(parents=True, exist_ok=True)
        MEMORY.write_text(json.dumps(mem, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        log(f"Hollywood memory: {mem['videos']} videos, {len(mem.get('places', {}))} places known, "
            f"{len(mem.get('unmatched', {}))} unmatched phrases queued for new library entries")
    except Exception as e:  # noqa: BLE001
        log(f"Hollywood memory not updated ({e})")
