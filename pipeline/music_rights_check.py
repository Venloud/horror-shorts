"""Validate Night Files music provenance policy before CI/builds.

Default policy is procedural_only: no files under assets/music are allowed to be used.
If approved_files is explicitly enabled, every music file must be listed in approved_music.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
MUSIC = ROOT / "assets" / "music"
EXTS = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}

policy = str(CONFIG.get("music_policy", "procedural_only")).strip().lower()
files = sorted(p for p in MUSIC.glob("*") if p.is_file() and p.suffix.lower() in EXTS)
approved = set(CONFIG.get("approved_music") or [])

if policy == "procedural_only":
    if files:
        raise SystemExit(
            "Music rights check failed: music_policy=procedural_only but assets/music contains "
            + ", ".join(p.name for p in files)
        )
elif policy == "approved_files":
    unapproved = [p.name for p in files if p.name not in approved]
    if unapproved:
        raise SystemExit(
            "Music rights check failed: unapproved files: " + ", ".join(unapproved)
        )
else:
    raise SystemExit(f"Music rights check failed: unknown music_policy={policy!r}")

print(f"Music rights check: OK ({policy}; {len(files)} repository music file(s))")
