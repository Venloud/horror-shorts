# Split-screen TikTok clipper

Independent from the scheduled horror pipeline. Launch **Split-screen TikTok clipper** in GitHub Actions using **Run workflow**.

The default source is the supplied MrBeast video. Leave the background URL blank to rotate between **Orbital** and **Spicy Sauce** Minecraft parkour videos, or supply a custom HTTPS YouTube/video URL that you have permission to reuse. Credit the background creator in the TikTok description according to their published terms. Set the start time to **-1** for automatic highlight selection (default), or enter a manual start time. Set a duration of **1 to 59 seconds**. Output is 1080x1920, top source and bottom background, with original source audio.

**Preview** is the default. The MP4 is stored as a GitHub Actions artifact for seven days. **Draft** uses the existing TikTok credentials to send it to your TikTok inbox. **Direct** uses the existing TikTok direct-post integration, with the privacy setting already configured by the project. Only select it when you are ready to publish.

For local usage: `python clipper/render.py --source source.mp4 --background gameplay.mp4 --start 30 --duration 45`. The GitHub workflow uses faster-whisper to transcribe the source, score speech-rich passages, choose a highlight, and burn synchronized caption groups. It also saves the selected timestamp and SRT in the preview artifact. The heuristic is not a guarantee of a compelling clip, so review previews before publishing. Local renders can use optional `--subtitles captions.srt`.

The workflow downloads one of the two selected background sources when no custom URL is provided. Recheck reuse terms before posting, and note that YouTube downloads can fail due to access restrictions. This does not establish permission to repost the top-half source. Source access and TikTok posting remain subject to applicable permissions and platform rules.
