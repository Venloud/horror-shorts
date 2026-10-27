# Night Files, viewer value and numbered clue pacing (owner review, October 26, 2026)

Scope: Night Files only. The owner reviewed a **previously published** fictional Oak Haven / 1884 archive video and found the words needlessly obscure and the promised "three clues" insufficiently visualized. This critique is a creative review, not external evidence that the storm, institution, archives, records or claimed chemical properties exist.

## Story value, before any visual spending

For every NEW script, the creator and editors must be able to state in one ordinary sentence why someone should remember watching:
- an authentic surprising fact, learned correctly and sourced;
- a story revelation, cause, choice or consequence they can explain to a friend;
- or a particular emotional experience with an earned meaning or payoff.

Never force a sermon or moral; a coherent, haunting fictional mystery can deliver emotional value. But an arbitrary final diary entry, impossible record or anonymous agency alone is NOT a payoff. The story must make sense even when the supernatural mechanism remains unexplained. In non-fiction, distinguish actual evidence from conjecture and don't manufacture forensic certainty.

Use friendly language without losing specificity. Name the central incident and clarify the place/people early, then any necessary dates or technical details. Replace obscure unexplained phrases with a concrete translation on first mention (for example "maritime legend" = "an old sea story"). Every new clue should change our understanding of the same question. Describe what it actually implies rather than calling it proof just because it sounds scientific. No false claims of real evidence.

This writer rule is effective through the existing centrally injected `docs/NIGHT_FILES_STORYTELLING_STYLE.md`, used by `pipeline/story.py:shared_style` for all current providers. Do not add a new writer, new judge call or additional paid credits to enforce it.

## Sequential clue graphic overlay, explainer only

The existing explainer editor now has an optional `pipeline/clue_board.py` layer. It creates a compact persistent counter and disclosure list ONLY when spoken narration includes an explicit "two/three/four clues/reasons/etc." lead-in and correctly enumerates first/second/third(/fourth) afterward. Each row contains only **contiguous words actually said**; future rows are hidden and revealed at their precise word timestamps. It stays across normal background pictures and shot boundaries until the last clue is explained, then fades off. It does not replace the pictures, choose background assets or dictate story content.

No exact cue, incomplete list, absent timing, number mismatch or no supported enumeration: nothing changes. No fake clue text, research material or sound is created. The board uses Night Files' existing accent, plain dark backing and phone-safe placement above captions. No decorative transitions. The initial implementation does not add new SFX because the repo has no verified licensed typing/click event sound for these actions. Do not invent a door/clock sound to accompany typography.

Config kill-switch: set `explainer_clue_board=false` in `config.json` to disable without code rollback. Only the existing explainer uses it. Classic and cutout are unaffected; none of the scheduling, Buffer/TikTok/YouTube, asset library, or previously buffered videos is changed.

## Review and rollout

Keep these changes on an isolated PR until the full test suite and an actual representative non-publishing rendered video have been reviewed for readability, pacing, captions, clipping and SFX. A passing PIL frame test or successful GitHub CI is NOT proof the published result looks good. Do not rerun an old publish, alter TikTok media, dispatch a production queue or create a second video just to test.
