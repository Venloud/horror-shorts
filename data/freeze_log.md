# Feature freeze log

Freeze start: 2026-10-02 (7 days, through 2026-10-08). Owner's rules: bug fixes only, no test builds unless
production fails, one phone summary a day (~9 PM New York, freeze_summary.yml), production hold lifted after the
first production build passes QA and left lifted.

## 2026-10-02 04:55 UTC: freeze started
- Deferred cutout test cancelled (data/deferred_test.json removed); Cloudflare (~57 images/day at 172.8 neurons
  each) is for production only.
- Production hold ON until one supervised production build (build.yml input ignore_hold) passes QA after the
  07:00 UTC Gemini quota reset.
- Investigation started: why Cloudflare said "daily limit used up" at 00:44 UTC after only 16 images (~2,800
  neurons). Every Cloudflare call now logs its status + cf-ai-neurons + quota headers; preflight and the end of image
  generation log Cloudflare's own analytics count (needs Account Analytics: Read on the API token).

## 2026-10-02 04:55 UTC: Cloudflare "daily limit" bug fix (allowed during the freeze: bug fix)
- Finding: no Cloudflare error body was ever logged for the Oct 1-2 "daily limit used up" decisions; they all came
  from the bge-small quota probe, which counted an undocumented code 4006 as the daily limit. Cloudflare's docs:
  daily limit = code 3036 (HTTP 429) "You have used up your daily free allocation of 10,000 neurons"; limits reset
  00:00 UTC. Run 36944145400 had no limit error at all (its one failure was an NSFW 400, code 8007).
- Fix: only code 3036 / "daily free allocation" ends Cloudflare for the day; 429/3040/408/5xx retry 10/30/60 s
  then skip one image; every non-200 answer logs status + codes + headers + body.

## 2026-10-02 05:00 UTC: freeze bug fixes (owner-approved)
- publish.py: make-up post deletes missed_slot.json only on success; duplicate-post guard (already-posted buffer
  entries are only removed; failed removal = history `removal_pending`).
- analytics.yml / freeze_summary.yml: own concurrency groups (no longer in `night-files`).
- Cloudflare: no new data yet; the first call with full error logging is the 07:10 UTC supervised production build.

## 2026-10-02 08:37 UTC: Night Files freeze day 1/7
- Posted: nothing in the last 24 h
- Built: The Corpse That Chewed Its Shroud (lore, writer gemini (gemini-3.5-flash-lite), critic 92, 8 AI / 6 real)
- Build runs: 24 (4 failed: 36855953908, 36850352869, 36848613329, 36847389674)
- Buffer now: 1 video(s)
- Missed slot waiting for a make-up: Fri Oct 02, 02:12 AM New York
- Cloudflare 2026-10-01 UTC: no record

## 2026-10-03 05:50 UTC: Night Files freeze day 2/7
- Posted #31 The Corpse That Chewed Its Shroud (lore): YouTube public https://youtube.com/shorts/d-NAQNa3jGQ; TikTok ok
- Posted #32 The Green Children of Woolpit (mystery): YouTube public https://youtube.com/shorts/VcHDx2iaSEA; TikTok ok
- Posted #33 Municipal Water Reservoir Security Camera (fiction): YouTube public https://youtube.com/shorts/8qntiTftNv0; TikTok ok
- Built: The Corpse That Chewed Its Shroud (lore, writer gemini (gemini-3.5-flash-lite), critic 92, 8 AI / 6 real)
- Built: The Green Children of Woolpit (mystery, writer gemini (gemini-3.5-flash-lite), critic 91, 15 AI / 1 real)
- Built: Municipal Water Reservoir Security Camera (fiction, writer gemini (gemini-3.5-flash-lite), critic None, 14 AI / 1 real)
- Build runs: 6 (0 failed)
- Buffer now: 0 video(s)
- Missed slot waiting for a make-up: Fri Oct 02, 02:12 AM New York
- Cloudflare 2026-10-02 UTC: 9043/10000 neurons (tests 922, production 8122, ~52 images)

## 2026-10-04 06:27 UTC: Night Files freeze day 3/7
- Posted: nothing in the last 24 h
- Build runs: 0 (0 failed)
- Buffer now: 1 video(s)
- Missed slot waiting for a make-up: Fri Oct 02, 02:12 AM New York
- Cloudflare 2026-10-03 UTC: no record

## 2026-10-05 06:19 UTC: Night Files freeze day 4/7
- Posted: nothing in the last 24 h
- Build runs: 0 (0 failed)
- Buffer now: 1 video(s)
- Missed slot waiting for a make-up: Fri Oct 02, 02:12 AM New York
- Cloudflare 2026-10-04 UTC: no record
