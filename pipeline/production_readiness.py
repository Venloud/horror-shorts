"""Offline production-readiness check for GitHub Actions.

No paid/API generation occurs here. This catches missing local tools,
configuration and required production credentials before the expensive build.
"""
import importlib.util
import json
import os
import shutil
import sys

from common import CONFIG, ROOT


REQUIRED_MODULES = ("requests", "PIL")
def main() -> int:
    errors = []
    warnings = []

    if not shutil.which("ffmpeg"):
        errors.append("ffmpeg is not installed")
    if not shutil.which("ffprobe"):
        errors.append("ffprobe is not installed")

    for module in REQUIRED_MODULES:
        if importlib.util.find_spec(module) is None:
            errors.append(f"Python module is missing: {module}")

    target = CONFIG.get("target_seconds")
    if not isinstance(target, list) or len(target) != 2:
        errors.append("config.target_seconds must be [min,max]")
    elif float(target[0]) <= 0 or float(target[1]) < float(target[0]):
        errors.append(f"invalid target_seconds: {target!r}")

    for name in ("GEMINI_API_KEY", "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN", "GITHUB_TOKEN"):
        if not os.environ.get(name):
            warnings.append(f"{name} is not set in this shell; the workflow must provide it")

    if CONFIG.get("youtube_enabled", True):
        for name in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"):
            if not os.environ.get(name):
                warnings.append(f"{name} is not set; YouTube publishing will be skipped")

    policy = str(CONFIG.get("music_policy", "procedural_only"))
    if policy == "approved_files" and not CONFIG.get("approved_music"):
        errors.append("approved_files music policy has no approved_music allowlist")


    # The manual Night Files run must use the owner's approved host art, not a
    # procedurally drawn replacement with a different identity.
    if os.environ.get("RENDER_STYLE", "").lower() == "explainer":
        manifest = ROOT / "assets" / "character" / "host" / "manifest.json"
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            approved = {item.get("id"): item for item in data.get("approved", []) if item.get("status") == "approved"}
            for asset_id in ("M01", "M02", "M03", "M04", "M05"):
                item = approved.get(asset_id)
                if not item or not (manifest.parent / item.get("path", "")).is_file():
                    errors.append(f"approved host master missing: {asset_id}")
        except (OSError, ValueError, TypeError) as exc:
            errors.append(f"approved host manifest unreadable: {exc}")

    for item in warnings:
        print(f"READINESS: WARN: {item}", flush=True)
    for item in errors:
        print(f"READINESS: FAIL: {item}", flush=True)

    if errors:
        return 1

    print("READINESS: PASS: local toolchain and configuration are ready; credential presence was reported above", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
