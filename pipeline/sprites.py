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



def select_for_beat(narration: str, mood: str = "neutral") -> str:
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
        narration, re.I))
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
