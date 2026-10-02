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
