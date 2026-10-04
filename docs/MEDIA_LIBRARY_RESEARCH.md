# Shared Media Sources Research

See `MEDIA_LIBRARY_RESEARCH.md` in Bouriko for the full research and implementation plan.

This repository should use the shared media-provider architecture described there where applicable:
- stock: Pexels, Pixabay, Coverr
- open/archive: Openverse, Wikimedia Commons, Internet Archive, Library of Congress, NASA, NOAA
- reaction/meme: KLIPY, Twitch Clips, GIPHY Clips
- anime: Blitz Anime API, anime-sdk, trace.moe
- sound effects: Freesound, Lots of Sounds
- local clip mining: OpenClip, Clips Studio

Every automated asset must preserve source, creator, license, source URL, and provider metadata in a manifest. Unknown/unclear rights should not be treated as cleared.

Implementation target: one reusable media-provider interface shared across video bots, with visual-intent requests such as `stock_video`, `reaction`, `streamer_reaction`, `anime`, `archival_video`, `sfx`, and `generated_visual`.

This file is a pointer/handoff document. The authoritative detailed notes are maintained in the Bouriko research document.
