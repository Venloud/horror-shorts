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
