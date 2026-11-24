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

### Experiment: 40 s cut (started 2026-11-23, first daily run after the merge)

- **What:** every new video is a ~40 s cut (config `short_cut`: 36-44 s video, 80-92-word script written for that
  length, same universal editor). Owner, 2026-11-23: one 40 s video goes to **both YouTube and TikTok** through
  Buffer.com (accepts losing TikTok Creator Rewards, which needs > 60 s). Owner exact-words inbox scripts keep the
  full length. Switch off: `short_cut.enabled=false`.
- **Why:** first YouTube Analytics pull (28 days to 2026-11-23) — Shorts with >= 55% average viewed (18 videos)
  gained 6 subscribers, < 55% (32 videos) gained 1. Shorter videos should raise average % viewed.
- **Tracking:** `data/history.json` per video: `length_variant` ("40s" / "full") and `video_seconds`; daily
  analytics report (`homebeacon\tools\night-files-analytics\report_<date>.json`) gives avg % viewed and
  subscribersGained per Short.
- **Baseline to beat (full-length videos, 56-73 s, 28 days to 2026-11-23):** 50 Shorts, median average viewed
  **35.7%** (mean 42.2%), 1,224 views, **7 subscribers (5.7 per 1,000 views)**.
- **Read-out:** after ~2 weeks (about 2026-12-07) compare the 40 s videos' median avg % viewed, views per video and
  subscribers per 1,000 views with the baseline; TikTok views before/after as a side check.

Next: hook test (first 2 s show the threat in motion, no title card) once the length test has a result.

### Experiment: hook styles (started 2026-11-24, #60)
- Owner idea: test openers instead of waiting. Every written story now opens in one of these styles:
  control (strangest detail, as before), true_story ("This is a true story." first), did_you_know, date,
  description (paint the key image) and ending_first (outcome first, then rewind).
- The rotation picks the least-used style, so sample sizes stay even. true_story and date are only used on true stories.
- Only the opening of scene 1 is rewritten, from facts already in the script. Any failure goes out as control.
- Measure: average % viewed and subscribers gained per `hook_style` in history.json, once each style has 4 or more videos (~2 weeks).
- Known gap: analytics match videos to history by title, and that missed most videos. Fix the join before the read-out.
