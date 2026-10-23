#!/usr/bin/env python3
"""Make non-destructive, alpha-safe 1024x1536 Night Files pose copies.

Uses approved M01 as the reference, retains original bytes and reports QA issues.
Requires Pillow and NumPy.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

W, H = 1024, 1536
MARGIN_X = 36
GROUND_Y = 1460
TOP_MARGIN = 32
HEAD_TOLERANCE = 0.15
PROPORTION_TOLERANCE = 0.12


def image_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def alpha_bbox(image, threshold=30):
    alpha = np.asarray(image.getchannel("A"))
    yy, xx = np.where(alpha >= threshold)
    if len(xx) == 0:
        raise ValueError("No visible character found")
    return int(xx.min()), int(yy.min()), int(xx.max()) + 1, int(yy.max()) + 1


def head_measure(image):
    """Measure wide near-white head bands at the top, not the gloves or collar."""
    arr = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    _, y0, _, y1 = alpha_bbox(image, 80)
    upper_end = min(arr.shape[0], y0 + max(32, int((y1 - y0) * .36)))
    top = arr[y0:upper_end]
    rgb = top[..., :3].astype(np.int16)
    bright = (rgb.min(axis=2) >= 165) & (
        rgb.max(axis=2) - rgb.min(axis=2) < 58
    ) & (top[..., 3] >= 160)
    candidates = []
    for iy in range(0, bright.shape[0], 2):
        indexes = np.flatnonzero(bright[iy])
        if len(indexes) < 15:
            continue
        breaks = np.where(np.diff(indexes) > 1)[0]
        starts = np.r_[0, breaks + 1]
        ends = np.r_[breaks, len(indexes) - 1]
        runs = [(int(indexes[s]), int(indexes[e]) + 1) for s, e in zip(starts, ends)]
        left, right = max(runs, key=lambda r: r[1] - r[0])
        if right - left >= 30:
            candidates.append((right - left, (left + right) / 2))
    if not candidates:
        raise ValueError("Cannot detect unoccluded round white head, manual review required")
    max_width = max(w for w, _ in candidates)
    near_max = [(w, x) for w, x in candidates if w >= .94 * max_width]
    width = float(np.median([w for w, _ in near_max]))
    cx = float(np.median([x for _, x in near_max]))
    if width < .06 * image.width or width > .65 * image.width:
        raise ValueError("Ambiguous head width, manual review required")
    return width, cx


def validate_alpha(image):
    if image.mode not in ("RGBA", "LA", "P"):
        raise ValueError("Input must be a transparent PNG")
    if image.mode == "P" and "transparency" not in image.info:
        raise ValueError("Palette image has no alpha transparency")
    alpha = np.asarray(image.convert("RGBA").getchannel("A"))
    if np.count_nonzero(alpha < 8) < alpha.size * .02:
        raise ValueError("Source is not genuinely transparent")
    if np.count_nonzero(alpha > 128) < alpha.size * .01:
        raise ValueError("Source has insufficient visible artwork")


def normalize_pose(source, reference, *, max_upscale=1.25):
    validate_alpha(source)
    source = source.convert("RGBA")
    reference = reference.convert("RGBA")
    if reference.size != (W, H):
        raise ValueError("Approved M01 reference must be 1024 x 1536")
    ref_width, ref_cx = head_measure(reference)
    src_width, src_cx = head_measure(source)
    _, ry0, _, ry1 = alpha_bbox(reference)
    x0, y0, x1, y1 = alpha_bbox(source)
    ref_ratio = ref_width / (ry1 - ry0)
    source_ratio = src_width / (y1 - y0)
    proportion_error = abs(source_ratio / ref_ratio - 1)

    ideal_scale = ref_width / src_width
    max_width_scale = (W - 2 * MARGIN_X - 3) / (x1 - x0)
    max_height_scale = (GROUND_Y - TOP_MARGIN - 3) / (y1 - y0)
    scale = min(ideal_scale, max_width_scale, max_height_scale, max_upscale)
    if scale <= 0:
        raise ValueError("Invalid scaling")
    width = max(1, round(source.width * scale))
    height = max(1, round(source.height * scale))
    resized = source.resize((width, height), Image.Resampling.LANCZOS)
    bx0, _, bx1, by1 = alpha_bbox(resized)
    y = GROUND_Y - by1
    preferred_x = round(ref_cx - src_cx * scale)
    min_x, max_x = MARGIN_X - bx0, W - MARGIN_X - bx1
    if min_x > max_x:
        raise ValueError("Pose cannot fit canvas without cropping")
    x = int(min(max(preferred_x, min_x), max_x))

    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    canvas.alpha_composite(resized, (x, y))
    actual_head_width = src_width * scale
    head_error = abs(actual_head_width / ref_width - 1)
    shift = abs(x + src_cx * scale - ref_cx)
    warnings = []
    if proportion_error > PROPORTION_TOLERANCE:
        warnings.append(f"head_to_body_proportion_diff_{proportion_error:.1%}, requires revised artwork")
    if head_error > HEAD_TOLERANCE:
        warnings.append(f"head_size_diff_{head_error:.1%}")
    if shift > 24:
        warnings.append(f"head_center_shift_{shift:.0f}px")
    if scale > 1.001:
        warnings.append(f"resampled_up_{scale:.3f}x, not native detail")
    qa = {
        "canvas": [W, H],
        "ground_y": GROUND_Y,
        "render_bounds": list(alpha_bbox(canvas)),
        "uniform_scale": round(scale, 6),
        "reference_head_width": round(ref_width, 2),
        "render_head_width": round(actual_head_width, 2),
        "head_size_deviation": round(head_error, 4),
        "head_to_body_proportion_deviation": round(proportion_error, 4),
        "reference_head_to_body_ratio": round(ref_ratio, 4),
        "source_head_to_body_ratio": round(source_ratio, 4),
        "reference_head_center_x": round(ref_cx, 2),
        "render_head_center_x": round(x + src_cx * scale, 2),
        "quality": "review_required" if warnings else "pass",
        "warnings": warnings,
    }
    return canvas, qa


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reference", required=True, type=Path)
    ap.add_argument("--inputs", nargs="+", required=True, type=Path)
    ap.add_argument("--output-dir", required=True, type=Path)
    ap.add_argument("--max-upscale", type=float, default=1.25)
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()
    if args.max_upscale < 1:
        ap.error("--max-upscale must be at least 1")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with Image.open(args.reference) as im:
        validate_alpha(im)
        ref = im.convert("RGBA")
    records = []
    flagged = 0
    for path in args.inputs:
        if path.suffix.lower() != ".png":
            raise ValueError(f"Only PNG supported: {path}")
        output = args.output_dir / path.name
        if output.resolve() == path.resolve():
            raise ValueError("Refusing to overwrite original asset")
        if output.exists() and not args.overwrite:
            raise FileExistsError(f"Render copy already exists: {output}")
        original_hash = image_digest(path)
        with Image.open(path) as src:
            image, qa = normalize_pose(src, ref, max_upscale=args.max_upscale)
        if qa["quality"] != "pass":
            flagged += 1
        record = {"source": str(path), "source_sha256": original_hash, **qa}
        if not args.strict or qa["quality"] == "pass":
            image.save(output, format="PNG", optimize=True)
            record["render_output"] = str(output)
            record["render_sha256"] = image_digest(output)
        else:
            record["status"] = "not_exported"
        if image_digest(path) != original_hash:
            raise RuntimeError("Source asset changed unexpectedly")
        records.append(record)
    report = {
        "reference": str(args.reference),
        "reference_sha256": image_digest(args.reference),
        "source_bytes_preserved": True,
        "assets": records,
    }
    (args.output_dir / "normalization_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(f"{len(records)} processed; {flagged} require manual review")
    if flagged and args.strict:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
