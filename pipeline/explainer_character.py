"""EXPLAINER render style: the recurring stick-figure "you", drawn ONCE (explainer_character.yml) and reused in every
explainer video, so a video spends 0 neurons on the character.

12 poses / expressions, every one with the SAME description word-for-word (config explainer_character_look +
explainer_character_style); only the pose phrase changes. Cloudflare FLUX schnell (Workers AI has no seed input:
"'/seed' not allowed", so consistency comes from the identical description + the check against pose 1). Each pose:
QA (one character, the pose, plain background) -> same character / outfit / style as pose 1 (Gemini vision, Groq
backup; NO = redraw, max 3 draws) -> cut out (rembg, gray-key fallback) -> assets/character/<pose>.png.
Poses already in assets/character are kept (a re-run only draws the missing ones). Test share of the Cloudflare
ledger (TEST_MODE=true): stops when today's test room is used up.
  TEST_MODE=true python explainer_character.py [--redo pose,pose]
"""
import json
import sys
from datetime import datetime, timezone

from common import CONFIG, ROOT, log

CHAR_DIR = ROOT / "assets" / "character"
REFERENCE = "worried"
POSES = {
    "worried": "standing, facing the viewer, worried expression, eyebrows raised in the middle, small frown, "
               "hands held together in front",
    "angry": "standing, facing the viewer, angry expression, eyebrows pulled down, gritted teeth, fists clenched",
    "scared": "standing and leaning back, scared expression, wide eyes, mouth open, both arms raised defensively",
    "shocked": "standing, facing the viewer, shocked expression, huge round eyes, jaw dropped, hands on cheeks",
    "determined": "standing, facing the viewer, determined expression, confident smirk, fists on hips",
    "sneaky": "tiptoeing sneakily, side view facing left, sly narrowed eyes, one finger on the lips",
    "sweating": "standing, facing the viewer, nervous expression, one big sweat drop on the forehead, awkward grin, "
                "tugging the hoodie collar",
    "looking_back": "walking away, looking back over the shoulder, nervous eyes, side view facing left",
    "running": "running fast, side view facing left, panicked expression, arms pumping, one leg lifted",
    "sitting": "sitting on a plain wooden crate, thinking expression, chin resting on one hand",
    "holding": "standing, facing the viewer, holding a flashlight in both hands, curious expression",
    "pointing": "standing, facing the viewer, pointing to the right with one arm stretched out, alarmed expression",
}
SIDE = {"sneaky", "looking_back", "running"}  # drawn facing left; the renderer flips them when needed

LOOK = ("an original stick-figure character: a perfectly round plain white bald head with a thick black outline, no "
        "hair, no ears, no blush, a big expressive cartoon face with thick black eyebrows, large white oval eyes with "
        "black pupils and a simple bold mouth, a forest-green baseball cap with a small orange button on top, an "
        "oversized charcoal-gray hoodie with orange drawstrings, thin black stick arms with round white hands, two "
        "thin black stick legs, chunky white sneakers with orange soles")
STYLE = ("flat 2D vector cartoon, clean thick black outlines, flat colors, no shading, single character, full body, "
         "centered, plain flat medium-gray background, even lighting, no text, no letters")


def look() -> str:
    return CONFIG.get("explainer_character_look") or LOOK


def style() -> str:
    return CONFIG.get("explainer_character_style") or STYLE


def prompt(pose: str) -> str:
    """The same words for every pose; only the pose phrase differs."""
    return f"{style()}, {look()}, {POSES[pose]}"


def available() -> dict:
    """{pose: cut-out PNG} for the poses in assets/character (empty when the set was never drawn)."""
    return {p: CHAR_DIR / f"{p}.png" for p in POSES if (CHAR_DIR / f"{p}.png").exists()}


def draw_set(redo: set | None = None, max_draws: int | None = None) -> dict:
    import cf_budget
    import cutout
    import images
    CHAR_DIR.mkdir(parents=True, exist_ok=True)
    raw_dir = ROOT / "output" / "character"
    raw_dir.mkdir(parents=True, exist_ok=True)
    man_path = CHAR_DIR / "manifest.json"
    try:
        manifest = json.loads(man_path.read_text())
    except (OSError, ValueError):
        manifest = {"poses": {}}
    redo = redo or set()
    if manifest.get("look") and (manifest["look"] != look() or manifest.get("style") != style()):
        log("Character: the description changed since the set was drawn; every pose is redrawn (word-for-word rule)")
        redo = set(POSES)
        manifest["poses"] = {}
        for p in POSES:  # never a mixed set: old poses go (git history keeps them)
            (CHAR_DIR / f"{p}.png").unlink(missing_ok=True)
    max_draws = int(max_draws or CONFIG.get("explainer_character_max_draws", 20))
    draws = 0
    log(cf_budget.line())
    order = [REFERENCE] + [p for p in POSES if p != REFERENCE]
    for pose in order:
        dest = CHAR_DIR / f"{pose}.png"
        if dest.exists() and pose not in redo:
            continue
        ok = False
        refused = 0
        for attempt in range(6):
            if attempt - refused >= 3:
                break
            if draws >= max_draws:
                log(f"Character: {draws} draws used (max {max_draws}); {pose} left for the next run")
                break
            if not cf_budget.test_allowed():
                log(f"Character: today's Cloudflare test share is used up ({cf_budget.line()}); "
                    f"{pose} left for the next run")
                break
            raw = raw_dir / f"{pose}_{attempt}.png"
            try:
                images._save_valid(images._cloudflare(prompt(pose), 4242, fixed_seed=True), raw)
            except Exception as e:  # noqa: BLE001
                log(f"Character {pose}: draw failed ({str(e)[:160]})")
                if images._STATE.get("cf_out"):
                    return manifest
                if "8007" in str(e) or "NSFW" in str(e):  # Cloudflare's prompt filter: refused, nothing billed
                    refused += 1
                    continue
                draws += 1
                continue
            draws += 1
            v, why = images.check_image(raw, f"one cartoon stick figure with a round white head, a green cap and a "
                                             f"gray hoodie, {POSES[pose]}, plain gray background")
            log(f"Character {pose} (draw {attempt + 1}): QA {'YES' if v else 'NO' if v is False else 'skipped'}"
                + (f" ({why})" if why else ""))
            if v is False:
                continue
            same, swhy = True, ""
            if pose != REFERENCE:
                ref_raw = manifest["poses"].get(REFERENCE, {}).get("raw")
                ref = raw_dir / ref_raw if ref_raw and (raw_dir / ref_raw).exists() else CHAR_DIR / f"{REFERENCE}.png"
                if not ref.exists():
                    log(f"Character {pose}: no reference pose yet; skipped")
                    break
                same, swhy = images.same_character(ref, raw)
                log(f"Character {pose}: same character as '{REFERENCE}'? "
                    f"{'YES' if same else 'NO' if same is False else 'unchecked'}" + (f" ({swhy})" if swhy else ""))
                if same is False:
                    continue
            try:
                cutout.cut_out(raw, dest)
            except ValueError as e:
                log(f"Character {pose}: {e}")
                continue
            manifest["poses"][pose] = {"prompt": prompt(pose), "raw": raw.name, "qa": "YES" if v else "skipped",
                                       "same_as_reference": "YES" if same else "unchecked", "draw": attempt + 1,
                                       "side_view_facing": "left" if pose in SIDE else "front"}
            ok = True
            log(f"Character {pose}: saved {dest.relative_to(ROOT)}")
            break
        if not ok and pose == REFERENCE and not dest.exists():
            log("Character: no usable reference pose; stopping (nothing else can be checked against it)")
            break
    manifest.update({"look": look(), "style": style(), "reference": REFERENCE,
                     "source": "Cloudflare Workers AI @cf/black-forest-labs/flux-1-schnell (original design)",
                     "seed": "not supported by Workers AI FLUX schnell; same description word-for-word instead",
                     "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")})
    manifest["missing"] = [p for p in POSES if not (CHAR_DIR / f"{p}.png").exists()]
    man_path.write_text(json.dumps(manifest, indent=2) + "\n")
    log(f"Character set: {len(POSES) - len(manifest['missing'])}/{len(POSES)} poses, {draws} draws this run; "
        f"missing: {', '.join(manifest['missing']) or 'none'}; {cf_budget.line()}")
    try:
        cutout.sheet([(CHAR_DIR / f"{p}.png", p) for p in POSES], raw_dir / "character_sheet.png", "poses",
                     cols=4, cell=(270, 400))
    except Exception as e:  # noqa: BLE001
        log(f"Character sheet failed ({e})")
    return manifest


if __name__ == "__main__":
    redo = set()
    if "--redo" in sys.argv:
        redo = {p.strip() for p in sys.argv[sys.argv.index("--redo") + 1].split(",") if p.strip() in POSES}
    m = draw_set(redo)
    sys.exit(0 if not m.get("missing") or len(m["missing"]) < len(POSES) else 1)
