
## Night Files retention R1–R9 (owner, October 27, 2026)

For every Night Files script, require an intelligible **central question**, a real change in viewer understanding, and an **honest payoff**. The question can be supported by **one optional understated recurring evidence motif**, not an invented status counter, charge, scorecard or unsupported conclusion. Reference `docs/NIGHT_FILES_STORYTELLING_STYLE.md` and the existing editor checklist before writing or cutting. Respect source verification for nonfiction, cinematic primary imagery, hard cuts, captions, approved cover and continuity. The optional three-episode fiction feature is disabled by default, requires full owner approvals, and must fail closed until **both 7 days and 14 actual verified public posts** pass. Existing publishing jobs and unrelated draft PRs are out of scope.

## Night Files animation timing, 2026-10-25

Always consult [the editing quality checklist](docs/NIGHT_FILES_EDITING_QUALITY_CHECKLIST.md#nonlinear-easing-entryexit-and-subtle-interface-overshoot-owner-directive-2026-10-25) before altering captions, motion, graphics, UI, transitions or the editor. Ease-out on justified entry, ease-in on justified exit and restrained interface overshoot/settle, not linear-looking default keyframes. Hard cut remains the default between shots. **Do not modify production publishing or claim video acceptance just because the guideline is saved.**

## ECC task guidance (Vandam integration)

Read `.ecc/project.json` for the project-specific skills and restrictions. ECC skills are namespaced `ecc-*` in `.agents/skills` (Codex) and `.claude/skills` (Claude). The shared canonical installation is the sibling `claudevandam/integrations/ecc/`; keep repositories as siblings, or create missing links with its `ecc.py activate --project .` command after cloning.

At task intake run `python3 ../claudevandam/integrations/ecc/ecc.py select --project . --task "<task>"`, then load at most two selected skills. Run the same tool's `doctor --project .` to distinguish discovery from executable readiness. Existing project instructions, runtime source, approval gates and tests take precedence. No automatic observation hooks, separate memory service, provider changes or paid calls are enabled. A skill install is not a product acceptance test.

## Semantic visual editing rule, October 25, 2026

For every edit or video pipeline change, follow [the semantic visual-method-first rule](docs/NIGHT_FILES_EDITING_QUALITY_CHECKLIST.md#semantic-visual-method-first-owner-review-of-hinterkaifeck-october-25-2026) and Vandam canonical editing Rule 0B. For each narrated beat first decide whether a cinematic asset, motion graphic, clue icon, date/map, overlay, or held frame explains it best, then search/reuse assets only when appropriate. Do not force all supplied images into scenes. Synchronize graphics and SFX precisely, preserve full-frame composition and caption safe zones, and inspect the actual output. Hard cuts remain default. No publishing changes are authorized by this editorial rule.

## Night Files: edit the maintained bot, not endless branches (October 27, 2026)

Venloud explicitly prefers **improvements integrated into the existing working Night Files bot** over a new experimental branch or detached rewrite for every edit. Read `main`, concurrent work, the current production/editor contracts and [CLAUDE.md](CLAUDE.md) first. For narrow authorized changes, improve the existing implementation directly with targeted regression tests and an integration record. Do not create another feature branch merely to demonstrate the same idea. If risk, branch protection or active unmerged work requires a PR, reuse the relevant existing PR where possible and give it an explicit integration/retention/cleanup disposition. Preserve unfinished agent work and approved media; never delete branches or publish videos without appropriate checks and authorization. In-scene motion graphics belong in the existing renderer; the narrated-year timeline is implemented in `pipeline/noir.py` and `pipeline/explainer.py`, not in a second video pipeline.

## Night Files date motion: once, on the first grounded date (October 27, 2026)

The existing explainer `date_stamp` is a minimal timeline overlay **over the current story image**, with a smooth indicator landing on the narrated year or calendar day and highlighting only that endpoint in red. **Use at most ONE such timeline per video, at its FIRST grounded narrated date.** No later date-timeline repeats or random year/title cards, no unsupported relative dates and no unrelated SFX. Subsequent dates remain in captions/narration. Implement/refine only inside existing `main` editor (`pipeline/explainer.py` and `pipeline/noir.py`), keep renderer safe zones and validated nonfiction provenance, and never open a new branch solely for this treatment. Existing version-3 storyboards are filtered locally when resumed to prevent repetition without a new AI call. See the active editing checklist.
