# horror-shorts

A free, fully automated faceless horror-story channel for TikTok.

Every day it runs these steps: **Gemini** writes an original scary story → **Kokoro** narrates it → **Flux** (Cloudflare) makes the scene images → **FFmpeg** renders a 1080×1920 video with moving shots, film grain, word-by-word captions, a hook title, ducked background music, and a sting on the twist → **TikTok** gets the video in your drafts (or posted directly after app approval) → your phone gets the caption and a comment to pin.

Setup instructions are in **[SETUP.md](SETUP.md)**.

```
pipeline/
  main.py            runs everything in order
  story.py           story, scenes, caption, hashtags (Gemini)
  voice.py           narration + word timings (Kokoro)
  images.py          scene images (Cloudflare Flux, Pollinations fallback)
  captions.py        animated captions (.ass)
  render.py          video render + quality check (FFmpeg)
  tiktok.py          drafts / direct post (TikTok Content Posting API)
  notify.py          phone notification (ntfy) + run summary
  connect_tiktok.py  one-time TikTok login
config.json          voice, subgenres, style, posting mode
assets/music, assets/stings   background audio (royalty-free only)
data/history.json    past stories, so they never repeat
```
