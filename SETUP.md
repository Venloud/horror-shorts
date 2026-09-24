# Setup guide (one time, about 30–45 minutes)

When you're done, a new scary-story video lands in your TikTok drafts every day at 5:40 PM, and your phone gets a notification with the caption to paste.

**Cost: $0.** Everything runs on free tiers. Each daily run uses about 10–15 of GitHub's 2,000 free minutes a month.

---

## 1. Put the code on GitHub

1. Make a free account at **github.com** if you don't have one.
2. Click **+ → New repository**. Name it `horror-shorts`, choose **Private**, then click **Create repository**.
3. On the empty repo page, click **uploading an existing file**.
4. Unzip `horror-shorts.zip` on your computer. Open the folder and drag **everything inside it** into the upload box, including the `.github` folder. Hidden folders don't show on Mac by default, so press `Cmd + Shift + .` to see it.
5. Click **Commit changes**.
6. Check that the **Actions** tab lists "Daily horror video" and "Connect TikTok (one time)". If it doesn't, the `.github` folder didn't upload, so drag it in again.

## 2. Get the free API keys

Keep a notes file open and paste each value into it as you go.

**Gemini (writes the stories)**
- Go to **aistudio.google.com**, click **Get API key**, then **Create API key**. Copy it. You don't need a credit card.

**Cloudflare (makes the images)**
- Sign up free at **dash.cloudflare.com**.
- Open **AI → Workers AI** in the left menu. Copy your **Account ID** (it's also in the browser URL).
- Go to **My Profile → API Tokens → Create Token**. Use the **Workers AI** template and click **Create**. Copy the token.
- If Cloudflare ever fails, the pipeline falls back to Pollinations, which is free and needs no key.

**ntfy (sends the notification to your phone)**
- Install the **ntfy** app (iPhone or Android).
- Tap **+** and subscribe to a topic name that nobody could guess, e.g. `van-horror-x7k29q`. Anyone who knows the name can read the messages, so keep it random.

## 3. Create the TikTok developer app

1. Go to **developers.tiktok.com** and log in with the TikTok account the videos are for.
2. Click **Manage apps → Connect an app**. Fill in the name, icon, and description.
   - You need a **Terms of Service URL** and a **Privacy Policy URL**. Add simple pages to your portfolio site.
3. Under **Products**, add **Login Kit** and **Content Posting API**.
4. Under **Scopes**, add `user.info.basic` and `video.upload`.
5. In the Login Kit settings, add a **Redirect URI** for Web. Use any https page on your own site, e.g. `https://yourportfolio.com/tiktok`. The page can even show a 404, because you only need the URL it lands on.
6. Open the **Sandbox** tab. Create a sandbox and add **your TikTok account as a Target User**. Copy the sandbox **Client key** and **Client secret**. This lets it work right away without waiting for TikTok's review.

## 4. Make a GitHub token so the bot can save the TikTok login

1. Go to GitHub **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**.
2. For **Repository access**, choose **Only select repositories**, then `horror-shorts`.
3. Under **Permissions → Repository permissions**, set **Secrets** to **Read and write**.
4. Set the expiration to 1 year, generate the token, and copy it.

## 5. Add the secrets to the repo

In your repo, go to **Settings → Secrets and variables → Actions → New repository secret**. Add each one of these, with the name spelled exactly as shown:

| Name | Value |
|---|---|
| `GEMINI_API_KEY` | Gemini key |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare account ID |
| `CLOUDFLARE_API_TOKEN` | Cloudflare token |
| `TIKTOK_CLIENT_KEY` | TikTok client key |
| `TIKTOK_CLIENT_SECRET` | TikTok client secret |
| `TIKTOK_REDIRECT_URI` | The redirect URI from step 3.5, exactly the same |
| `GH_PAT` | GitHub token from step 4 |
| `NTFY_TOPIC` | Your ntfy topic name |

## 6. Connect your TikTok account

1. Build this link in your notes, replacing the two parts in CAPS:

   ```
   https://www.tiktok.com/v2/auth/authorize/?client_key=YOUR_CLIENT_KEY&scope=user.info.basic,video.upload&response_type=code&redirect_uri=YOUR_REDIRECT_URI&state=horror
   ```

2. Open it in your browser and approve. You'll land on your redirect page, and the URL bar will contain `?code=...`.
3. **Within about 5 minutes** (the code expires quickly), copy that whole URL.
4. In GitHub, go to **Actions → Connect TikTok (one time) → Run workflow**, paste the URL, and click **Run**.
5. The run turns green when it worked, and the `TIKTOK_REFRESH_TOKEN` secret is created for you automatically.

## 7. Test it

1. Go to **Actions → Daily horror video → Run workflow**, tick **Test run**, and click **Run**. It takes about 10–15 minutes.
2. When it finishes, open the run and scroll to **Artifacts**. Download the zip and watch `final.mp4`.
3. If you're happy with it, run it again **without** ticking Test run. The video should appear in TikTok as an inbox notification ("Your video is ready to edit"), and your phone should get the ntfy message.

From now on it runs by itself every day.

---

## Your daily 30 seconds

1. Tap the TikTok notification to open the draft.
2. **Optional but good for reach:** add a trending sound and set its volume to about 5–10% so the narration stays clear.
3. Paste the caption from the ntfy notification.
4. Under **More options**, turn on **AI-generated content**.
5. Post, then pin the suggested comment.

If a run fails, you get a "FAILED" notification. Open **Actions**, click the red run, and the error is in the log.

## Phase 2: fully automatic posting

1. In the TikTok developer portal, submit your app for **review/audit**. Add the `video.publish` scope and a short screen recording showing how it works.
2. Once approved, switch the secrets to the **production** client key and secret, then redo step 6 with `scope=user.info.basic,video.upload,video.publish`.
3. In `config.json`, set `"tiktok_mode": "direct"` and `"direct_privacy": "PUBLIC_TO_EVERYONE"`.
4. Videos then post themselves with the caption and AI label already applied. Trending sounds still can't be added this way; that's a TikTok limit.

## Customizing

Edit these in `config.json` directly on GitHub (pencil icon):

- `channel_name`: your channel's name, used in the story prompt.
- `voice`: the narrator. Try `am_michael` (default), `am_onyx`, `am_fenrir`, `bm_george`, or `bm_lewis`. Use `voice_speed` to make it slower or faster.
- `subgenres`: add or remove story types.
- `caption_highlight`: the color of the highlighted word.
- `music_volume`: how loud the background music is.

The background music comes from `assets/music/`. There's a default dark drone. Add royalty-free tracks (e.g. from **pixabay.com/music**, searching "dark ambient") and it picks one at random each day. Never use copyrighted songs. Put impact sounds for the twist in `assets/stings/`.

To change the posting time, edit the `cron` line in `.github/workflows/daily.yml`. It's in UTC, so New York time + 4 hours in summer and + 5 in winter.

## Good to know

- Stories never repeat. `data/history.json` remembers every past story and gets fed back into the prompt.
- Draft limit: TikTok allows at most 5 unposted API drafts per 24 hours. At 1 a day that's fine, but post them or delete them so they don't pile up.
- If GitHub ever emails that scheduled workflows were disabled for inactivity, click "enable". The daily history commit should prevent that.
