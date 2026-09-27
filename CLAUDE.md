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
   Modes rotate by position through `story_modes` (a mode can repeat), currently `[lore, mystery, lore, case]`;
   inbox runs don't count toward the rotation. Made-up fiction was dropped from the rotation on purpose: real
   legends with a pop-culture tie-in perform best (the Strigoi video got 232 views and 47% average watch time).
   Fiction is only the fallback when a mode fails (still behind the 80/100 quality gate).
   - `fiction` (fallback only): written with the OWNER'S OWN instructions in `prompts/fiction_*.txt` (Reddit-style
     thriller/suspense/mystery). `fiction_creepy_job.txt` is his text verbatim; `fiction_reddit_thriller.txt` is a
     widened version with `{subgenre}`. `subgenre_prompts` in config maps subgenres to files.
     Step 2 turns the script into scenes with `prompts/scene_plan.txt` (images, sounds, caption) WITHOUT changing words.
   - `case`: real FBI / History.com cases from `data/cases.json` (fact-locked `TRUE_PROMPT`; FBI page first,
     Wikipedia fallback). Sensitive stories (harm to a child, sexual crime, suicide) are NOT skipped: they
     become inspiration for an original fictional story instead (owner's request: "make it safe").
   - `mystery`: real unsolved mysteries (`data/mysteries.json`, Wikipedia facts).
   - `lore`: legends/folklore with a "Did you know" hook (`data/lore.json`).
   - `inbox/`: the owner can drop links (`inbox/links.txt`: `true <url>` or `fiction <url>`) or pasted
     stories (`.txt`, first line TRUE/FICTION). Inbox items jump the queue and are used once.
   - Real stories include a **pop-culture reference** only when the Wikipedia "In popular culture" section
     states it (e.g. Beast of Gevaudan -> Teen Wolf). Never invent references.
   - Anti-repeat: `data/history.json` stores title, premise, setting, threat, twist; the last 40 are
     sent as "ALREADY USED".
   - Length: `story_words` [120, 140] = about 50-60 s (the Kokoro voice reads ~2.2-2.4 words/sec at speed 1.1).
2. **Voice**: Kokoro TTS `am_michael`, speed 1.1, word timings tagged by scene.
3. **Images** (`images.py`): Cloudflare Workers AI FLUX schnell (free 10,000 neurons/day, ~58 per image,
   resets 8 PM New York) -> Hugging Face (credits usually used up, 402) -> Pollinations (`POLLINATIONS_KEY`).
   Up to 4 images per scene (`shots_per_scene`), each showing exactly what the words say at that moment.
   Quota order: every scene's "a"/"b" shots are drawn before any "c"/"d", so running out of quota loses extra
   cuts, not scenes. Cloudflare daily cap vs short rate limit are told apart (short limit = wait and retry);
   Pollinations 402 marks it out for the run; once all services are out the rest are skipped. The run only
   fails if more than max(1, scenes // 4) scenes have no image at all.
   Consistency: the scene plan outputs `characters` and `locations` sheets; the code injects the fixed looks
   into every prompt (style first, then setting, then character looks, then the shot).
   Art style (config `image_style`): comic / storybook illustration, NOT photoreal. Owner chose to keep comic
   only (not the 1980s found-photo look).
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
6. **Notify**: ntfy phone alert with caption + pinned comment (`NTFY_TOPIC`).

## Schedule
- 2 videos a day, **11:40 AM and 8:40 PM New York**. GitHub's own cron was unreliable (4 h late / skipped),
  so the plan is **cron-job.org** calling the `workflow_dispatch` API for `daily.yml` with a fine-grained token
  (Actions: read & write). Only remove the `schedule:` block from daily.yml AFTER cron-job.org is tested.
- `daily.yml` should have `timeout-minutes: 60` and HF cache key `hf-models-v2`.

## Owner preferences (how to work with him)
- Hook must hit in the first second; stories need a hook, a logical plot and a real ending that pays off the hook.
- Wants consistency (same characters/places), lots of cuts, real sound effects (not synthesized), quieter music.
- Wants everything free where possible. If he asks about a workaround (e.g. extra accounts), give the real
  risks straight, then respect his decision. It's his project.
- He often pastes reviews from other AIs: evaluate them honestly; keep what's right, explain what's wrong.
- Keep replies short and direct; he learns a workflow after doing it once or twice.
- When giving updates: just list the changed files and their folders. He knows the upload flow; don't re-explain it.
- Test renders locally before shipping when possible.

## Future ideas (not now)
- Repost to YouTube Shorts, Instagram Reels, Snapchat after the TikTok trial.
- More channels on the same bot: football facts, Bible stories, finance/side hustles ("side hustles that got
  patched", educational only, not financial advice), tech devices (needs real product images, affiliate links).
- Turn it into a public product (working names: ReelPilot / ChannelPilot): users run it on their own GitHub
  (template + setup site + a tiny Cloudflare Worker for TikTok login), free tier + paid "done for you".
- Owner's other projects: domino game (Figma), Lajan finance app, Fi Chier, AstroKeeper, portfolio site.

## Secrets used
GEMINI_API_KEY, CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_TOKEN, TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET,
TIKTOK_REFRESH_TOKEN, NTFY_TOPIC, HF_TOKEN, POLLINATIONS_KEY, FREESOUND_API_KEY, GH_PAT.
