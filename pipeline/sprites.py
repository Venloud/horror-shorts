"""The Night Files host: ONLY the owner-approved artwork listed in assets/character/host/manifest.json ("approved"):
M01-M04 full body (front / three_quarter / side / back) and M05 + F01-F22 head-and-shoulders expressions.

Never generated, redrawn, recoloured or substituted, and no procedural fallback: a missing file, a file whose
SHA-256 no longer matches the manifest, or an ID that isn't approved raises MissingAsset naming the asset ID.
Placement only: resize, mirror for a left-facing side / three-quarter view, crop of transparent padding. The red
aura stays exactly as approved (the compositor adds light on the PLATE behind the figure, never on it).

The storyboard picks a mood and a view; body_id() / face_id() turn them into asset IDs:
  view -> M01-M04, mood -> F01-F22 (F16 shocked has an opaque black background: until a transparent re-export
  passes usable(), "shocked" uses F15 scared).
"""
import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageOps

from common import ROOT

DIR = ROOT / "assets" / "character" / "host"

VIEWS = ("front", "three_quarter", "side", "back")
BODY = {"front": "M01", "three_quarter": "M02", "side": "M03", "back": "M04"}
FACES = {
    "neutral": "F01", "talking": "F02", "smiling": "F03", "happy": "F03", "laughing": "F04", "excited": "F05",
    "smirk": "F06", "confident": "F07", "serious": "F08", "curious": "F09", "confused": "F10", "skeptical": "F11",
    "suspicious": "F12", "thinking": "F13", "worried": "F14", "scared": "F15", "shocked": "F16", "sad": "F17",
    "angry": "F18", "determined": "F19", "frustrated": "F20", "relieved": "F21", "tired": "F22",
}
FACE_FALLBACK = {"F16": "F15"}  # unusable (opaque) -> nearest approved expression
# Until the P-series action poses are approved, every action is shown with an approved M-view; the action only
# decides the view (walking away = back, crossing = side). The planner may still name these beats.
ACTIONS = {"standing": None, "observing": "three_quarter", "thinking": "front", "presenting": "front",
           "waiting": "front", "reacting": "front", "scared": "front", "inspecting": "three_quarter",
           "holding": "front", "turning": "side", "walking": "side", "sneaking": "side", "leaving": "back",
           "watching": "back"}
EXPRESSIONS = tuple(FACES)


class MissingAsset(RuntimeError):
    """An approved character asset is missing or changed: the build fails by asset ID, never substitutes."""

    def __init__(self, asset_id: str, why: str):
        super().__init__(f"Approved character asset {asset_id} {why}")
        self.asset_id = asset_id


@lru_cache(maxsize=1)
def approved_registry() -> dict:
    p = DIR / "manifest.json"
    if not p.is_file():
        return {"approved": []}
    return json.loads(p.read_text(encoding="utf-8"))


def _record(asset_id: str) -> dict | None:
    return next((r for r in approved_registry().get("approved", [])
                 if r.get("id") == asset_id and r.get("status") == "approved"), None)


@lru_cache(maxsize=64)
def asset_path(asset_id: str) -> Path:
    """The approved file for an ID, its bytes checked against the manifest's SHA-256. Raises MissingAsset."""
    rec = _record(asset_id)
    if rec is None:
        raise MissingAsset(asset_id, "is not in the approved manifest")
    p = DIR / rec["path"]
    if not p.is_file():
        raise MissingAsset(asset_id, f"is missing ({rec['path']})")
    if rec.get("sha256") and hashlib.sha256(p.read_bytes()).hexdigest() != rec["sha256"]:
        raise MissingAsset(asset_id, f"was changed: SHA-256 differs from the manifest ({rec['path']})")
    return p


def _approved_path(asset_id: str):
    """Old name (tools/night_files_visual_preview.py): the path, or None instead of raising."""
    try:
        return asset_path(asset_id)
    except MissingAsset:
        return None


@lru_cache(maxsize=64)
def usable(asset_id: str) -> bool:
    """Approved, unchanged AND a real cut-out (transparent corner). F16's opaque black square is not usable."""
    try:
        with Image.open(asset_path(asset_id)) as im:
            return im.mode == "RGBA" and im.getpixel((2, 2))[3] == 0
    except MissingAsset:
        return False


def body_id(view: str) -> str:
    return BODY.get(view, "M01")


def face_id(mood: str) -> str:
    aid = FACES.get(mood, "F01")
    if not usable(aid) and aid in FACE_FALLBACK:
        return FACE_FALLBACK[aid]
    return aid



def select_for_beat(narration: str, mood: str = "neutral", allow_poses: bool | None = None) -> str:
    """Choose among existing checksum-verified owner-approved faces/poses for a generic story beat.

    CLIP is optional and conservative. New action poses are candidates ONLY once in the approved
    manifest. No image generation, new art or story-specific conditional is permitted.
    """
    fallback = face_id(mood)
    if not narration.strip():
        return fallback
    approved = approved_registry().get("approved", [])
    choice = bool(re.search(
        r"\b(choos\w*|decid\w*|option|either|which|two choices|left or right)\b",
        narration, re.I)) if allow_poses is None else bool(allow_poses)
    # allow_poses: the editor's grounded choice detection (explainer.choice_options) overrides the keyword match,
    # so "isn't always an option" never gets the open-palms choice pose
    # A small semantic set keeps the CPU pass bounded. Reuse the approved registry, never guess paths.
    useful_faces = {"F01", "F07", "F09", "F10", "F11", "F12", "F13", "F14", "F15", "F19", "F21"}
    ids = [r["id"] for r in approved if r.get("status") == "approved"
           and (r["id"] in useful_faces or r["id"] == fallback
                or (choice and r["id"].startswith("P")))]
    if fallback not in ids:
        ids.insert(0, fallback)
    try:
        import library
        intent = ("A person with open hands showing two choices, choosing between options. "
                  if choice else "The person reacts to the scene. ") + narration[:170]
        return library.best_approved_asset(intent, ids, fallback)
    except Exception:  # optional local model must never stop rendering or compromise the approved set
        return fallback


def approved_image(asset_id: str) -> Image.Image:
    """A transparent approved sprite, verified against its manifest, returned without changing the source."""
    if not usable(asset_id):
        raise MissingAsset(asset_id, "is not an approved transparent asset")
    return _trimmed(asset_id).copy()


def view_for(action: str, view: str) -> str:
    return ACTIONS.get(action) or (view if view in VIEWS else "front")


def verify_all() -> list[str]:
    """Every approved ID: present + unchanged. The list of problems (empty = all good)."""
    out = []
    for rec in approved_registry().get("approved", []):
        try:
            asset_path(rec["id"])
        except MissingAsset as e:
            out.append(str(e))
    return out


def require_all() -> None:
    """Raise MissingAsset for the first approved ID that is missing or changed (checked before every render)."""
    for rec in approved_registry().get("approved", []):
        asset_path(rec["id"])


@lru_cache(maxsize=40)
def _trimmed(asset_id: str) -> Image.Image:
    im = Image.open(asset_path(asset_id)).convert("RGBA")
    box = im.getchannel("A").getbbox()
    return im.crop(box) if box else im


@lru_cache(maxsize=40)
def full_body(view: str = "front", height: int = 900, facing: str = "right"):
    """(RGBA, (foot_x, foot_y)) of the approved M-view, scaled to `height` for placement only. Raises MissingAsset."""
    im = _trimmed(body_id(view))
    height = max(200, int(height))
    im = im.resize((max(1, round(im.width * height / im.height)), height), Image.Resampling.LANCZOS)
    if facing == "left" and view in ("three_quarter", "side"):
        im = ImageOps.mirror(im)
    return im, (im.width / 2.0, float(im.height))


# P-series poses the editor picks for a beat (POSE_RENDER_STANDARD.md: only poses in the approved manifest).
# P08 = both palms open: the viewer surrogate for a binary choice (owner, Oct 25: "Use P08"), registered in
# manifest.json with the SHA-256 from assets/poses/asset_checksums.json; asset_path() verifies it like every asset.
POSE_FOR = {"choice": "P08"}


@lru_cache(maxsize=8)
def pose(asset_id: str, height: int) -> Image.Image:
    """The approved pose trimmed to its visible pixels and scaled to `height` (uniform scale, placement only)."""
    im = Image.open(asset_path(asset_id)).convert("RGBA")
    box = im.getchannel("A").getbbox()
    im = im.crop(box) if box else im
    height = max(100, int(height))
    return im.resize((max(1, round(im.width * height / im.height)), height), Image.Resampling.LANCZOS)


def bust(mood: str = "neutral") -> tuple[Image.Image, str]:
    """(RGBA trimmed to its visible pixels, asset ID) of the approved F-series face for this mood."""
    aid = face_id(mood)
    return _trimmed(aid).copy(), aid


def approved_full_body(view: str = "front", height: int = 900, facing: str = "right"):
    """Old name: full_body(), or None instead of raising."""
    try:
        return full_body(view, height, facing)
    except MissingAsset:
        return None


# ---------------------------------------------------------------- the owner's own pose set (assets/poses)
# The owner's personal pose PNGs (added Oct 27, 86 transparent 1024x1536 files, SHA-256 in asset_checksums.json).
# The editor prefers them, when a narration line matches a pose's tag, as the host's B-roll shot (still <= ~15%
# of the runtime): placement only, the bytes are verified and never changed. Tags are generic actions / props,
# never a story: the first matching cue wins.
POSES_DIR = ROOT / "assets" / "poses"
POSE_CUES = [
    (r"\bknock(?:ed|ing|s)?\b", "P30_knocking_on_door"),
    (r"\bopen(?:ed|s|ing)?\s+(?:the\s+|a\s+|her\s+|his\s+|their\s+)?(?:\w+\s+)?door\b", "P30_opening_door"),
    (r"\b(?:read|reads|reading)\b[^.]{0,40}\b(?:letter|note|document|report|file|diary|newspaper|record)s?\b",
     "P18_reading_document"),
    (r"\b(?:held|holding|holds)\b[^.]{0,30}\b(?:photo|photograph|picture|portrait)s?\b", "P19_holding_photograph"),
    (r"\benvelopes?\b", "P20_holding_envelope"),
    (r"\b(?:magnifying|examin\w+|inspect\w+)\b", "P21_inspecting_magnifying_glass"),
    (r"\b(?:flashlight|torch)\b", "P22_searching_with_flashlight"),
    (r"\b(?:phone call|on the phone|dial(?:l)?ed|answered the phone|called the police)\b", "P23_talking_on_phone"),
    (r"\b(?:text(?:ed|s)?|messages?|notification|(?:checked|checks) (?:his|her|their|the) phone)\b",
     "P24_checking_phone"),
    (r"\btyp(?:ed|ing)\b", "P25_typing"),
    (r"\b(?:wrote|writing|took notes)\b", "P26_writing_notes"),
    (r"\b(?:folder|case file)s?\b", "P27_opening_folder"),
    (r"\b(?:waited|waiting|sat alone)\b", "P31_sitting_waiting"),
    (r"\b(?:peek\w*|peer\w*|around the corner)\b", "P32_peeking_around_corner_scene_variant"),
    (r"\b(?:ran|runs|running|fled|sprinted)\b", "P34_running_stride_clean_variant"),
    (r"\b(?:hid|hides|hiding)\b", "P35_hiding_behind_barrier_scene_variant"),
    (r"\b(?:sneak\w*|tiptoe\w*|crept)\b", "P36_sneaking_tiptoeing"),
    (r"\b(?:over (?:his|her|their|your) shoulder|being followed|being watched)\b", "P37_looking_over_shoulder"),
    (r"\b(?:fell|falls|tripped|stumbled)\b", "P38_falling_losing_balance"),
    (r"\b(?:walked|walking|wandered)\b", "P33_walking_stride"),
    (r"\b(?:looked around|searched|searching)\b", "P13_looking_around"),
    (r"\b(?:wallet)\b", "P49_examining_found_wallet"),
    (r"\b(?:pockets?)\b", "P46_checking_pockets"),
    (r"\b(?:checked the time|looked at (?:his|her|the) watch|wristwatch)\b", "P45_looking_at_watch"),
]


@lru_cache(maxsize=1)
def owner_pose_checksums() -> dict:
    p = POSES_DIR / "asset_checksums.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def owner_pose_ok(pose_id: str) -> bool:
    """The owner's pose file exists and its bytes match asset_checksums.json."""
    want = owner_pose_checksums().get(f"{pose_id}.png")
    p = POSES_DIR / f"{pose_id}.png"
    return bool(want) and p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest() == want


def owner_pose_for(text: str) -> str | None:
    """The first owner pose whose action / prop tag the line says ("she knocked on the door" -> P30_knocking_on_
    door), verified; None when nothing matches (the editor then keeps its normal picture / face choice)."""
    for rx, pose_id in POSE_CUES:
        if re.search(rx, text or "", re.IGNORECASE) and owner_pose_ok(pose_id):
            return pose_id
    return None


@lru_cache(maxsize=12)
def owner_pose_image(pose_id: str) -> Image.Image:
    """The verified owner pose, trimmed to its visible pixels (placement only). Raises MissingAsset."""
    if not owner_pose_ok(pose_id):
        raise MissingAsset(pose_id, "is missing or its SHA-256 differs from assets/poses/asset_checksums.json")
    im = Image.open(POSES_DIR / f"{pose_id}.png").convert("RGBA")
    box = im.getchannel("A").getbbox()
    return (im.crop(box) if box else im).copy()
