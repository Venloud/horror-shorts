# Night Files growth log

Goal: 500 genuine YouTube subscribers (owner mission, 2026-11-20). One record of the baseline, every production
fix that changes output, and every creative experiment with its measured result. Public numbers come from
`tools/channel_snapshot.py` (appends to `data/growth/snapshots.jsonl`); retention, swipe-away and subscribers per
video need YouTube Studio / Analytics access (not available to the bot yet).

## Baseline: 2026-11-21 (public channel page, @MonkeyTellsStories)

- **33 subscribers, 76 videos**; 48 Shorts listed; **median 30 views** per Short.
- Best: Slender Man 175, Strigoi 154, Severed Thumb Archives 120, "Lost Contact For Seventy Five Minutes" 117.
- Newest (Nov 17-19: Hessdalen, Bigfoot, St. Valentine's Day Massacre, Hanako-san): **5-10 views each**, i.e. the
  Shorts feed shows them to a handful of people and they are swiped away. Distribution, not volume, is the problem.

## Production outages found 2026-11-21

| Dates | Cause | Lost slots |
|---|---|---|
| Nov 10 | every writer stalled (Gemini timeouts, Groq 413, DeepSeek 2 x 180 s per topic, re-tried on every topic) | 1 |
| Nov 11-16 | Hessdalen script said "the nineteen thirties"; the number checker read 19 and 30, "not in the source". Parked after 3 tries, then the old Actions cache restored it and it was parked again in 9 more runs | 12 |
| Nov 19-20 | Dover Demon script said "April twenty-first"; checker read 20. Same story retried in 3 slots | 3 |

Fixes (this commit): ordinals / decades read correctly (`spoken_numbers.values`); a parked story leaves a marker and
is never resumed from an older cache entry; a final-gate failure parks the story at once and writes ONE replacement
story in the same run; stalled backup writers stay skipped for the whole run.

## Viewer review: Hanako-san (2026-11-19, 10 views)

- First second: black-and-white photoreal cover, then a different anime-style girl (style jump).
- Opening 3 s: a static title card over a standing girl; nothing happens yet.
- **Map showed Senegal labelled "THIS"** on a Japanese legend: Hollywood's place matcher dropped accents, so
  "Thiès" became "this" (1,984 gazetteer names were mangled). Fixed: accents fold ('thies').
- "Different versions claim she was a victim of bullying" is shown over a BOY on a staircase (subject mismatch); the
  same girl then fills 5 shots in a row; the ending trails off on "ANIME" / "FILMS" cards and a forced question.

## Experiments

None running yet. Next: hook test (first 2 s show the threat in motion, no title card) once production is stable.
