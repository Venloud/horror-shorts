# Inbox project assets and safe reuse

A script at `inbox/PROJECT.txt` can own originals in `assets/projects/PROJECT/`.
Its `manifest.json` declares schema 1, the matching `project_id`, an `assets` list,
and optional `preserve_exact_opening` and offline `preview_story`. Every asset
needs a unique ID, relative file, kind (`image`, `video`, optional `sfx`), SHA-256,
truthful description, rights/provenance and explicit project-use authorization.
Use the Hinterkaifeck manifest as a complete example. Do not infer clearance from
a filename, an uploaded attachment, or an archival appearance.

The existing classic/explainer flow now selects relevant project media first,
then the existing shared library, licensed media search, and AI for remaining
gaps. Local CLIP relevance and quality gates still apply; unrelated pictures are
not inserted merely because they were supplied. Videos retain their original
bytes and receive a local preview frame. Already-approved checkpoints remain
usable. Unknown rights fail closed. The archival Hinterkaifeck reference is
retained for source inspection and excluded from visual selection.

After the existing final video validation/buffer boundary, cleared, explicitly
reusable assets (including unused eligible assets) can be promoted through the
existing library Store and index. This is not a second asset service. Original
formats/bytes, full source hashes, tags, provenance, period/setting and metadata
are retained. Hash deduplication, original readback, index readback and a durable
`data/project_asset_promotions/PROJECT.json` receipt must succeed before cleanup.
Restricted or case-specific items, undeclared files, low-quality media and any
failed upload/verification keep the project folder intact. Promoted originals
are protected from ordinary library pruning. Repeating a completed promotion
uses the receipt. No owner-supplied rights are invented or broadened.

Approved existing SFX remain first. Authorized local project SFX are optional
fallbacks; missing sounds never block a visual build. The read-only command
`python pipeline/get_sfx.py --check-elevenlabs` checks authentication/quota only.
It performs no generation and proves no generation capability. Explicit future
sound-generation approval remains necessary before consuming credits.

## Isolated review render

From the repository, using its media environment and cached Kokoro/CLIP models:

```sh
python pipeline/main.py --preview-project hinterkaifeck_1922 --output-dir work/hinterkaifeck-review
python -m unittest discover -s tests -p test_project_assets.py -v
python -m unittest discover -s tests -v
```

Use a new output directory; an existing final export is never overwritten. This
path uses local narration, supplied/general-library media, original captions,
renderer, approved music and production QA. It disables depth-model downloads
and AI motion for this isolated preview; it never publishes, buffers, marks a
production checkpoint complete, consumes the inbox or changes production history.
An unfilled shot fails before paid generation. CLI exit 2 means QA failed.
Local FFmpeg, the normal media dependencies, Kokoro weights and cached CLIP are
required; absence is a real blocker, not permission to call a paid fallback.

## Hinterkaifeck review evidence — 2026-10-25

The uploaded ZIP's eleven originals are stored byte-for-byte under this project.
Uploaded scripts, metadata and notes remain in `assets/source_uploads/`; the
chosen 155-word script is `inbox/hinterkaifeck_1922.txt`. The original and revised
uploaded versions are preserved. The hook is exactly:

> Someone walked out of the frozen woods and straight toward their farmhouse. But the footprints never led back out.

Onscreen: **FOOTPRINTS IN. NONE OUT.** The following narration attributes the
footprint account as reported. Dates/six victims/mattock and reported pre-crime
observations were checked against the current encyclopedia account:
https://en.wikipedia.org/wiki/Hinterkaifeck_murders . This is a secondary-source
check, not independent proof of the footprint story or an attic occupant.
Illustrations are labeled reconstructions; the script does not confirm a killer
hiding in the attic. No real victim photographs are fabricated.

Final local review export: 1080×1920, 64.1 seconds, nine supplied illustrations,
`am_adam`, existing approved soundtrack and SFX. FFmpeg fully decoded the video;
production QA passed with no problems. Eight sampled frames were inspected;
peak audio −1.9 dBFS, mean −17.8 dBFS. An earlier eight-picture preview failed
its picture-count gate and was retained as a failed attempt. A superseded voice
preview was also retained; neither is the final export.

All eleven supplied originals are general-reuse restricted/case-specific, so
none was promoted or deleted. No direct YouTube API or workflow was introduced;
current Buffer delivery changes from main remain intact. No generation, posting,
paid call, production buffer/history write or workflow dispatch occurred.
The matching Vandam implementation record holds logs, hashes, preview results,
regression results and review PR links.
