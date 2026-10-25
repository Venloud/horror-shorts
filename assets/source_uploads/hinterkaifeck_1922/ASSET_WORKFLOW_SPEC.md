# Night Files asset-first lifecycle, proposed integration

1. For an inbox script, create `inbox/assets/<script_slug>/` with `manifest.json`, `images/`, `videos/`, `sfx/`, and `scene_bindings.json`.
2. Check script-specific assets first. Search the *persistent* existing GitHub Release asset library next, using its CLIP text-image matching, QA, crop and licensing rules.
3. Match footage and imagery by subject/action/era/location, not filenames or general similarity alone. Reuse archives only for the exact site, otherwise label visuals as illustrative. Respect per-video reuse limits, recent reuse windows and diversity.
4. If no reliable match, search licensed real media using pipeline/media.py. Only then run AI scene generation.
5. Support a frame graphic layout for a letterboxed photo or video with a subtle border, descriptive archive/recreation label and animated camera within the frame. Do not crop away historical context simply to fill 9:16.
6. Use `assets/sfx/<cue>.mp3` first, then optionally query approved Freesound API using token in secrets. Restrict to CC0 or explicitly approved licenses; record source URL, creator, license, and hash, normalize to mp3. On failure, leave the scene without that effect, not the video without audio. No verification of a live API key was performed.
7. When the finished video and visual QA succeed, dedupe media by SHA-256 and perceptual hash; promote high-quality, cleared, reusable assets into the current GitHub Release asset library. Store precise tags, rights, creator, source URL, original script, general applicability and style. Never use an unknown license as a free-use asset.
8. Verify index, object downloads and checksums *before* removing temporary inbox assets. Make promotion and cleanup idempotent and retry-safe. Never clear `inbox/` or production release buffer as a generic cleanup.
9. Persistent general names should describe what image actually depicts, e.g. `winter_farmhouse_snow_footprints_night_1920s_recreation_<hash8>.png`, `barn_investigators_oil_lantern_1920s_illustration_<hash8>.png`. Preserve source files unaltered, track derived crop versions separately.
10. Keep the existing pipeline/library.py asset-first behavior, don't replace it with a duplicate library. This package is a local handoff, not a GitHub implementation or verified deployment.
