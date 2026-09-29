# Night Files: project notes for Claude

Read this first. It sums up the decisions from the long chat where this project was built (Sept 2026),
so a new session can pick up without starting over.

## Who / what
- Owner: Van (GitHub **Venloud**). Computer science student who codes (Python, Java, web) and can debug;
  also works a day job, and is building this to earn income. Treat him as a developer: he prefers you write the
  code and hand it over ready to use, but you don't need to over-explain basics or talk down.
- **Night Files** is a fully automated, faceless AI horror / true-crime / folklore channel on **TikTok**
  (account "Nightfiles Stories", @istwatrajiks). Goal: go viral fast, spend as close to $0 as possible.
- Everything runs on **GitHub Actions** in this private repo.
- Repo is **private** (owner's call). `assets/music`: "Everything In Its Right Place" (Radiohead), "Tonight You Belong
  To Me" (Patience & Prudence), "bk grnde" by Kitty katzzz (credited in the caption), and his own "Unsolved Mystery".
  Music choices are his decision; don't lecture about it.
- Secrets/keys go ONLY in GitHub repo secrets. Never ask the owner to paste keys into chat.
- The owner is Christian, and his faith stays part of the channel's rules: **no occult / illuminati imagery**
  (no all-seeing eye, no floating "eyes only" shots, no occult symbols), even when a horror story would suggest it.
  Dark stories are fine; that kind of imagery is not.
- Mascot: a hooded monkey storyteller with a lantern and a "Night Files" book (`assets/mascot*.png`).
  Shown as a small corner logo and on the end card ("FOLLOW FOR MORE / NIGHT FILES" + click sound).
  The intro flash at the start was removed on purpose (`mascot_intro: false`): the hook must be frame one.

## Pipeline (pipeline/main.py runs it in order)
1. **Story** (`story.py`, `mystery.py`, `sources.py`) with the Gemini API (free tier). Models in `config.json` `llm_models`,
   automatic fallback on 404/429/503/safety blocks. On 503 (overloaded) the FIRST model is retried up to 5 times
   (~2 min wait, `_run_models(patient=True)`) because the backup model writes much worse image prompts.
   Modes rotate by position through `story_modes` (a mode can repeat), currently `[lore, mystery, lore, case, coldcase]`;
   inbox runs don't count toward the rotation. Made-up fiction was dropped from the rotation on purpose: real
   legends with a pop-culture tie-in perform best (the Strigoi video got 232 views and 47% average watch time).
   Fiction is only the fallback when a mode fails (still behind the 80/100 quality gate).
   **Groq backup writer** (flag `groq_backup`, `groq_model` openai/gpt-oss-120b, only if GROQ_API_KEY):
   `story.model_chain()` = first Gemini model -> Groq (OpenAI-compatible JSON mode, schema spelled out in the
   prompt, same prompts + fact lock) -> the other Gemini models. One Groq failure = next model at once. Every story
   logs "Written by gemini (...)" / "groq (...)"; history `writer`. Cloudflare text models are never used.
   Groq vision (`groq_vision_model` qwen/qwen3.8-27b, flag `groq_vision_qa`) is the backup image-QA checker when
   Gemini answers 429 (log reason "groq..."); without it that image's QA is skipped as before.
   - `fiction` (fallback only): written with the OWNER'S OWN instructions in `prompts/fiction_*.txt` (Reddit-style
     thriller/suspense/mystery). `fiction_creepy_job.txt` is his text verbatim; `fiction_reddit_thriller.txt` is a
     widened version with `{subgenre}`. `subgenre_prompts` in config maps subgenres to files.
     Step 2 turns the script into scenes with `prompts/scene_plan.txt` (images, sounds, caption) WITHOUT changing words.
   - `coldcase` (IN THE ROTATION AS A TEST): ORIGINAL fake case files (`prompts/fiction_cold_case.txt`: invented
     small town, missing adult, last sighting, evidence, suspects, one strange detail, twist that pays off the hook).
     Uses the fiction score loop (min 80, max 3 drafts; a date/year/place first sentence fails the draft), falls back
     to lore. Never gets the TRUE STORY badge/line/caption; caption gets "(fictional story)" + #fiction
     (`notify.is_fiction`: forced for ANY made-up story: coldcase, fiction fallback, inbox FICTION, sensitive cases
     retold as fiction; never for true stories, lore or inbox SCRIPTs). Never copies
     or resembles real cases or other creators' stories (e.g. the fake "Emily Carter case" is inspiration for the
     FORMAT only). Compare its analytics with the real modes via `mode` in history.json.
   - `case`: real FBI / History.com cases from `data/cases.json` (fact-locked `TRUE_PROMPT`; FBI page first,
     Wikipedia fallback). Sensitive stories (harm to a child, sexual crime, suicide) are NOT skipped: they
     become inspiration for an original fictional story instead (owner's request: "make it safe").
   - `mystery`: real unsolved mysteries (`data/mysteries.json`, Wikipedia facts).
   - `lore`: legends/folklore with a "Did you know" hook (`data/lore.json`).
   - `inbox/`: the owner can drop links (`inbox/links.txt`: `true <url>` or `fiction <url>`) or pasted
     stories (`.txt`, first line TRUE/FICTION/SCRIPT/SCRIPT TRUE). Inbox items jump the queue and are used once.
     Optional second header line `NOT_BEFORE: <video number>` (e.g. `NOT_BEFORE: 31`): `sources.next_inbox` skips
     that file until `data/counter.json` next_video >= that number; other inbox items and the rotation go on.
     (`inbox/louvre_password.txt` waits for #31.)
   - **TRUE STORY rule**: modes `case`, `mystery`, `inbox-true` and inbox `SCRIPT TRUE` files are true stories
     (NOT `lore`: legends aren't true stories; NOT fiction). For those, `story["true_story"] = True` (saved in history),
     scene 1 = hook sentence, THEN "This is a true story." (never first: slow opener; code moves/inserts it),
     captions.py shows a red "TRUE STORY" badge above the hook for 0-3.5 s, and the TikTok caption starts "TRUE STORY:".
     Inbox `.txt` first lines: `TRUE`, `FICTION`, `SCRIPT` (exact words) or `SCRIPT TRUE` (exact words, true story,
     real people drawn per the REAL PEOPLE rule in Images).
   - **HOOK RULE**: never open with a date, a year or a place name (when/where goes in scene 2); the first words are
     the strangest/most shocking detail. Analytics: "...of south-central France" (Gevaudan) and the Jim Thompson
     opener lost most viewers at 0:01. `story.hook_problem()` checks scene 1's first 6 words (4-digit year,
     "In <month>", country/state/region) and `fix_hook()` sends it back to the editor (max 2 tries).
     voice.py trims leading silence so the first word is spoken at ~0.0 s. Success check: 40%+ viewers left at 0:07.
   - Real stories include a **pop-culture reference** only when the Wikipedia "In popular culture" section
     states it (e.g. Beast of Gevaudan -> Teen Wolf). Never invent references.
   - Anti-repeat: `data/history.json` stores title, premise, setting, threat, twist; the last 40 are
     sent as "ALREADY USED".
   - Length: `story_words` [120, 140] = about 50-60 s (the Kokoro voice reads ~2.2-2.4 words/sec at speed 1.1).
     **Duration fit** (`main.fit_duration`): narration must land in config `target_seconds` [50, 60]. First the voice
     speed is adjusted within `voice_speed_range` [1.0, 1.2]; if still outside, Gemini trims/extends by the needed
     word count (`story.resize_story`, keeps scene 1's first sentence + the TRUE line, max 2 tries). Exact-words
     inbox SCRIPTs only get the speed change, never a rewrite.
   - **FACT LOCK** (mystery.py MYSTERY/LORE/TRUE prompts): the model first writes a `fact_ledger` from the SOURCE
     (names, numbers, money, dates, ages, places, counts, organizations, vehicles/aircraft, quotes) and writes only
     from it; values may become spoken words but are never changed, rounded, estimated or slangified. "Never
     distort a fact to make a hook more shocking." The ledger is saved in story.json and logged; resize_story keeps
     every factual value unchanged.
   - **TRUE-STORY FACT CHECK** (before voicing; `story.fact_check`, for `case`, `inbox-true`, `mystery`):
     `unsupported_details()` lists every number > 10, money amount, year, slang amount ("20k", "twenty-k") and
     capitalized name/place/organization in the narration that isn't in the source (numbers match however they're
     written: `pipeline/spoken_numbers.py`); Gemini corrects them from the source; each correction is logged. Then
     `speak_numbers()` writes all digits the way they're spoken ("$200,000" -> "two hundred thousand dollars",
     "1971" -> "nineteen seventy-one"). Owner's TRUE SCRIPT files are never rewritten; their numbers/names are
     only logged.
   - **Inbox failures**: a Gemini 503/429/quota/network error (or ANY failure of an owner's SCRIPT) never skips an
     item: it stays queued for the next build and the log says why. Only a permanent problem (e.g. a link with no
     article) skips it, with the reason in history. (inbox/elisa_lam.txt had been skipped by a 503 while its scenes
     were planned; it's back in the queue.)
   - **Hook candidates**: the real-story prompts return `hook_candidates` (3 first sentences); the editor pass
     scores them (`hook_scores`, "score | sentence") and `use_best_hook()` makes scene 1 start with the best one
     that passes `hook_problem()`; then `fix_hook()` still runs as a safety net.
2. **Voice**: Kokoro TTS `am_michael`, speed 1.1, word timings tagged by scene.
3. **Images** (`images.py`), all free: Cloudflare Workers AI FLUX schnell (10,000 neurons/day, resets 00:00 UTC =
   8 PM New York; no size option, 1024x1024 = 4 tiles x 4.8 + 4 steps x 9.6 = ~57.6 neurons, logged per image)
   -> free HF ZeroGPU Spaces running FLUX.1-schnell (config `image_spaces`, 576x1024, gradio_client like ai_motion;
   shares the daily GPU minutes with the AI hook) -> local SD-Turbo on the runner CPU (`local_image_model`,
   512x896, 2 steps, guidance 0; ~23 s load + ~20 s/image on 4 CPUs; Stability AI Community License: free under
   $1M/yr revenue, register once at stability.ai/community-license). Pollinations and the paid HF router were
   removed (always 402). The render upscales everything to 1080x1920 with lanczos. Log shows the source of every
   image and the local model's total time. `preflight()` runs BEFORE the story: tiny Cloudflare quota check; if
   it's out, test the Spaces, then the local model; only if all fail, stop with a phone alert (nothing wasted).
   If Cloudflare is out (or hits its limit mid-run), at most 2 shots per scene for the rest of the run.
   **2 images per scene** (`shots_per_scene` 2, was 4; 3-4 still work if configured): shot a = the narration's
   main visual, shot b = a DIFFERENT subject/action/angle of the same words (render motion covers the rest).
   Quota order: every scene's "a" shot first, then every "b", then "c"/"d", so running out of quota (or the local
   time budget) loses extra cuts, never whole scenes. SD-Turbo is a GAP FILLER only: max `local_image_max` (6)
   local images per video in production (test builds: only the 12-min `local_image_budget_minutes`). If Cloudflare
   and the Spaces are out and more scenes need an image than local may make, the build stops early
   (`images.ImageQuotaWait`, ntfy "waiting for image quota"; the checkpoint keeps story + narration, the buffer
   covers the gap); preflight does the same before writing a story when both are already out.
   Hook shot (scene 0 shot a): up to 3 draws (new seed, then `build_simple_prompt`) before it's dropped.
   Cloudflare daily cap vs short rate limit are told apart (short limit = wait and retry).
   A Space quota error marks the Spaces out for the run; the local model is always the last step. The run only
   fails if more than max(1, scenes // 4) scenes have no image at all.
   **REAL PEOPLE rule** (mystery.py prompts, scene_plan.txt, story.REAL_STORY_IMAGES, editor rules): real people
   get normal visible faces in the illustrated style, from basic public facts only (approximate age, hair,
   clothing, era); never an attempt to copy a real private person's actual face; historical figures (dead 100+
   years) may follow known portraits; masked/hooded figures are fine when the story fits. Each real person has a
   `characters` entry whose fixed look is reused word-for-word in every shot. This replaced the old
   silhouettes-only rule; the build_prompt "seen from behind, face not visible" auto-add was removed with it.
   The occult / all-seeing-eye / floating-eyes ban still applies.
   **Image prompts** (`images.build_prompt` Cloudflare / `build_short_prompt` fallbacks): natural comma-separated
   text, NO labels ("SHOT:", "SETTING:"... are stripped). Order: shot subject + action + key object -> locked looks
   of the characters named IN this shot -> THIS shot's location -> camera framing -> style. Cloudflare gets the full
   looks + full location + rich `image_style_cf`; fallbacks get 3-6 key traits (age, hair, clothing), <= 8 words of
   location, short `image_style_fallback`, and stay <= 70 CLIP tokens (trim order: style, camera, setting details,
   character details; the shot is never cut and is always first; a shot over ~42 CLIP tokens is rewritten to
   <= 20 words by flash-lite, `_shorter_shot`, keeping subject/action/object). Token counts come from the real CLIP
   tokenizer (its "longer than 77" warning was only drafts being measured; silenced). Only style words are
   filtered ("graphic novel", "comic panels"...), never a literal "panel" (elevator button panel).
   **No readable text**: prompts never ask for signs, neon lettering, title cards, headlines or screens/documents
   with words (`_no_text` strips quoted words, "sign reading ...", "neon sign" -> glowing neon tubes; texty shots
   get "no legible text" on Cloudflare / "blank unmarked surfaces" on fallbacks). Every image logs one line: provider,
   tokens, qa, subject, location (+ neurons for Cloudflare) and the final prompt.
   **Per-shot location**: the scene plan / mystery prompts output `image_location`, `image_location_2..4` (a
   `locations` name or "none") for each image prompt; only that shot's location is injected, never the scene's.
   An outdoor shot (forest, river, roof, sky...) never gets an interior block (e.g. the cabin). Object close-ups
   (note, briefcase, money...) get no setting (Cloudflare: 3 words at most). Older plans without the fields: only a
   location named in the shot. Schema lives in story.SCHEMA.
   **Near-duplicates**: `dedupe_shots` (before drawing) + a check before each shot: a nearly identical prompt is
   rewritten by Gemini to a different subject/angle, else rebuilt around an object from its narration.
   scene_plan.txt and the mystery.py prompts add ONE FRAME ONLY (one continuous film frame, never panels/
   collages/storyboards/split screens) and, for real stories, TRUE STORY VISUALS (historically accurate
   objects/clothing/vehicles/era; generic when the source doesn't say).
   Negative prompt (`images.NEGATIVE`: comic page, multiple panels, panel grid, collage, split screen, text,
   letters, speech bubbles, watermark) is passed to any Space that exposes `negative_prompt`; today none of the
   three sources uses one (Cloudflare FLUX / FLUX Spaces have no such input, SD-Turbo runs at guidance 0).
   **Image QA** (`check_image`, Gemini vision lite model): passes if the image clearly shows the requested subject
   and action in a setting that fits, is one frame and has no garbled text; it does NOT require a real landmark /
   brand / person identity (a painterly "old downtown hotel" is fine for the Cecil Hotel). "YES / NO: reason". Paced to
   `image_check_per_minute` (10); a 429 skips QA for that image only (qa=SKIPPED); never fails the build.
   Fallback images always get QA (waits a few s for the slot); Cloudflare images only when a slot is free right now
   (`image_check_cloudflare`), so fallbacks keep the quota. NO = rejected (file renamed `*.rejected*.png`, never
   used): after a Cloudflare NO the fallbacks draw it; after a fallback NO the next source tries once with a
   simpler prompt (`build_simple_prompt`); the same prompt is never sent twice; one try per provider (no blind
   retries). Also refused: files < 256 px or landscape. A shot with no usable image gets a virtual shot (75% crop)
   only from the SAME scene and the same place (never a cabin image for a forest shot); a scene with no image at
   all borrows a same-place image, else (emergency, logged) its own rejected image or the previous scene's.
   End of run: "Cloudflare images / Cloudflare estimated neurons / HF images / Local SD images / Rejected images /
   Virtual/cached images".
   Consistency: the scene plan outputs `characters` and `locations` sheets (never removed); looks are injected
   word-for-word, only into shots where that character / location actually appears.
   Art style (config `image_style_cf` / `image_style_fallback`): dark painterly illustration with bold ink linework,
   NOT photoreal. "graphic novel", "comic", "panels", "storyboard" are never in a positive prompt (they caused page
   layouts / panels); the look stays the same (painterly + bold ink, warm lamp / moonlight highlights).
   **Real media first** (`media.py`, flag `real_media`, per-source flags `real_media_sources`; runs before the AI
   images, never stops a build): the scene plan gives each shot `image_source` (ai / stock_video / real_photo) +
   `image_query`. stock_video = generic atmosphere, no story character: Pexels Videos (PEXELS_API_KEY,
   /v1/videos/search, portrait, >= 1080 tall, <= 190 calls/h) -> Pixabay Videos (PIXABAY_API_KEY, vertical only;
   never Pixabay music). real_photo = TRUE stories only (real place/building/object/document/official sketch; never
   private people, victims, crime scenes): Wikimedia Commons (no key, NightFilesBot User-Agent, one request at a
   time, Retry-After honored, ONLY Public domain / CC0 / CC BY) -> Smithsonian Open Access (SI_API_KEY, CC0 only).
   Searches cached 24 h (`cache/media-search`, Actions cache `media-search-*`). Limits: <= `stock_video_max_share`
   (0.4) stock shots, <= `real_photo_max` (3) photos; the hook shot (0a) stays AI; a stock clip isn't reused within
   `stock_reuse_window` (20) videos (history `media_ids`). Same paced Gemini QA; fail -> next result (max 3) -> AI.
   Graded to the channel look (dark, desaturated, teal/amber, vignette, grain). Photos = 1080x1920 PNG (parallax in
   render); stock video = `scene_XXl.mp4` (8 s max, 1080x1920, 30 fps, no audio) next to a poster PNG, played by
   render as real motion. `scene_XXl.json` + story["media_assets"] keep source/url/author/license/date. Credits:
   TikTok caption line "Visuals: Pexels, Wikimedia Commons"; YouTube description "Visual credits:" (caption.json
   `visual_credits`). Free Spaces draw at most `space_images_max` (6) images per video so ZeroGPU minutes stay
   for the hook animation.
4. **Render** (`render.py`, `effects.py`, `ai_motion.py`), FFmpeg 1080x1920:
   - Hook shot: real AI animation via free Hugging Face ZeroGPU Spaces (list in config `ai_motion.spaces`,
     live API discovery, never hard-wired) -> falls back to 3D parallax -> falls back to Ken Burns zoom.
   - Other shots: Depth Anything V2 Small (Apache-2.0, CPU) 2.5D parallax; fog + dust overlays; light flicker
     only on scenes whose narration mentions lights; camera shake on the twist.
   - Cuts land on punctuation; min shot 1.2 s. Captions: one word at a time, white, centered (Anton font).
   - Sound effects: real recordings in `assets/sfx` (BigSoundBank / Freesound CC0). `clean_sfx()` removes any
     sound the narration doesn't literally mention; max 4; never on the hook.
   - Music ducked under the voice, per-track volumes in config. Video bitrate capped (TikTok API limit 64 MB).
5. **TikTok** (`tiktok.py`): own developer app "Night Files" (sandbox). `tiktok_mode: "draft"`: videos go to
   the owner's TikTok inbox and he posts them himself (account stays PUBLIC). Direct Post app review was
   submitted, but TikTok's guidelines reject "tools that upload to your own/team accounts", so expect rejection.
   Plan if needed: an approved third-party posting service, or turn this into a public product later.
   **YouTube Shorts** (`youtube.py`, Data API v3, scope youtube.upload): the same mp4 right after TikTok, in
   publish.py. Title = story title + " #Shorts" (<=100 chars, cut at a word), description = the TikTok caption
   text + #Shorts, tags from hashtags, category 24, containsSyntheticMedia true, not made for kids, privacy from
   config `youtube_privacy` (`youtube_enabled` switches it off). Uploads from an UNVERIFIED Google Cloud project
   are forced private until YouTube's API audit passes; the log/alert shows the privacy YouTube returned.
   TikTok and YouTube are independent: the video leaves the buffer if at least one worked (never double-posted);
   only if both fail does it stay for the next slot. Refresh token: run `pipeline/connect_youtube.py` once
   locally (OAuth consent screen must be "In production", or Google expires the token after 7 days).
6. **Notify**: ntfy phone alert with caption + pinned comment + YouTube link (`NTFY_TOPIC`).

## Buffer (build.yml fills it, daily.yml posts from it)
- `build.yml` runs every 3 h: if fewer than 3 (`BUFFER_SIZE`) videos wait on the GitHub Release **"buffer"**
  (assets `<stamp>.mp4` + `<stamp>.json`), it makes one (`pipeline/main.py`) and uploads it (`pipeline/buffer.py`).
  Inbox items / cases / history are marked used when the video enters the buffer. A failed build exits quietly
  (next run retries); the phone alert only fires when the buffer is empty. The images + story are saved to the
  Actions cache (`last-images-*`) after each build.
- `build.yml` "test" input (workflow_dispatch): no Cloudflare (reuses the cached images if the scene count
  matches, else local SD-Turbo), not added to the buffer, no history, mp4 kept as an artifact, ntfy "[TEST]".
  `test_cloudflare_images` input (0-12, default 0; env TEST_CF_IMAGES): a test build uses that many real
  Cloudflare images first (no cache reuse then) to check actual quality.
- `daily.yml` (`pipeline/publish.py`) does NO generation: oldest buffered video -> TikTok + YouTube Shorts ->
  delete from buffer -> both results + "posted" time saved in history -> phone alert with the YouTube link
  (+ "buffer low" alert at 1 left). Only if both platforms fail does the video stay in the buffer.
- **Empty buffer at a slot**: the publisher does NOT fail. It writes `data/missed_slot.json` {"slot", "at"}, sends
  "Buffer empty: building now, will post when ready", and daily.yml starts build.yml at once (`gh workflow run`,
  GH_PAT or github.token with actions: write). When a video passes QA and enters the buffer, main.py calls
  `publish.post_missed_slot()`: missed slot < 6 h old -> post it right away (same publish code, TikTok + YouTube,
  so build.yml also has the TikTok/YouTube secrets + token-save step), then delete the file; older -> just delete
  it and the next slot posts normally. Both workflows save history.json + missed_slot.json with
  `pipeline/push_state.sh` (merge_history.py + 3 push tries).
- **Video numbers** (`data/counter.json` {"next_video": N}): GitHub run numbers are per workflow, so the bot keeps
  its own post counter. `publish.take_video_number()` gives the number only once a video actually went out
  (TikTok or YouTube accepted it, also for a make-up post from build.yml); test builds, failed publishes and
  empty-buffer slots never use one. The number is in history.json (`video_number`), the ntfy title ("#26 ..."),
  the logs and the artifact name (`video-26`). Before posting, a video is known by its story id (build
  artifacts `build-<story_id>` / `test-<story_id>`, buffer caption.json `story_id`). push_state.sh commits
  counter.json with history (higher next_video wins). #26 = the Louvre heist, #27 = D. B. Cooper (backfilled);
  the counter continues at #28.
- Note: while the repo is public, buffered (unposted) videos on the release are publicly downloadable.

## Reliability (build side)
- **Render join**: every clip (AI motion, parallax, Ken Burns) is normalized to 1080x1920 / 30 fps / yuv420p /
  SAR 1 / one timebase, video only, before the xfade chain (`render.NORMALIZE`, `_join`), so odd AI clips can't
  crash it.
- **Checkpoints** (`checkpoint.py`, Actions cache `ckpt-<run id>`): a build keeps story.json, the narration
  (wav + timings, tied to a hash of the text + speed) and every finished image in `cache/checkpoint/`. A failed
  build's next try resumes the same story and only makes what's missing. Success writes `done.json`, so an older
  cache entry is never resumed; a story already in history is never resumed. Test builds skip checkpoints.
- **QA gate** (`render.qa_gate`) before the buffer: 1080x1920, duration within target + end-card tail, audio
  stream, integrated loudness -18..-12 LUFS (ffmpeg ebur128; the mix is loudnormed to -14), caption lines in the
  burned-in .ass cover the words, 5-64 MB. Fail = not buffered + ntfy alert; a duration failure drops the saved
  narration so it's re-fitted; the SAME story failing QA twice is skipped for good (history `skipped` + reason).
- **Concurrency**: build.yml and daily.yml share the group `night-files` (never write history.json at the same
  time); build cron is :50 every 3 h, just after the publish slots. Pushing history uses
  `pipeline/push_state.sh` -> `merge_history.py` (applies this run's new/changed entries onto origin/main's file)
  + push, 3 tries;
  no rebase conflicts. Note: GitHub keeps only ONE pending run per concurrency group; a newer queued run
  replaces an older pending one.

## Schedule
- 2 videos a day, **11:40 AM and 8:40 PM New York**. GitHub's own cron was unreliable (4 h late / skipped),
  so the plan is **cron-job.org** calling the `workflow_dispatch` API for `daily.yml` with a fine-grained token
  (Actions: read & write). Only remove the `schedule:` block from daily.yml AFTER cron-job.org is tested.
- `build.yml` has `timeout-minutes: 60` and HF cache key `hf-models-v3` (adds SD-Turbo); `daily.yml` 15 min.
- `build.yml` runs at :50 every 3 hours (UTC); publish slots are 15:40 and 00:40 UTC.

## Owner preferences (how to work with him)
- Hook must hit in the first second; stories need a hook, a logical plot and a real ending that pays off the hook.
- Wants consistency (same characters/places), lots of cuts, real sound effects (not synthesized), quieter music.
- Wants everything free where possible. If he asks about a workaround (e.g. extra accounts), give the real
  risks straight, then respect his decision. It's his project.
- He often pastes reviews from other AIs: evaluate them honestly; keep what's right, explain what's wrong.
- Keep replies short and direct; he learns a workflow after doing it once or twice.
- When giving updates: just list the changed files and their folders. He knows the upload flow; don't re-explain it.
- Test renders locally before shipping when possible.

## Update report (required after every change)
End every reply that changes the repo with this block, as plain text I can copy:

UPDATE REPORT
- Commit: <short hash> - <one-line summary>
- Files changed: <path> (<what changed>), ...
- New secrets/config needed: <names or "none">
- What I tested: <how, and the result>
- Not tested / risks: <anything unverified>
- How to check it worked: <which workflow to run and what line to look for in the log>
- Next suggested step: <one line>

## Future ideas (not now)
- Repost to Instagram Reels, Snapchat (YouTube Shorts is live).
- More channels on the same bot: football facts, Bible stories, finance/side hustles ("side hustles that got
  patched", educational only, not financial advice), tech devices (needs real product images, affiliate links).
- Turn it into a public product (working names: ReelPilot / ChannelPilot): users run it on their own GitHub
  (template + setup site + a tiny Cloudflare Worker for TikTok login), free tier + paid "done for you".
- Owner's other projects: domino game (Figma), Lajan finance app, Fi Chier, AstroKeeper, portfolio site.

## Secrets used
GEMINI_API_KEY, CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_TOKEN, TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET,
TIKTOK_REFRESH_TOKEN, NTFY_TOPIC, HF_TOKEN, FREESOUND_API_KEY, GH_PAT, YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN.
Optional (feature skipped without them): PEXELS_API_KEY, PIXABAY_API_KEY, SI_API_KEY (api.data.gov), GROQ_API_KEY. (POLLINATIONS_KEY is no longer used.)
build.yml/daily.yml also use the built-in `github.token` for the buffer release.
