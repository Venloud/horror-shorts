"""Shot rules that keep a video's key beats real (run once after the story is written, before any picture).

- Legends: the creature/revenant is a character (fixed look in story["characters"]) and is SHOWN, by name, in at
  least `lore_creature_shots` (3) shots: the hook shot (scene 1 shot a), the twist scene and one more. Those shots
  are AI pictures (never stock, archive or a library reuse) so its look stays the same.
- Hook scene + twist scene: every shot has a real subject (a person, the creature or a story object in the story's
  moment) and is AI; never a texture, a surface or a blank wall.
- Filler shots anywhere (a bare texture / surface / threads / a wall) are rewritten to a real subject.
Locked shots are listed in story["_ai_only"] ("00a", "05b"...): library.py and media.py never fill them.
"""
import json
import re

from common import CONFIG, log

PROMPT_KEYS = {"a": "image_prompt", "b": "image_prompt_2", "c": "image_prompt_3", "d": "image_prompt_4"}
SRC_KEYS = {"a": "image_source", "b": "image_source_2", "c": "image_source_3", "d": "image_source_4"}
ALIASES = ["corpse", "creature", "revenant", "the dead", "body"]
# a shot whose main subject (first words) is only a material / surface / texture
_FILLER = re.compile(r"\b(textures?|surfaces?|walls?|ground|floor|threads?|fabric|cloth|linen|moss|soil|dirt|"
                     r"stones?|plaster|planks?|wood grain|bricks?|dust|leaves|bark|rust(ed|y)?|metal|paint|shadows?|"
                     r"pattern|grain)\b", re.I)
_SUBJECT = re.compile(r"\b(man|men|woman|women|villagers?|gravedigger|priest|family|mother|father|widow\w*|husband|"
                      r"wife|neighbou?rs?|people|crowd|figure|person|hunter|farmer|corpse|creature|revenant|body|"
                      r"ghost|spirit|monster|beast|coffin|grave|mouth|face|hand|hands)\b", re.I)
_GORE = re.compile(r"\b(blood\w*|gore|gory|guts|entrails|severed|pentagram|occult|sigil|all-seeing)\b", re.I)


_CREATURE_ACTS = ["standing still and staring", "emerging from the shadows", "seen up close, its face half lit",
                  "glimpsed at a distance", "looming in a doorway", "lying motionless, eyes open"]
_PERSON_ACTS = ["looking over his shoulder", "frozen in fear", "stepping forward slowly", "whispering a prayer",
                "staring at the ground", "holding the lantern high"]


def _tag(i: int, l: str) -> str:
    return f"{i:02d}{l}"


def _letters() -> str:
    return "abcd"[: max(1, min(4, int(CONFIG.get("shots_per_scene", 2))))]


def key_scenes(story: dict) -> set[int]:
    n = len(story.get("scenes") or [])
    try:
        twist = int(story.get("twist_scene"))
    except (TypeError, ValueError):
        twist = n - 2
    return {0, max(0, min(n - 1, twist))} if n else set()


_NEGATED = re.compile(r"\b(no|without|empty of|devoid of)\s+(\w+\s+)?(people|person|figures?|one|bodies|humans?)\b",
                      re.I)
_ON_TABLE = re.compile(r"\b(resting|lying|sitting|placed|scattered) (on|in) (an? |the )?(\w+ ){0,2}(table|surface|floor|"
                       r"ground|soil|dirt|shelf|counter)\b", re.I)


def has_subject(story: dict, text: str) -> bool:
    """A person, a story character, the creature or a story-moment word (grave, coffin, mouth...)."""
    names = [c.get("name", "").lower() for c in story.get("characters") or [] if c.get("name")]
    text = _NEGATED.sub("", text)  # "empty, no people" is not a person
    low = text.lower()
    return any(nm and nm in low for nm in names) or bool(_SUBJECT.search(text))


def is_filler(story: dict, text: str) -> bool:
    """A bare texture / surface / wall, or a generic object lying on a table, with no person, creature or story
    subject in it ("silver coins resting on a table" is not "a coin in the corpse's mouth")."""
    if has_subject(story, text):
        return False
    return bool(_FILLER.search(" ".join(text.split()[:8])) or _ON_TABLE.search(text))


def lock(story: dict, i: int, l: str) -> None:
    sc = story["scenes"][i]
    sc[SRC_KEYS[l]] = "ai"
    tags = story.setdefault("_ai_only", [])
    if _tag(i, l) not in tags:
        tags.append(_tag(i, l))


def ai_only(story: dict, i: int, l: str) -> bool:
    return _tag(i, l) in (story.get("_ai_only") or [])


def _creature(story: dict) -> str:
    if story.get("mode") != "lore" or story.get("true_story"):
        return ""
    return str(story.get("case") or "").strip().lower()


def _creature_entry(story: dict, name: str) -> dict:
    chars = story.setdefault("characters", [])
    for c in chars:
        if name in str(c.get("name", "")).lower():
            c["name"] = name  # shots refer to it by exactly this name
            return c
    import images
    look = ""
    try:
        narration = " ".join(sc.get("narration", "") for sc in story.get("scenes") or [])
        ans = images._gemini_json(
            f"A short illustrated legend video about the {name}. Give the {name} ONE fixed look of 15-20 words "
            "exactly as the legend describes it (no blood, no gore, no occult symbols).\n"
            f"NARRATION: {narration[:2000]}\nReturn JSON {{\"look\": \"...\"}}") or {}
        look = str(ans.get("look", "")).strip()
    except Exception:  # noqa: BLE001
        look = ""
    if not look or _GORE.search(look):
        look = (f"the {name} of the legend: a pale gaunt corpse in a torn linen burial shroud, sunken cheeks, "
                "dark hollow eyes, mouth slightly open, no blood")
    entry = {"name": name, "look": look, "aliases": ALIASES}
    chars.insert(0, entry)
    log(f"Creature sheet added: {name}: {look}")
    return entry


def _rewrite(story: dict, jobs: list[dict]) -> dict:
    """{tag: new prompt} from one small LLM call; empty on failure (callers fall back to templates)."""
    import images
    chars = "; ".join(f"{c['name']}: {c.get('look', '')}" for c in story.get("characters") or [] if c.get("name"))
    ask = ("Rewrite these image prompts for a dark painted horror illustration video. Each new prompt: max 25 "
           "words, ONE clear subject in the moment the narration describes, plain descriptive text, no gore, no "
           "readable text, no occult symbols, never a real victim's body, never a texture, surface or blank wall. "
           "Refer to characters by their exact names.\n"
           f"CHARACTERS: {chars}\nSHOTS:\n" + json.dumps(jobs, ensure_ascii=False)
           + '\nReturn JSON {"shots": [{"id": "00a", "prompt": "..."}]}')
    try:
        ans = images._gemini_json(ask) or {}
    except Exception:  # noqa: BLE001
        ans = {}
    out = {}
    for s in ans.get("shots") or []:
        p = str(s.get("prompt", "")).strip()
        if p and not _GORE.search(p):
            out[str(s.get("id", ""))] = p
    return out


def apply(story: dict) -> dict:
    """Run the rules on a freshly written story (idempotent). Returns a small report."""
    scenes = story.get("scenes") or []
    if not scenes:
        return {}
    letters = _letters()
    keys = key_scenes(story)
    creature = _creature(story)
    jobs: list[dict] = []
    need_creature: set[str] = set()
    if creature:
        _creature_entry(story, creature)
        want = int(CONFIG.get("lore_creature_shots", 3))
        has = {_tag(i, l) for i, sc in enumerate(scenes) for l in letters
               if creature in (sc.get(PROMPT_KEYS[l]) or "").lower()}
        twist = max(keys)
        order = [_tag(0, "a"), _tag(twist, "a")]
        # then scenes whose narration talks about the creature / the dead, then the middle of the video
        said = [i for i, sc in enumerate(scenes) if re.search(rf"\b({re.escape(creature)}|corpse|revenant|the dead|"
                                                               r"grave|coffin|body)\b", sc.get("narration", ""), re.I)]
        order += [_tag(i, "a") for i in said] + [_tag(i, "a") for i in range(1, len(scenes))]
        for t in dict.fromkeys(order):
            if len(has | need_creature) >= want and t not in order[:2]:
                break
            if t not in has:
                need_creature.add(t)
        has |= need_creature
    for i, sc in enumerate(scenes):
        for l in letters:
            t = _tag(i, l)
            text = (sc.get(PROMPT_KEYS[l]) or "").strip()
            if not text and t not in need_creature:
                continue
            if t in need_creature:
                jobs.append({"id": t, "narration": sc.get("narration", ""), "prompt": text,
                             "must": f"show the {creature} (by exactly that name) in this moment"})
            elif is_filler(story, text) or (i in keys and not has_subject(story, text)):
                jobs.append({"id": t, "narration": sc.get("narration", ""), "prompt": text,
                             "must": "a real subject: a story character (by name), the creature, or a story object "
                                     "in this moment, instead of this texture / surface"})
    new = _rewrite(story, jobs) if jobs else {}
    rewritten = []
    for j in jobs:
        i, l = int(j["id"][:2]), j["id"][2]
        sc = scenes[i]
        p = new.get(j["id"], "")
        loc = sc.get(f"image_location{'' if l == 'a' else '_' + str('abcd'.index(l) + 1)}") or sc.get("location") or ""
        loc = "" if loc.lower() == "none" else loc
        where = f" in the {loc}" if loc else " in the dark"
        if j["id"] in need_creature and creature not in p.lower():
            act = _CREATURE_ACTS[len(rewritten) % len(_CREATURE_ACTS)]
            p = f"the {creature} {act}{where}, lantern light, eerie"
        elif not p:  # no LLM answer: a person of the story in this place, framing varied per shot
            people = [c["name"] for c in story.get("characters") or [] if c.get("name") and c["name"] != creature]
            who = people[0] if people else "a frightened villager holding a lantern"
            p = f"{who} {_PERSON_ACTS[len(rewritten) % len(_PERSON_ACTS)]}{where}, tense, lantern light"
        sc[PROMPT_KEYS[l]] = p
        lock(story, i, l)  # a rewritten story moment is always a fresh AI picture
        rewritten.append(j["id"])
        log(f"Shot {j['id']}: {'creature shot' if j['id'] in need_creature else 'filler replaced'}: {p}")
    for i, sc in enumerate(scenes):  # lock the creature's shots and every key-scene shot to AI
        for l in letters:
            text = (sc.get(PROMPT_KEYS[l]) or "").lower()
            if text and ((creature and creature in text) or i in keys):
                lock(story, i, l)
    n_creature = sum(1 for sc in scenes for l in letters if creature and creature in (sc.get(PROMPT_KEYS[l]) or "").lower())
    if creature:
        log(f"Creature on screen: '{creature}' in {n_creature} shot(s) (AI only), hook shot "
            f"{'yes' if creature in (scenes[0].get(PROMPT_KEYS['a']) or '').lower() else 'NO'}")
    log(f"Key scenes {sorted(keys)}: AI shots with a real subject; locked shots: {', '.join(story.get('_ai_only', []))}")
    return {"rewritten": rewritten, "creature_shots": n_creature}
