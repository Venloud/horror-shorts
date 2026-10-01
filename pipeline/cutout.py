"""EXPERIMENTAL render style "cutout": the same character in every shot.

Characters are drawn ONCE as a pose set (Cloudflare FLUX, fixed seed, same description word-for-word, plain gray
background), checked for consistency against pose 1, cut out (rembg, chroma-key fallback) and composited onto
empty AI background plates (2-3 per location, reused so rooms stay the same). Object close-ups ("inserts") are
normal AI images; phone texts / notes / screens are drawn by code with only the words the narration says.

Switch: config "render_style" (classic | cutout), build.yml input render_style (env RENDER_STYLE), or config
"cutout_for_modes" (story modes). Anything failing here -> main.py logs it and renders the video in classic.

build() returns [[shot, ...], ...] per scene like images.generate_images(); a stage / screen shot is a preview
PNG with a `.cutout.json` spec next to it, which render.py animates with render_shot().
"""
import json
import math
import os
import random
import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from common import CONFIG, log

W, H, FPS = 1080, 1920, 30
POSES = {
    "standing_front": "standing, facing the viewer, full body",
    "walking_side": "walking, side view facing left, full body",
    "sitting": "sitting on a plain box, full body",
    "lying_in_bed": "lying down on his or her back, side view, full body",
    "holding_phone": "standing, holding a phone and looking down at it, full body",
    "scared_closeup": "scared face, head and shoulders close-up",
    "back_view": "seen from behind, back to the viewer, full body",
    "over_shoulder": "looking back over the shoulder, side view facing left, full body",
}
SIDE_POSES = {"walking_side", "over_shoulder", "lying_in_bed"}  # drawn facing left: flipped to face right
FALLBACK_POSE = {"walking_side": "standing_front", "sitting": "standing_front", "lying_in_bed": "",
                 "holding_phone": "standing_front", "scared_closeup": "standing_front",
                 "back_view": "standing_front", "over_shoulder": "back_view"}
PLATE_KINDS = {"wide": "wide establishing view", "medium": "medium view at eye level",
               "detail": "close detail view of one part of the place"}
ACTIONS = ("stand", "enter_left", "enter_right", "walk_across", "sit", "lie", "turn")
_CHILD = re.compile(r"\b(child|children|kid|kids|boy|girl|baby|toddler|teen\w*|\d{1,2}-year-old)\b", re.IGNORECASE)
_SCREEN_WORDS = re.compile(r"\b(text(?:ed|s)?|message\w*|call(?:ed|s|ing)?|voicemail|note|letter|screen|email|"
                           r"phone|dm|chat)\b", re.IGNORECASE)


class CutoutUnavailable(RuntimeError):
    """Cutout mode can't run for this video (no Cloudflare quota, nothing to draw...): render classic."""


# ---------------------------------------------------------------- switch

def style_for(story: dict) -> str:
    forced = (os.environ.get("RENDER_STYLE") or "").strip().lower()
    if forced in ("classic", "cutout"):
        return forced
    if story.get("mode") in (CONFIG.get("cutout_for_modes") or []):
        return "cutout"
    return "cutout" if CONFIG.get("render_style") == "cutout" else "classic"


def _style() -> str:
    return CONFIG.get("cutout_style") or ("flat 2D cartoon illustration, clean dark outlines, simple shading, "
                                          "muted night palette, no text")


# ---------------------------------------------------------------- plan

PLAN_PROMPT = """You plan the shots of a short vertical video made of: character cut-outs placed on background
plates ("stage"), object close-ups ("insert") and code-drawn screens ("screen").
Every shot must show EXACTLY what the narration says at that moment.

CHARACTERS (use these exact names; at most 2 may appear on stage): {characters}
LOCATIONS (use these exact names): {locations}
TRUE STORY: {true}

SCENES (narration, and the {n} shot(s) each scene gets, in order):
{scenes}

Return JSON: {{"scenes": [{{"shots": [SHOT, ...]}}, ...]}} with one entry per scene, {n} shots each (1 is fine for a
very short scene). SHOT is one of:
- {{"type": "stage", "character": "<name or none>", "pose": "<{poses}>", "location": "<location name>",
   "plate": "wide|medium|detail", "position": "left|center|right", "scale": "full|medium|close",
   "action": "<{actions}>", "facing": "left|right"}}
- {{"type": "insert", "prompt": "<object or detail close-up, no people, no signs/labels/inscriptions, max 15 words>",
   "location": "<name or none>"}}
- {{"type": "screen", "kind": "phone|note|laptop", "contact": "<name said in the narration, or empty>",
   "time": "<e.g. 11:47 PM>", "lines": [{{"from": "them|me", "text": "<words QUOTED from the narration>"}}]}}
RULES: adults only. A screen only when the narration mentions a text, message, call, note or screen, and its
lines use ONLY words the narration actually says (never invent messages). Never show a real victim's death, body
or remains: use the place or an object instead (stage with character "none", or an insert). "lie" only for a
living person in bed. character "none" = the empty place. Keep the same character in the same outfit.
"""


def plan(story: dict) -> list[list[dict]]:
    """Shots per scene. Gemini (Groq backup) plans; anything missing or invalid falls back to a keyword plan."""
    import images
    chars = _main_characters(story)
    locs = [l["name"] for l in story.get("locations") or [] if l.get("name")]
    n_shots = max(1, min(3, int(CONFIG.get("shots_per_scene", 2))))
    scenes_txt = "\n".join(f"{i}. {sc.get('narration', '')}" for i, sc in enumerate(story["scenes"]))
    prompt = PLAN_PROMPT.format(
        characters="; ".join(f"{c['name']}: {c.get('look', '')}" for c in chars) or "none",
        locations="; ".join(locs) or "none", true="yes" if story.get("true_story") else "no",
        n=n_shots, scenes=scenes_txt, poses="|".join(POSES), actions="|".join(ACTIONS))
    data = None
    try:
        data = images._gemini_json(prompt)
    except Exception as e:  # noqa: BLE001
        log(f"Cutout plan: LLM failed ({str(e)[:100]})")
    raw = (data or {}).get("scenes") if isinstance(data, dict) else None
    out = []
    for i, sc in enumerate(story["scenes"]):
        shots = []
        if isinstance(raw, list) and i < len(raw) and isinstance(raw[i], dict):
            shots = [s for s in (raw[i].get("shots") or [])[:3] if isinstance(s, dict)]
        shots = [v for v in (_valid(story, i, s, chars, locs) for s in shots) if v]
        if not shots:
            shots = _keyword_plan(story, i, chars, locs, n_shots)
        out.append(shots)
    log(f"Cutout plan: {sum(len(s) for s in out)} shots "
        f"({'LLM' if raw else 'keyword fallback'}): " +
        ", ".join(f"{i}:" + "/".join(s['type'][0] for s in shots) for i, shots in enumerate(out)))
    return out


_FIGURES = re.compile(r"\b(gravedigger|villager|priest|monk|nun|widow|farmer|old woman|old man|woman|man|"
                      r"hunter|soldier|watchman|innkeeper|traveler|traveller|stranger|figure|corpse|ghost|"
                      r"mourner|doctor|nurse|guard|sailor|fisherman|witch|creature)\b", re.IGNORECASE)


def derive_characters(story: dict) -> list[dict]:
    """A legend often has no character sheet. For cutout, up to 2 recurring ADULT figures the shots already show
    (e.g. "a gravedigger", "the shrouded corpse") get a fixed look: LLM first, a word count fallback. Only figures
    the image prompts actually name; never a child, never a real person's name."""
    import images
    prompts = " ".join(sc.get(k) or "" for sc in story.get("scenes") or []
                       for k in ("image_prompt", "image_prompt_2", "image_prompt_3", "image_prompt_4"))
    low = prompts.lower()
    out: list[dict] = []
    ans = None
    try:
        ans = images._gemini_json(
            "These are the image prompts of a short illustrated legend video. Name up to 2 recurring ADULT figures "
            "they show (not children, not real named people), using the words the prompts use, and give each a fixed "
            "look of 15-20 words (age, build, hair, clothing, era) that fits the story's setting: "
            f"{story.get('setting', '')}.\nPROMPTS: {prompts[:3000]}\n"
            'Return JSON {"characters": [{"name": "the gravedigger", "look": "..."}]}')
    except Exception:  # noqa: BLE001
        ans = None
    for c in (ans or {}).get("characters") or []:
        name, look = str(c.get("name", "")).strip(), str(c.get("look", "")).strip()
        key = name.lower().removeprefix("the ").removeprefix("a ").strip()
        if name and look and key and key.split()[-1] in low and not _CHILD.search(f"{name} {look}"):
            out.append({"name": key, "look": look})  # no article: shots are matched by the name's first word
    if not out:  # no LLM: the most frequent figure word in the shots
        counts: dict = {}
        for m in _FIGURES.finditer(prompts):
            w = m.group(1).lower()
            counts[w] = counts.get(w, 0) + 1
        for w, n in sorted(counts.items(), key=lambda x: -x[1])[:2]:
            if n >= 2:
                out.append({"name": w, "look": f"{w}, adult, plain period clothing fitting "
                                                       f"{(story.get('setting') or 'the story')[:60]}"})
    narration = " ".join(sc.get("narration", "") for sc in story.get("scenes") or []).lower()
    creature = str(story.get("case") or "").strip()
    if not out and story.get("mode") == "lore" and creature and creature.lower() in narration:
        # a legend whose shots show no figure at all: its own creature (+ one adult witness) becomes the cast
        try:
            ans = images._gemini_json(
                f"A short illustrated legend video about the {creature}. Give the {creature} ONE fixed look of 15-20 "
                "words exactly as the legend describes it (no gore, no blood, no occult symbols), and optionally ONE "
                "adult witness from the story (villager, gravedigger...) with a 15-20 word period look fitting "
                f"{story.get('setting', '')}.\nNARRATION: {narration[:2000]}\n"
                'Return JSON {"characters": [{"name": "' + creature.lower() + '", "look": "..."}, '
                '{"name": "villager", "look": "..."}]}') or {}
        except Exception:  # noqa: BLE001
            ans = {}
        for c in ans.get("characters") or []:
            name = str(c.get("name", "")).lower().removeprefix("the ").removeprefix("a ").strip()
            look = str(c.get("look", "")).strip()
            if name and look and not _CHILD.search(f"{name} {look}") and not re.search(
                    r"\b(blood|gore|gory|pentagram|occult|sigil)\b", look, re.I):
                out.append({"name": name, "look": look})
        for c in out:
            if c["name"] == creature.lower():  # how the narration refers to it in later scenes
                c["aliases"] = ["corpse", "creature", "revenant", "the dead", "body", "it"]
        if not out:
            out.append({"name": creature.lower(), "look": f"the {creature} of the legend, a pale gaunt figure in a "
                                                          "linen burial shroud, dark hollow eyes, no gore",
                        "aliases": ["corpse", "creature", "revenant", "the dead", "body", "it"]})
    if out:
        log("Cutout: no character sheet; derived cast: " + ", ".join(c["name"] for c in out[:2]))
    return out[:2]


def _main_characters(story: dict) -> list[dict]:
    """Up to 2 adult characters, the ones the image prompts / narration mention most."""
    text = " ".join(f"{sc.get('narration', '')} " + " ".join(sc.get(k) or "" for k in
                    ("image_prompt", "image_prompt_2", "image_prompt_3", "image_prompt_4"))
                    for sc in story.get("scenes") or []).lower()
    ok = [c for c in story.get("characters") or [] if c.get("name") and c.get("look")
          and not _CHILD.search(c.get("look", ""))]
    ok.sort(key=lambda c: -text.count(c["name"].lower().split()[0]))
    return ok[:2]


def _said(text: str, narration: str) -> bool:
    norm = lambda t: re.sub(r"[^a-z0-9 ]+", "", t.lower()).split()
    words, said = norm(text), " " + " ".join(norm(narration)) + " "
    return bool(words) and (" " + " ".join(words) + " ") in said


def _valid(story: dict, i: int, s: dict, chars: list[dict], locs: list[str]) -> dict | None:
    narr = story["scenes"][i].get("narration", "")
    kind = (s.get("type") or "").lower()
    names = {c["name"].lower(): c["name"] for c in chars}
    loc_names = {l.lower(): l for l in locs}
    if kind == "screen":
        lines = [l for l in s.get("lines") or [] if isinstance(l, dict) and _said(str(l.get("text", "")), narr)]
        if not _SCREEN_WORDS.search(narr):
            return None
        contact = str(s.get("contact") or "")
        contact = contact if contact and contact.lower() in narr.lower() else ""
        if not lines and not re.search(r"\bcall", narr, re.IGNORECASE):
            return None  # nothing the story actually says to show
        return {"type": "screen", "kind": s.get("kind") if s.get("kind") in ("phone", "note", "laptop") else "phone",
                "contact": contact, "time": str(s.get("time") or "11:47 PM")[:8],
                "lines": [{"from": "me" if l.get("from") == "me" else "them", "text": str(l["text"])[:140]}
                          for l in lines[:4]]}
    loc = loc_names.get(str(s.get("location") or "").lower(), "")
    if kind == "insert":
        p = re.sub(r"\s+", " ", str(s.get("prompt") or "")).strip()
        if not p:
            return None
        return {"type": "insert", "prompt": p[:160], "location": loc}
    if kind != "stage":
        return None
    who = names.get(str(s.get("character") or "").lower(), "")
    pose = s.get("pose") if s.get("pose") in POSES else "standing_front"
    action = s.get("action") if s.get("action") in ACTIONS else "stand"
    if story.get("true_story") and (pose == "lying_in_bed" or action == "lie") and _victim_moment(narr):
        who = ""  # never a real victim's death/body: the empty place instead
    if not loc:
        loc = _scene_location(story, i, locs)
    if not loc:
        return None
    return {"type": "stage", "character": who, "pose": pose, "location": loc,
            "plate": s.get("plate") if s.get("plate") in PLATE_KINDS else "wide",
            "position": s.get("position") if s.get("position") in ("left", "center", "right") else "center",
            "scale": s.get("scale") if s.get("scale") in ("full", "medium", "close") else "full",
            "action": action, "facing": "right" if s.get("facing") == "right" else "left"}


def _victim_moment(narr: str) -> bool:
    import images
    return bool(images._DEATH.search(narr))


def _scene_location(story: dict, i: int, locs: list[str]) -> str:
    sc = story["scenes"][i]
    for key in ("image_location", "location", "image_location_2"):
        v = (sc.get(key) or "").strip().lower()
        for l in locs:
            if v and l.lower() == v:
                return l
    return locs[0] if locs else ""


_POSE_WORDS = [("scared_closeup", r"scream|terrified|scared|afraid|horror|gasp|face"),
               ("holding_phone", r"phone|text|message|call|screen"),
               ("lying_in_bed", r"\bbed\b|asleep|sleep|lying|lay down"),
               ("sitting", r"\bsit|sat\b|seated|chair|desk|table"),
               ("walking_side", r"walk|runs?\b|ran\b|enter|arriv|step"),
               ("over_shoulder", r"looked back|over (?:his|her|their) shoulder|turned around"),
               ("back_view", r"walked away|leav|left the|disappear")]


def _keyword_plan(story: dict, i: int, chars: list[dict], locs: list[str], n: int) -> list[dict]:
    sc = story["scenes"][i]
    narr = sc.get("narration", "")
    out = []
    for k in ("image_prompt", "image_prompt_2", "image_prompt_3")[:n]:
        shot = (sc.get(k) or "").strip() or narr
        who = next((c["name"] for c in chars if c["name"].lower().split()[0] in shot.lower()), "")
        if not who and not out:  # the scene's first shot: a character the NARRATION names (a legend's creature)
            nl = narr.lower()
            who = next((c["name"] for c in chars if any(re.search(rf"\b{re.escape(a)}\b", nl) for a in
                                                         [c["name"].lower().split()[0]] + c.get("aliases", []))), "")
        loc = _scene_location(story, i, locs)
        if who and loc:
            pose = next((p for p, rx in _POSE_WORDS if re.search(rx, shot + " " + narr, re.IGNORECASE)),
                        "standing_front")
            action = {"walking_side": "walk_across", "sitting": "sit", "lying_in_bed": "lie"}.get(pose, "stand")
            out.append(_valid(story, i, {"type": "stage", "character": who, "pose": pose, "location": loc,
                                         "plate": "medium" if out else "wide",
                                         "position": ["center", "left", "right"][len(out) % 3],
                                         "scale": "close" if pose == "scared_closeup" else "full",
                                         "action": action}, chars, locs))
        elif re.search(r"close-up|close up|detail", shot, re.IGNORECASE) or not loc:
            out.append({"type": "insert", "prompt": re.sub(r"\s+", " ", shot)[:160], "location": loc})
        else:
            out.append({"type": "stage", "character": "", "pose": "standing_front", "location": loc,
                        "plate": "wide" if not out else "detail", "position": "center", "scale": "full",
                        "action": "stand", "facing": "left"})
    return [o for o in out if o] or [{"type": "insert", "prompt": narr[:160], "location": ""}]


# ---------------------------------------------------------------- assets

class Budget:
    def __init__(self, target: int, hard: int):
        self.target, self.hard, self.used = target, hard, 0

    def take(self, planned: bool = True) -> bool:
        limit = self.target if planned else self.hard
        if self.used >= limit:
            return False
        self.used += 1
        return True


def _draw(prompt: str, seed: int, path: Path, budget: Budget, planned: bool = True) -> Path | None:
    import images
    if not budget.take(planned):
        log(f"Cutout: Cloudflare budget used ({budget.used}), skipping {path.name}")
        return None
    raw = images._cloudflare(prompt, seed, fixed_seed=True)
    images._save_valid(raw, path)
    return path


def _qa(path: Path, request: str) -> tuple[bool | None, str]:
    import images
    return images.check_image(path, request)


def make_poses(story: dict, chars: list[dict], needed: dict, outdir: Path, budget: Budget) -> dict:
    """{name: {pose: cutout PNG}}. Pose 1 (standing front) is the reference; every other pose is checked against
    it (same person / outfit / style), regenerated up to 2 times, else dropped."""
    import images
    style = _style()
    out: dict = {}
    for ci, c in enumerate(chars):
        want = ["standing_front"] + [p for p in POSES if p in needed.get(c["name"], set()) and p != "standing_front"]
        seed = 1000 + 7919 * (ci + 1) + int.from_bytes(c["name"].encode()[:4].ljust(4, b"_"), "big") % 9973
        got: dict = {}
        for pose in want:
            dest = outdir / f"pose_{ci}_{pose}.png"
            cut = dest.with_suffix(".cut.png")
            if cut.exists():  # resumed build
                got[pose] = cut
                continue
            ok = False
            for attempt in range(3):
                frame = "head and shoulders, centered" if pose == "scared_closeup" else "full body, centered"
                prompt = (f"{style}, {c['look'].strip().rstrip('.')}, adult, {POSES[pose]}, {frame}, "
                          f"plain flat light-gray background, even lighting, single character, no text")
                if not _draw(prompt, seed + attempt * 101, dest, budget, planned=attempt == 0):
                    break
                v, why = _qa(dest, f"one adult person, {POSES[pose]}, plain light-gray background")
                if v is False:
                    log(f"Cutout pose {c['name']}/{pose}: QA NO ({why}), try {attempt + 1}/3")
                    continue
                if pose != "standing_front" and "standing_front" in got:
                    same, why = images.same_character(outdir / f"pose_{ci}_standing_front.png", dest)
                    log(f"Cutout pose {c['name']}/{pose}: same person as pose 1? "
                        f"{'YES' if same else 'NO' if same is False else 'unchecked'}" + (f" ({why})" if why else ""))
                    if same is False:
                        continue
                ok = True
                break
            if not ok:
                if pose == "standing_front":
                    log(f"Cutout: no usable reference pose for {c['name']}; the character is left out")
                    break
                log(f"Cutout pose {c['name']}/{pose}: dropped (uses {FALLBACK_POSE.get(pose) or 'no pose'})")
                continue
            try:
                got[pose] = cut_out(dest, cut)
            except ValueError as e:
                log(f"Cutout pose {c['name']}/{pose}: {e}; dropped")
                if pose == "standing_front":
                    break
        if got:
            out[c["name"]] = got
    return out


def cut_out(src: Path, dest: Path) -> Path:
    """Character on transparent background: rembg (isnet-anime, then u2net), else a gray-background key.
    Alpha edge cleaned (1 px erode + feather), cropped to the character."""
    im = Image.open(src).convert("RGB")
    alpha = None
    try:
        from rembg import new_session, remove
        for model in ("isnet-anime", "u2net"):
            try:
                sess = _SESS.get(model) or new_session(model)
                _SESS[model] = sess
                alpha = remove(im, session=sess, only_mask=True)
                break
            except Exception as e:  # noqa: BLE001
                log(f"Cutout: rembg {model} failed ({str(e)[:80]})")
    except ImportError:
        pass
    if alpha is not None and not _mask_ok(alpha):
        log(f"Cutout: rembg mask for {src.name} is weak (semi-transparent figure); using the gray-background key")
        alpha = None
    if alpha is None:
        alpha = _key_gray(im)
        if not _mask_ok(alpha):
            raise ValueError(f"cut-out of {src.name}: no clean mask (rembg and the gray key both weak)")
    alpha = alpha.convert("L").filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(1.2))
    rgba = im.copy()
    rgba.putalpha(alpha)
    box = alpha.point(lambda v: 255 if v > 40 else 0).getbbox()
    if not box or (box[2] - box[0]) < im.width * 0.08 or (box[3] - box[1]) < im.height * 0.2:
        raise ValueError(f"cut-out of {src.name} is nearly empty ({box})")  # the pose is dropped, never a sliver
    rgba.crop(box).save(dest)
    return dest


_SESS: dict = {}


def _mask_ok(mask: Image.Image) -> bool:
    """A usable cut-out mask is decisive (almost every pixel clearly in or out) and the figure is neither a
    sliver nor the whole frame. rembg sometimes returns a uniformly weak mask: a ghost-like, see-through figure."""
    import numpy as np
    a = np.asarray(mask.convert("L"), dtype="float32")
    fg = (a > 128).mean()
    decisive = ((a > 200) | (a < 40)).mean()
    return decisive > 0.9 and 0.02 < fg < 0.9


def _key_gray(im: Image.Image) -> Image.Image:
    """No rembg: flood-fill the plain light-gray background from the borders."""
    marker = (255, 0, 255)
    work = im.copy()
    w, h = work.size
    for xy in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1), (w // 2, 0), (w // 2, h - 1), (0, h // 2),
               (w - 1, h // 2)]:
        if work.getpixel(xy) != marker:
            ImageDraw.floodfill(work, xy, marker, thresh=38)
    import numpy as np
    arr = np.asarray(work)
    mask = ~((arr[..., 0] == 255) & (arr[..., 1] == 0) & (arr[..., 2] == 255))
    return Image.fromarray((mask * 255).astype("uint8"), "L")


def make_plates(story: dict, needed: set, outdir: Path, budget: Budget) -> dict:
    """{(location, kind): PNG}. Empty places, same description word-for-word, reused across scenes."""
    style = _style()
    looks = {l["name"]: l.get("look", "") for l in story.get("locations") or []}
    out = {}
    order = sorted(needed, key=lambda lk: (list(PLATE_KINDS).index(lk[1]), lk[0]))  # every wide plate first
    for li, (loc, kind) in enumerate(order):
        dest = outdir / f"plate_{re.sub(r'[^a-z0-9]+', '_', loc.lower())}_{kind}.png"
        if dest.exists():
            out[(loc, kind)] = dest
            continue
        prompt = (f"{style}, {looks.get(loc, loc).strip().rstrip('.')}, {PLATE_KINDS[kind]}, empty, no people, "
                  f"vertical composition, blank unmarked surfaces, no text, no signs")
        for attempt in range(2):
            if not _draw(prompt, 5000 + li * 37 + attempt, dest, budget, planned=attempt == 0):
                break
            v, why = _qa(dest, f"{loc}: {looks.get(loc, '')}, empty, no people; NO if any letters, words or writing are visible")
            if v is not False:
                out[(loc, kind)] = dest
                break
            log(f"Cutout plate {loc}/{kind}: QA NO ({why})")
            dest.rename(dest.with_suffix(f".rejected{attempt}.png"))
    return out


def make_insert(story: dict, i: int, shot: dict, dest: Path, budget: Budget) -> Path | None:
    looks = {l["name"]: l.get("look", "") for l in story.get("locations") or []}
    place = " ".join(looks.get(shot.get("location") or "", "").split()[:10])
    import images
    # garbled AI lettering ("Herteellienn" sign, "Lanes" tombstone in build 36848613329): no text requests at all,
    # blank surfaces, and QA fails any visible letters
    prompt = (f"{_style()}, {images._no_text(shot['prompt'])}" + (f", {place}" if place else "")
              + ", close-up, no people, blank unmarked surfaces, no letters, no signs, no text")
    for attempt in range(2):
        if not _draw(prompt, 9000 + i * 11 + attempt, dest, budget, planned=attempt == 0):
            return None
        v, why = _qa(dest, f"{shot['prompt']}; NO if any letters, words or writing are visible")
        if v is not False:
            return dest
        log(f"Cutout insert {dest.name}: QA NO ({why})")
        dest.unlink(missing_ok=True)
    return None


# ---------------------------------------------------------------- screens (drawn by code)

def _font(size: int, bold: bool = False, serif: bool = False) -> ImageFont.FreeTypeFont:
    name = ("DejaVuSerif" if serif else "DejaVuSans") + ("-Bold" if bold else "") + ".ttf"
    for d in ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu"):
        p = Path(d) / name
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default(size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> list[str]:
    lines, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=font) <= width:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    return lines + ([cur] if cur else [])


def draw_screen(shot: dict, dest: Path, backdrop: Path | None = None) -> Path:
    """Dark-mode phone chat / handwritten note / laptop line, 1080x1920. Only the narration's own words."""
    if backdrop and backdrop.exists():
        bg = ImageOps.fit(Image.open(backdrop).convert("RGB"), (W, H)).filter(ImageFilter.GaussianBlur(18))
        bg = ImageEnhance.Brightness(bg).enhance(0.35)
    else:
        bg = Image.new("RGB", (W, H), (14, 16, 22))
    d = ImageDraw.Draw(bg)
    kind = shot.get("kind", "phone")
    lines = shot.get("lines") or []
    if kind == "note":
        paper = Image.new("RGB", (820, 1000), (236, 228, 205))
        pd = ImageDraw.Draw(paper)
        for y in range(120, 1000, 64):
            pd.line([(40, y), (780, y)], fill=(170, 190, 215), width=2)
        f = _font(54, serif=True)
        y = 70
        for l in lines or [{"text": ""}]:
            for row in _wrap(pd, l["text"], f, 700):
                pd.text((70, y), row, font=f, fill=(35, 32, 60))
                y += 64
        paper = paper.convert("RGBA").rotate(-4, expand=True, resample=Image.BICUBIC)  # a slightly tilted sheet
        x0, y0 = (W - paper.width) // 2, (H - paper.height) // 2
        shadow = paper.getchannel("A").point(lambda v: int(v * 0.6)).filter(ImageFilter.GaussianBlur(20))
        bg.paste((0, 0, 0), (x0 + 18, y0 + 24), shadow)
        bg.paste(paper, (x0, y0), paper)
    elif kind == "laptop":
        d.rounded_rectangle([90, 560, 990, 1180], 28, fill=(28, 30, 36))
        d.rectangle([130, 600, 950, 1140], fill=(8, 10, 14))
        d.polygon([(40, 1180), (1040, 1180), (1000, 1250), (80, 1250)], fill=(40, 42, 50))
        f = _font(46, serif=False)
        y = 660
        for l in lines or [{"text": ""}]:
            for row in _wrap(d, l["text"], f, 740):
                d.text((170, y), row, font=f, fill=(210, 225, 215))
                y += 62
        d.rectangle([170, y + 8, 196, y + 52], fill=(210, 225, 215))  # cursor
    else:  # phone
        x0, y0, x1, y1 = 150, 160, 930, 1760
        d.rounded_rectangle([x0 - 14, y0 - 14, x1 + 14, y1 + 14], 90, fill=(40, 40, 46))
        d.rounded_rectangle([x0, y0, x1, y1], 78, fill=(11, 11, 15))
        sf = _font(34, bold=True)
        d.text((x0 + 60, y0 + 34), shot.get("time", "11:47 PM"), font=sf, fill=(235, 235, 240))
        d.rounded_rectangle([x1 - 120, y0 + 42, x1 - 64, y0 + 66], 6, outline=(235, 235, 240), width=3)
        d.rectangle([x1 - 116, y0 + 46, x1 - 84, y0 + 62], fill=(235, 235, 240))
        cy = y0 + 170
        d.line([(x0, cy + 120), (x1, cy + 120)], fill=(40, 40, 48), width=2)
        d.ellipse([W // 2 - 50, cy - 40, W // 2 + 50, cy + 60], fill=(70, 72, 84))
        name = shot.get("contact") or ""
        d.text((W // 2, cy + 10), (name[:1] or "?").upper(), font=_font(52, bold=True), fill=(230, 230, 236),
               anchor="mm")
        if name:
            d.text((W // 2, cy + 92), name, font=_font(36, bold=True), fill=(230, 230, 236), anchor="mm")
        f = _font(44)
        y = cy + 190
        if not lines:  # a call the narration mentions, no words to quote
            d.text((W // 2, y + 300), "Incoming call", font=_font(52, bold=True), fill=(230, 230, 236), anchor="mm")
            d.ellipse([W // 2 - 70, y + 700, W // 2 + 70, y + 840], fill=(52, 199, 89))
        for l in lines:
            rows = _wrap(d, l["text"], f, 520)
            bw = max(d.textlength(r, font=f) for r in rows) + 64
            bh = len(rows) * 58 + 40
            me = l.get("from") == "me"
            bx = x1 - 40 - bw if me else x0 + 40
            d.rounded_rectangle([bx, y, bx + bw, y + bh], 36, fill=(10, 132, 255) if me else (48, 48, 56))
            for k, r in enumerate(rows):
                d.text((bx + 32, y + 20 + k * 58), r, font=f, fill=(255, 255, 255))
            y += bh + 28
    bg.save(dest)
    return dest


# ---------------------------------------------------------------- build

def build(story: dict, img_dir: Path, workdir: Path) -> list[list[Path]]:
    """All cutout assets for this story + one preview PNG and `.cutout.json` spec per shot."""
    import images
    if not os.environ.get("CLOUDFLARE_API_TOKEN"):
        raise CutoutUnavailable("no Cloudflare token")
    if images.cloudflare_has_quota() is False or images._STATE.get("cf_out"):
        raise CutoutUnavailable("Cloudflare daily limit used up")
    out = img_dir / "cutout"
    out.mkdir(parents=True, exist_ok=True)
    images.sanitize_victim_shots(story)
    if not _main_characters(story):  # legends: no character sheet -> the recurring figures of the shots
        derived = derive_characters(story)
        if derived:
            story["characters"] = list(story.get("characters") or []) + derived
    shots = plan(story)
    chars = _main_characters(story)
    budget = Budget(int(CONFIG.get("cutout_max_images", 22)), int(CONFIG.get("cutout_hard_max_images", 26)))

    needed_poses: dict = {}
    plates_needed: set = set()
    for sc in shots:
        for s in sc:
            if s["type"] == "stage":
                plates_needed.add((s["location"], s["plate"]))
                if s["character"]:
                    needed_poses.setdefault(s["character"], set()).add(s["pose"])
    n_pose = sum(1 + len(p - {"standing_front"}) for p in needed_poses.values())
    n_ins = sum(1 for sc in shots for s in sc if s["type"] == "insert")
    if n_pose + len(plates_needed) + n_ins > budget.target:  # over budget: wide plates only
        plates_needed = {(l, "wide") for l, _k in plates_needed}
        for sc in shots:
            for s in sc:
                if s["type"] == "stage":
                    s["plate"] = "wide"
    log(f"Cutout budget: {n_pose} poses + {len(plates_needed)} plates + {n_ins} inserts "
        f"(target {budget.target} Cloudflare images)")
    # sizes planned: poses first (the whole point), then plates, then inserts
    poses = make_poses(story, [c for c in chars if c["name"] in needed_poses], needed_poses, out, budget)
    plates = make_plates(story, plates_needed, out, budget)
    if not plates:
        raise CutoutUnavailable("no background plate could be made")
    sheet([(p, f"{who.split()[0]}: {pose}") for who, d in poses.items() for pose, p in sorted(d.items())],
          workdir / "poses_sheet.png", "poses")
    sheet([(p, f"{loc[:18]} / {kind}") for (loc, kind), p in sorted(plates.items())],
          workdir / "plates_sheet.png", "plates")
    fallbacks: list[str] = []
    empty_used: set = set()

    per_scene: list[list[Path]] = []
    for i, sc in enumerate(shots):
        row = []
        for k, s in enumerate(sc):
            tag = f"scene_{i:02d}{'abcd'[k]}"
            png = out / f"{tag}.png"
            spec_path = png.with_suffix(".cutout.json")
            if s["type"] == "insert":
                got = png if png.exists() else make_insert(story, i, s, png, budget)
                if got:
                    row.append(got)
                    continue
                fallbacks.append(f"{tag}: insert '{s.get('prompt', '')[:40]}' could not be drawn -> empty plate")
                loc = s.get("location") or _scene_location(story, i, [l for l, _ in plates])
                s = {"type": "stage", "character": "", "location": loc, "plate": "wide", "pose": "standing_front",
                     "position": "center", "scale": "full", "action": "stand", "facing": "left"}
            if s["type"] == "screen":
                plate = next((p for (l, _k), p in plates.items() if l == _scene_location(story, i, list(
                    {l for l, _ in plates}))), None)
                draw_screen(s, png, plate)
                spec = {"type": "screen", "image": str(png)}
            else:
                plate = plates.get((s["location"], s["plate"])) or next(
                    (p for (l, _k), p in plates.items() if l == s["location"]), None) or next(iter(plates.values()))
                if not s.get("character"):  # an empty plate twice = the same picture twice: take an unused plate
                    if plate in empty_used:
                        alt = next((p for (l, _k), p in plates.items() if l == s["location"] and p not in empty_used),
                                   None) or next((p for p in plates.values() if p not in empty_used), None)
                        if alt:
                            fallbacks.append(f"{tag}: empty plate {Path(plate).stem} already shown -> {Path(alt).stem}")
                            plate = alt
                    empty_used.add(plate)
                pose_png = None
                who = s.get("character")
                if who in poses:
                    pose = s["pose"]
                    while pose and pose not in poses[who]:
                        pose = FALLBACK_POSE.get(pose, "")
                    pose_png = poses[who].get(pose) if pose else None
                    if pose and pose != s["pose"]:
                        log(f"Cutout {tag}: pose {s['pose']} missing, using {pose}")
                        fallbacks.append(f"{tag}: {who} pose {s['pose']} missing -> {pose}")
                        s["pose"] = pose
                spec = {"type": "stage", "plate": str(plate), "pose": str(pose_png) if pose_png else "",
                        "pose_name": s["pose"], "position": s["position"], "scale": s["scale"],
                        "action": s["action"], "facing": s["facing"]}
                preview(spec, png)
            spec_path.write_text(json.dumps(spec, indent=1))
            row.append(png)
        per_scene.append(row)
    story["render_style"] = "cutout"
    story["cutout"] = {"cloudflare_images": budget.used, "characters": list(poses),
                       "poses": {k: sorted(v) for k, v in poses.items()},
                       "plates": [f"{l}/{k}" for l, k in plates], "shots": shots, "fallbacks": fallbacks,
                       "counts": {t: sum(1 for sc in shots for x in sc if x["type"] == t)
                                  for t in ("stage", "insert", "screen")}}
    log(f"Cutout: {budget.used} Cloudflare images; {sum(len(v) for v in poses.values())} poses, "
        f"{len(plates)} plates; {sum(len(r) for r in per_scene)} shots")
    return per_scene


# ---------------------------------------------------------------- compositor

def spec_for(img: Path) -> dict | None:
    p = Path(img).with_suffix(".cutout.json")
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except ValueError:
        return None


class _Stage:
    """Prepared layers of one stage shot (graded once; per frame only crop / scale / paste)."""

    def __init__(self, spec: dict):
        self.spec = spec
        plate = ImageOps.fit(Image.open(spec.get("plate") or spec.get("image")).convert("RGB"),
                             (int(W * 1.12), int(H * 1.12)), Image.LANCZOS)
        if spec["type"] == "stage":
            plate = ImageEnhance.Brightness(plate).enhance(0.8)
            plate = ImageEnhance.Color(plate).enhance(0.8)
        self.bg = plate
        self.char = None
        if spec.get("pose"):
            ch = Image.open(spec["pose"]).convert("RGBA")
            if spec.get("pose_name") in SIDE_POSES and spec.get("facing") == "right":
                ch = ImageOps.mirror(ch)
            self.char = self._grade(ch, plate)
            self.char_flip = ImageOps.mirror(self.char)

    @staticmethod
    def _grade(ch: Image.Image, plate: Image.Image) -> Image.Image:
        rgb, a = ch.convert("RGB"), ch.getchannel("A")
        rgb = ImageEnhance.Brightness(rgb).enhance(1.07)
        rgb = ImageEnhance.Color(rgb).enhance(1.08)
        mean = plate.resize((1, 1), Image.BOX).getpixel((0, 0))
        rgb = Image.blend(rgb, Image.new("RGB", rgb.size, mean), 0.10)  # a little of the room's light
        from PIL import ImageChops
        rim = ImageChops.subtract(a, a.filter(ImageFilter.MinFilter(9))).filter(ImageFilter.GaussianBlur(3))
        light = tuple(min(255, int(c * 1.6) + 40) for c in mean)
        rgb = Image.composite(Image.new("RGB", rgb.size, light), rgb, rim.point(lambda v: int(v * 0.35)))
        out = rgb.convert("RGBA")
        out.putalpha(a)
        return out

    def frame(self, t: float, length: float) -> Image.Image:
        u = t / max(length, 0.01)
        z = 1.0 + 0.05 * u  # slow push-in on the background
        bw, bh = self.bg.size
        cw, chh = bw / z / 1.12, bh / z / 1.12
        cx = bw / 2 + (bw - cw) * 0.1 * (u - 0.5)
        box = (cx - cw / 2, bh / 2 - chh / 2, cx + cw / 2, bh / 2 + chh / 2)
        img = self.bg.resize((W, H), Image.BILINEAR, box=box)
        if self.char is None:
            return img
        s = self.spec
        close = s.get("pose_name") == "scared_closeup"
        height = {"full": 0.60, "medium": 1.10, "close": 1.55}[s.get("scale", "full")] * H
        feet = {"full": 0.90, "medium": 1.42, "close": 1.95}[s.get("scale", "full")] * H
        if close:
            height, feet = 0.66 * H, H + 4
        if s.get("pose_name") == "lying_in_bed":
            height, feet = 0.30 * H, 0.86 * H
        breath = 1 + 0.012 * math.sin(2 * math.pi * t / 3.2)
        ch = self.char
        if s.get("action") == "turn" and u > 0.5:
            ch = self.char_flip
        scale = height * breath / max(ch.height, 1)
        cw2, ch2 = max(2, min(int(ch.width * scale), 3 * W)), max(2, int(ch.height * scale))  # never a runaway sprite
        sprite = ch.resize((cw2, ch2), Image.BILINEAR)
        target = {"left": 0.3, "center": 0.5, "right": 0.7}[s.get("position", "center")] * W
        act = s.get("action", "stand")
        x = target
        bob = 0.0
        if act in ("enter_left", "enter_right"):
            k = min(1.0, u / 0.45)
            k = 1 - (1 - k) ** 3
            start = -0.3 * W if act == "enter_left" else 1.3 * W
            x = start + (target - start) * k
            bob = 10 * abs(math.sin(2 * math.pi * t * 1.7)) * (1 - k)
        elif act == "walk_across":
            a, b = (0.12 * W, 0.88 * W) if s.get("facing") == "right" else (0.88 * W, 0.12 * W)
            x = a + (b - a) * u
            bob = 10 * abs(math.sin(2 * math.pi * t * 1.7))
        top = feet - ch2 - bob
        left = x - cw2 / 2
        if not close and s.get("scale", "full") == "full":  # soft contact shadow under the feet
            sh = Image.new("L", (int(cw2 * 1.2), 70), 0)
            ImageDraw.Draw(sh).ellipse([0, 10, sh.width, 60], fill=120)
            sh = sh.filter(ImageFilter.GaussianBlur(14))
            img.paste((0, 0, 0), (int(x - sh.width / 2), int(feet - 38)), sh)
        img.paste(sprite, (int(left), int(top)), sprite)
        return img


def preview(spec: dict, dest: Path) -> Path:
    _Stage(spec).frame(0.0, 1.0).save(dest)
    return dest


def render_shot(spec: dict, length: float, out: Path) -> Path:
    """One animated shot (stage or screen) straight into a 1080x1920 / 30 fps mp4."""
    stage = _Stage(spec)
    n = max(2, int(round(length * FPS)))
    p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                          "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-frames:v", str(n), "-c:v", "libx264",
                          "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p", str(out)],
                         stdin=subprocess.PIPE)
    try:
        for k in range(n):
            p.stdin.write(stage.frame(k / FPS, length).tobytes())
    finally:
        p.stdin.close()
        p.wait()
    if p.returncode:
        raise RuntimeError(f"cutout shot encode failed ({p.returncode})")
    return out


# ---------------------------------------------------------------- review sheets

def sheet(paths: list, dest: Path, title: str, cols: int = 4, cell: tuple = (270, 480)) -> Path | None:
    """paths: Path or (Path, label) items; each cell is labelled (default: the file name)."""
    items = [(Path(p[0]), p[1]) if isinstance(p, tuple) else (Path(p), Path(p).stem[:34]) for p in paths]
    items = [(p, lab) for p, lab in items if p.exists()]
    paths = [p for p, _ in items]
    labels = [lab for _, lab in items]
    if not paths:
        return None
    rows = math.ceil(len(paths) / cols)
    im = Image.new("RGB", (cols * cell[0], rows * (cell[1] + 40)), (30, 30, 34))
    d = ImageDraw.Draw(im)
    f = _font(20)
    for k, p in enumerate(paths):
        src = Image.open(p)
        if src.mode == "RGBA":  # cut-outs on a checker so the edge quality is visible
            bgc = Image.new("RGB", src.size, (120, 120, 120))
            bgc.paste(src, (0, 0), src)
            src = bgc
        t = ImageOps.contain(src.convert("RGB"), cell)
        x, y = (k % cols) * cell[0], (k // cols) * (cell[1] + 40)
        im.paste(t, (x + (cell[0] - t.width) // 2, y))
        d.text((x + 6, y + cell[1] + 8), labels[k][:30], font=f, fill=(220, 220, 220))
    im.save(dest)
    log(f"Review sheet: {dest.name} ({len(paths)} {title})")
    return dest


def contact_sheet(video: Path, dest: Path, every: float = 2.0) -> Path | None:
    """One frame per 2 s of the finished video in a grid (for the owner's review)."""
    tmp = dest.parent / "_contact"
    tmp.mkdir(exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-vf", f"fps=1/{every},scale=216:384",
                    str(tmp / "f_%03d.png")], check=False)
    frames = sorted(tmp.glob("f_*.png"))
    out = sheet(frames, dest, "frames", cols=8, cell=(216, 384))
    for f in frames:
        f.unlink()
    tmp.rmdir()
    return out
