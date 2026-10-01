# Setup guide

When it's set up, the bot builds videos on its own and posts **2 a day** (11:40 AM and 8:40 PM New York) to your
TikTok drafts and to YouTube Shorts. Your phone gets an ntfy alert with the caption, pinned comment and YouTube
link. **Cost: $0** on free tiers. CLAUDE.md has the full design notes.

---

## 1. Repo

Private GitHub repo `horror-shorts` with this code. The **Actions** tab should list: Build video (buffer), Daily
horror video, YouTube analytics, buffer_cleanup, yt_check, yt_upload_test, voice_samples, Connect TikTok (one
time), get-sfx.

## 2. Secrets

**Settings -> Secrets and variables -> Actions -> New repository secret.** Keys go only here, never in chat or code.

**Required**

| Name | What it is / where to get it |
|---|---|
| `GEMINI_API_KEY` | aistudio.google.com -> Get API key (stories, image QA) |
| `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` | dash.cloudflare.com -> Workers AI (FLUX images, 10,000 free neurons/day) |
| `HF_TOKEN` | huggingface.co -> Settings -> Access Tokens (free ZeroGPU Spaces: hook animation + backup images) |
| `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_REDIRECT_URI` | your TikTok developer app (sandbox) |
| `TIKTOK_REFRESH_TOKEN` | created by the "Connect TikTok (one time)" workflow (step 4) |
| `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN` | Google Cloud OAuth "Desktop app" client + `pipeline/connect_youtube.py` (step 5) |
| `GH_PAT` | fine-grained GitHub token for this repo: Secrets read/write, Actions read/write |
| `NTFY_TOPIC` | a random topic name you subscribe to in the ntfy app |
| `FREESOUND_API_KEY` | freesound.org API key (the get-sfx workflow for sound effects) |

**Optional** (the feature is skipped without it)

| Name | Enables |
|---|---|
| `GROQ_API_KEY` | console.groq.com: backup story writer (gpt-oss-120b) + backup image QA (qwen vision) |
| `PEXELS_API_KEY` | pexels.com/api: vertical stock video |
| `PIXABAY_API_KEY` | pixabay.com/api/docs: vertical stock video |
| `SI_API_KEY` | api.data.gov: Smithsonian Open Access photos (CC0) |
| `DUCHAS_API_KEY` | duchas.ie API: Irish folklore leads (also set `duchas_topic_ids` in config.json) |

Wikimedia Commons, Chronicling America and the Wikipedia pageviews API need no key.

## 3. TikTok developer app

developers.tiktok.com -> your app with **Login Kit** + **Content Posting API**, scopes `user.info.basic` and
`video.upload`, a web Redirect URI on your own site, and a **sandbox** with your account as Target User. Posting
mode is `tiktok_mode: "draft"`: videos land in your TikTok inbox and you post them.

## 4. Connect TikTok (one time)

Open `https://www.tiktok.com/v2/auth/authorize/?client_key=YOUR_CLIENT_KEY&scope=user.info.basic,video.upload&response_type=code&redirect_uri=YOUR_REDIRECT_URI&state=horror`,
approve, copy the whole URL you land on (within ~5 minutes), then run **Actions -> Connect TikTok (one time)** with
it. `TIKTOK_REFRESH_TOKEN` is saved for you.

## 5. Connect YouTube (one time)

1. Google Cloud Console: enable **YouTube Data API v3** and **YouTube Analytics API**, create an OAuth client
   (Desktop app), set the consent screen to **In production** (in "Testing" the token expires after 7 days).
2. On your computer: `pip install google-auth-oauthlib` then
   `python pipeline/connect_youtube.py path/to/client_secret.json`. It asks for upload + read-only analytics
   access and prints the three values for `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`.
3. Check with **Actions -> yt_check**: the log says `YouTube token OK`.
4. Until the Google Cloud project passes YouTube's API audit, uploads may be forced private; the log and the alert
   show the privacy YouTube returned.

## 6. Test

- **Build video (buffer) -> Run workflow** with **test** ticked: nothing goes into the buffer or history; the mp4 is
  kept as a run artifact. By default it re-renders the last built story with its saved images (no API cost).
  Tick **fresh_images** for a new story with real images. Optional: `visual_mode` (classic / fast / analog),
  `render_style` (classic / cutout, experimental).
- **YouTube analytics -> Run workflow**: `Analytics: N Shorts saved`, or `analytics scope missing` (redo step 5).
  An API failure turns the run red with the exact error.

After that everything runs by itself.

## Settings (config.json)

All settings and on/off flags are in `config.json` (edit on GitHub with the pencil icon). The main ones:

- Story: `story_modes`, `llm_models`, `groq_backup` / `groq_model`, `story_upgrade`, `critic_pass`,
  `trend_picking`, `discovery`.
- Voice: `voice` (`am_michael`), `voice_lang`, `voice_speed_range`, `target_seconds`.
- Images: `shots_per_scene` (2), `real_media` + `real_media_sources`, `local_image_max` (6), `image_check`,
  `image_style_cf` / `image_style_fallback`.
- Video: `visual_ab` + `visual_modes`, `ai_motion`, music volumes.
- Posting: `tiktok_mode`, `youtube_enabled`, `youtube_privacy`, `caption_search_style`, `analytics`.

The owner's own stories go in `inbox/` (see CLAUDE.md for the header lines TRUE / FICTION / SCRIPT / SCRIPT TRUE and
`NOT_BEFORE`). Music is picked from `assets/music/` (only tracks that are verifiably public domain or licensed for monetized use: today only the owner's own `unsolved_mystery.mp3`), twist stings from `assets/stings/`, sound effects from
`assets/sfx/`.

## Good to know

- Stories never repeat: `data/history.json` remembers every story; `data/counter.json` holds the post numbers.
- A failed build retries quietly 3 h later (and resumes where it stopped); you're only alerted when the buffer
  is empty. On days without Cloudflare quota the bot uses real media and free fallbacks, or waits for the quota.
- TikTok allows at most 5 unposted API drafts per 24 h: post or delete them so they don't pile up.
- If GitHub disables scheduled workflows for inactivity, click "enable" in the Actions tab.
