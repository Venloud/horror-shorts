
## Night Files animation timing, 2026-10-25

Always consult [the editing quality checklist](docs/NIGHT_FILES_EDITING_QUALITY_CHECKLIST.md#nonlinear-easing-entryexit-and-subtle-interface-overshoot-owner-directive-2026-10-25) before altering captions, motion, graphics, UI, transitions or the editor. Ease-out on justified entry, ease-in on justified exit and restrained interface overshoot/settle, not linear-looking default keyframes. Hard cut remains the default between shots. **Do not modify production publishing or claim video acceptance just because the guideline is saved.**

## ECC task guidance (Vandam integration)

Read `.ecc/project.json` for the project-specific skills and restrictions. ECC skills are namespaced `ecc-*` in `.agents/skills` (Codex) and `.claude/skills` (Claude). The shared canonical installation is the sibling `claudevandam/integrations/ecc/`; keep repositories as siblings, or create missing links with its `ecc.py activate --project .` command after cloning.

At task intake run `python3 ../claudevandam/integrations/ecc/ecc.py select --project . --task "<task>"`, then load at most two selected skills. Run the same tool's `doctor --project .` to distinguish discovery from executable readiness. Existing project instructions, runtime source, approval gates and tests take precedence. No automatic observation hooks, separate memory service, provider changes or paid calls are enabled. A skill install is not a product acceptance test.

## Semantic visual editing rule, October 25, 2026

For every edit or video pipeline change, follow [the semantic visual-method-first rule](docs/NIGHT_FILES_EDITING_QUALITY_CHECKLIST.md#semantic-visual-method-first-owner-review-of-hinterkaifeck-october-25-2026) and Vandam canonical editing Rule 0B. For each narrated beat first decide whether a cinematic asset, motion graphic, clue icon, date/map, overlay, or held frame explains it best, then search/reuse assets only when appropriate. Do not force all supplied images into scenes. Synchronize graphics and SFX precisely, preserve full-frame composition and caption safe zones, and inspect the actual output. Hard cuts remain default. No publishing changes are authorized by this editorial rule.
