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
- Repo is **private** (owner's call). `assets/music` (Oct 5): ONLY the owner's own tracks "Unsolved Mystery"
  (`unsolved_mystery.mp3`) and "bk grnde" (`bk_grnde.mp3`, credited "Music: bk grnde by Kitty katzzz"); the owner
  confirmed both are his. They rotate with the FFmpeg-generated ambient bed (config `music_policy` approved_files,
  `approved_music`, `music_rotation` [unsolved_mystery, bk_grnde, procedural], picked by history length in
  `background_music._pick_approved`). Oct 1 copyright audit (owner's request after a YouTube "Notices" flag): removed
  "Everything In Its Right Place" (Radiohead, (P) 2016 XL Recordings: the YouTube Content ID claim was THIS file) and
  "Tonight You Belong To Me" (Patience & Prudence, 1956 Liberty recording ripped from a YouTube upload; the 1926
  song is public domain but US pre-1972 recordings from 1947-1956 stay protected until 2067 under the Music
  Modernization Act). Those two must never come back. ChatGPT deleted "Unsolved Mystery" on Oct 3 (c89e26b) blaming it
  for the Radiohead claim by mistake; both owner tracks were restored Oct 5. Only add a track whose specific recording is verifiably public domain / CC0 / licensed for
  monetized use, with its source + license noted here. `assets/stings/default_impact.mp3` has no recorded source
  (uploaded Sept 25): unverified. Music choices are his decision; don't lecture about it.
- Secrets/keys go ONLY in GitHub repo secrets. Never ask the owner to paste keys into chat.
- The owner is Christian, and his faith stays part of the channel's rules: **no occult / illuminati imagery**
  (no all-seeing eye, no floating "eyes only" shots, no occult symbols), even when a horror story would suggest it.
  Dark stories are fine; that kind of imagery is not.
- Mascot: a hooded monkey storyteller with a lantern and a "Night Files" book (`assets/mascot*.png`).
  Shown as a small corner logo and on the end card ("FOLLOW FOR MORE / NIGHT FILES" + click sound).
  The intro flash at the start was removed on purpose (`mascot_intro: false`): the hook must be frame one.


## External project integrations (implementation order)
- These integrations are added one at a time. Do not replace the working Night Files production pipeline wholesale.
- **Remotion: OFF (Oct 5)**. `remotion_join` false: every production run logged `REMOTION: FAILED ... does not contain "registerRoot"` and fell back to FFmpeg, so the attempt (and its npm install in daily.yml / buffer_fill.yml) is skipped. The code stays; FFmpeg `render._join` renders every video.
- **PersonaLive: INTEGRATED, OFF by default**. Optional adapter in `pipeline/ai_motion.py`; requires an explicitly configured local PersonaLive checkout, reference/driving assets, and a suitable environment. GitHub-hosted CPU production stays on the existing motion path.
- **MuMuAINovel: INTEGRATED**. Deterministic local story-bible stage in `pipeline/story_bible.py`, after story writing and before shot planning. It carries canonical characters, locations, threat/twist, timeline, and visual continuity. Do not copy the GPL application wholesale.
- **AutoClip: INTEGRATED, OFF by default**. `pipeline/autoclip_adapter.py` runs only after the primary render succeeds, uses the rendered video path, produces optional alternate clips/publish kits, and is non-fatal. Latest AutoClip fix commit: `79d803d65f0e11aa242e2573e2abfc065472579a`.
- **Ruflo: INTEGRATED, PRODUCTION-DISABLED**. The first implementation layer is now present as a declarative orchestration manifest plus six reusable task contracts under `docs/ruflo_tasks/`, with `pipeline/ruflo_check.py` and `pipeline/ruflo_task_check.py` validating the manifest/contracts. Ruflo is an agent meta-harness for Claude Code/Codex with agents, swarms, memory, hooks, and workflow orchestration. Night Files currently uses Ruflo only as an orchestration contract, not as a production runtime. No Anthropic key, Ruflo daemon, swarm, MCP server, or new secret is required. The existing Python generator, renderer, QA, buffer, and publisher remain the production source of truth. The next stage is isolated non-production execution and comparison, followed only by consideration of selective production delegation. See `NIGHT_FILES_UPDATE.md` and `docs/RUFLO_INTEGRATION.md`. Official repo: https://github.com/ruvnet/ruflo

## Pipeline (pipeline/main.py runs it in order)
1. **Story** (`story.py`, `mystery.py`, `sources.py`) with the Gemini API (free tier). Models in `config.json` `llm_models`,
   automatic fallback on 404/429/503/safety blocks (see **Retries** below).
   Modes rotate by position through `story_modes` (a mode can repeat), currently `[lore, mystery, lore, case, coldcase]`;
   inbox runs don't count toward the rotation. Made-up fiction was dropped from the rotation on purpose: real
   legends with a pop-culture tie-in perform best (the Strigoi video got 232 views and 47% average watch time).
   Fiction is only the fallback when a mode fails (still behind the 80/100 quality gate).
   **Groq backup writer** (flag `groq_backup`, `groq_model` openai/gpt-oss-120b, only if GROQ_API_KEY):
   `story.model_chain()` = every Gemini model in llm_models, STRONGEST FIRST (3.8-flash, flash-latest, 3.5-flash-lite
   last; minus ones whose DAILY quota is used up) -> Groq LAST; a story written by a lite model or Groq logs
   "WARNING: story text written by ... a last-resort writer". Small JSON helper calls (critic scores, premises,
   packaging, images._gemini_json) use `model_chain(light=True)` (lite first) so they don't eat the strong
   model's small free daily quota
   (OpenAI-compatible JSON mode, schema spelled out in the prompt, same prompts + fact lock).
   **Retries** (`story._with_models`, used by every writer/JSON call): 500/503 "high demand" = the SAME model again
   after 10 s, 30 s, 60 s, then the next Gemini model, then Groq; a Gemini per-minute 429 waits its retryDelay
   (max 65 s, 3x); a per-DAY quota = next model at once. Groq 429 tokens/requests per MINUTE (TPM/RPM) = wait
   Retry-After / "try again in Xs" (max 65 s) and resend the same request up to 3x; only per-DAY (TPD/RPD) counts
   as exhausted. Groq gets a shorter source (`groq_source_chars` 3500; source text is wrapped in invisible markers
   by `common.mark_source`, Gemini gets it whole) and `groq_max_tokens` 8000. If every writer failed only on rate
   limits / overload -> `ApiBusy`: NOT a topic problem, no topic/mode switching; the build stops, the next one
   retries (inbox items / cases stay queued). (Test build 15:37 on Sept 30: two 503s were misread as the daily
   quota, then Groq TPM 429s made it hop through 4 topics in 15 s.) Every story
   logs "Written by gemini (...)" / "groq (...)"; history `writer`. Cloudflare text models are never used.
   Groq vision (`groq_vision_model` qwen/qwen3.8-27b, flag `groq_vision_qa`) is the backup image-QA checker when
   Gemini answers 429 or errors (log reason "groq..."); without it that image's QA is skipped as before.
   **Gemini daily quota** (flag `gemini_quota_switch`, `common.note_gemini_429(body, model)`): ONLY a 429 whose body
   names a per-DAY quota ("PerDay" quota id / "per day") counts, and only for THAT model ("exceeded your current
   quota" alone is also the per-minute text; a 503 never counts). When every Gemini model is out: Groq only, image
   QA straight to Groq vision, dedupe/shorten helpers use Groq.
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
   - **Discovery sources** (`discover.py`, flag `discovery`, per-source `discovery_sources`, `discovery_share`
     0.25 = how often a lore/mystery pick tries a lead first). Discovery only: the lead's readable source page is the
     ONLY source for the fact ledger. ntsb = `data/aviation.json` (7 strange NTSB aviation incidents, Wikipedia
     source) mixed into the case pool; newspapers = Chronicling America via the loc.gov API (old API retired 2025),
     pages 1850-1928 for `newspaper_queries`, text = the page's ALTO OCR around the match, only if it reads
     cleanly, told as "a newspaper reported..."; serialized fiction and missing/kidnap stories skipped. lore:
     LOC Folklife Today "legends" posts (blogs.loc.gov; returned 403 from the dev sandbox, untested on runners) and
     Dúchas (only with DUCHAS_API_KEY + config `duchas_topic_ids`; its texts are CC BY-NC: facts/retelling only).
     Leads are deduped by source url (history `source`).
   - **Trend picking** (`trends.py`, flag `trend_picking`): lore / mystery / case picks check up to `trend_sample`
     (25) unused topics on the Wikimedia pageviews API (NightFilesBot User-Agent, one request at a time, cached 24 h
     in cache/media-search/trends.json) and take the one whose last-7-day views are >= `trend_min_ratio` (1.5x)
     its 60-day average; else (or on any error) a random pick as before. Log: "Trending pick: ...".
   - `lore`: legends/folklore (`data/lore.json`), told as a STORY, never a fact list (Oct 1, owner: the Nachzehrer
     test was "not postable"): one scenario told the way the legend is told (a death in a village, the family
     falling ill, suspicion, the grave opened, the signs found, the remedy from the source), facts from the ledger
     woven into it; framed as folklore when the source has no specific case; the hook is the scenario's most
     unsettling moment (no "Did you know"). Never source-talk ("according to the sources", "from the sources",
     "folklore held"...: `story.SOURCE_TALK` fails the critic). The critic scores legends with an extra `story`
     (max 20, `CRITIC_MAX_LEGEND`): "is this a story with tension?"; story < 12 fails whatever the total.
   - `inbox/`: the owner can drop links (`inbox/links.txt`: `true <url>` or `fiction <url>`) or pasted
     stories (`.txt`, first line TRUE/FICTION/SCRIPT/SCRIPT TRUE). Inbox items jump the queue and are used once.
     Optional second header line `NOT_BEFORE: <video number>` (e.g. `NOT_BEFORE: 31`): `sources.next_inbox` skips
     that file until `data/counter.json` next_video >= that number; other inbox items and the rotation go on.
     (`inbox/louvre_password.txt` waits for #31.)
     **Topic files** (`sources.next_inbox` -> `story.topic_story`): first line `REMAKE: <topic>` (new lore video about
     a topic we already made), `LORE: <topic>` (a legend) or `TRUE: <topic>` (real story, TRUE STORY rules). Header
     lines: `SOURCES: Title; es:Spanish title` (Wikipedia pages, `xx:` = that language; default the topic),
     `ANGLE:`, `HOOK:` (scene 1 opens with it if sourced; a multi-sentence hook keeps "This is a true story." after
     the whole hook), repeatable `AVOID:`, `NOT_BEFORE: N`, `QUEUE: n` (lower = sooner; topic files without it come
     before other inbox files), `NO_CHILDREN: yes`; other lines = owner notes (instructions, not facts). The topic
     comes from the file, so the used-topic check (mystery.pick_case) is bypassed for that topic only; a failure
     keeps the file queued. REMAKE: old history title/premise/twist + AVOID lines; a draft whose opening / hook
     overlay (or a near-identical title) matches them is rewritten (max 3 drafts); new story id = new images.
     Log "Remake of <old title> (#N): new angle '...'"; history `remake_of` / `remake_angle`; remakes don't count
     toward the story_modes rotation; the old video is marked `remade` in data/backfill.json (never uploaded).
     NO_CHILDREN (`images.sanitize_child_shots`, run with sanitize_victim_shots): any shot with a child / baby /
     cradle becomes its place, empty; child character sheets dropped; a draft putting a child together with harm
     words (`story.child_harm`) is rewritten. Queue (Oct 1): nachzehrer_remake (1), bloody_mary_remake (2),
     lougawou (3, NOT_BEFORE 33, NO_CHILDREN), chalino_sanchez (4, TRUE, en+es Wikipedia, owner HOOK), then
     louvre_password etc. The 2009 Venice "brick" skull is in neither Wikipedia page: only used if research backs it.
   - **Research** (flag `research`, `pipeline/research.py`): before writing case / mystery / lore / inbox TRUE / topic
     stories, Gemini with Google Search grounding (`tools: google_search`) finds 3-6 sources beyond Wikipedia. FREE
     only on gemini-2.5-flash / 2.5-flash-lite (500 requests/day shared; the 3.x writer models have no free
     grounding), so `research_models` = those two; the writer + critic chain is unchanged (Gemini 3.x first, Groq
     last). Only FACT/RUMOR lines backed by the grounding metadata are kept; they're appended to the Wikipedia text
     as a RESEARCH block (so they reach the fact ledger and, for true stories, the fact check); RUMOR = only as
     rumor. story.json `sources[]` (Wikipedia pages + research URLs), history `research_sources` (domains). Usage
     counted in cache/media-search/research_usage.json (`research_daily_limit` 400); a per-day 429, the budget,
     no key or any error = Wikipedia only for the rest of the run, never a failed build.
     Log "Research: N sources (domains...), M grounded lines via <model> (K grounded calls today)".
   - **TRUE STORY rule**: modes `case`, `mystery`, `inbox-true` and inbox `SCRIPT TRUE` files are true stories
     (NOT `lore`: legends aren't true stories; NOT fiction). For those, `story["true_story"] = True` (saved in history),
     scene 1 = hook sentence, THEN "This is a true story." (never first: slow opener; code moves/inserts it),
     captions.py shows a red "TRUE STORY" badge above the hook for 0-3.5 s, and the TikTok caption starts "TRUE STORY:".
     NEVER said twice: `mark_true_story` adds the line only if NO scene says "this is a true story" yet (an owner's
     script split by the planner had it in scene 2 and got a second copy in scene 1); extra copies are removed.
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
     **Repeat guard** (`pipeline/repeat_guard.py`, Oct 5): no topic from the same case / topic / subgenre family as
     any of the last `repeat_window` (15) made videos AND the videos waiting in the buffer (their caption.json), and
     no reused opening line (history `opening`, caption.json `opening`). Families = a recent video's SUBJECT (case /
     source / title with generic words like "The Legend of", "Disappearance of", nationalities removed:
     `repeat_guard._subject`) found in the new topic or vice versa, the same subgenre for fiction / coldcase ONLY
     (for lore / mystery / case the subgenre is just the mode label "legend / folklore": Oct 5 it blocked Baba Yaga as
     "the same topic" as the Cornish Owlman, buffer_fill #12 / #13 / daily #53), or a shared `topic_families`
     keyword (bloody mary, lizzie borden). Checked in next_case, mystery.pick_case (+ discovery leads), pick_subgenre,
     inbox links/files (a repeating inbox item waits) BEFORE any script is written, and once more on the finished
     story (`story._final_problem`): ONE retry with the rejected topic excluded (a local list for the pickers, never
     saved; `save_history` also drops any `rejected_this_run` / "[rejected" entry). Tests on real history:
     `pipeline/test_repeat_guard.py`. (babddea by another model had a 5-full-story retry loop; replaced Oct 6.) `blocked_topics` (["Lizzie Borden"]) is a
     hard block in the same places. `priority_subgenre_probability` 0.15 (was 0.4).
   - Length: TikTok Creator Rewards needs videos OVER 60 s. Config `target_seconds` [61, 68] = the FINISHED VIDEO
     (narration + the 3.4 s end-card tail); `story_words` [138, 152] (prompts get the range from config; the
     Kokoro voice reads ~2.2-2.4 words/sec at speed 1.1). NEVER under 61 s: `render.tail_for()` holds the end card
     longer if a narration (e.g. an owner's exact-words script) is still too short, and the QA gate rejects any
     video under 61.0 s (or over 68.5 s). (Until Sept 30 it was 50-60 s narration: #29 was ~54 s.)
     **Duration fit** (`main.fit_duration`): narration must land in `render.narration_window()` = target_seconds
     minus the tail (57.6-64.6 s). First the voice
     speed is adjusted within `voice_speed_range` [1.0, 1.2] (up to 3 re-voicings; Kokoro's length isn't linear in
     speed, so each try uses the measured speed response); if still outside, Gemini trims/extends by the needed
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
   - **Story upgrade** (flags `story_upgrade`, `critic_pass`, `critic_min_score` 75, `gemini_min_interval` 4 s
     between Gemini text calls): true stories get UPGRADE_TRUE (strangest true detail, viewer can explain it, a new
     verified fact every 5-8 s, case/place name said early, no invented twists), lore gets UPGRADE_LORE. Then
     `critic_pass` (scores hook/clarity/pacing/name_early/payoff/integrity + concrete reasons, max 2 rewrites,
     BEFORE the fact check); still failing = `StoryDiscarded` (next topic / next build; an inbox item or case stays
     queued). Fiction/coldcase: `pick_shape` rotates discovery / strange rule / gradual realization /
     investigation / reversal / uncanny normal (history `story_shape`), `pick_premise` pitches 3 premises and
     rejects vague ones (clarity < 7; one clear sentence + question + visual), "90% normal, 10% wrong", the
     ending explains what happened; the existing 80/100 score loop (3 drafts) is its critic.
   - **Packaging** (flag `packaging`, `pipeline/yt_packaging.py` (NOT packaging.py: that shadowed the pip `packaging` module and broke `import transformers`); replaces the caption style below for new videos and
     backfill uploads): one small LLM call (`story._json_call`) proposes title hook / subject / place / category /
     hook sentence / topic tags / 2 niche tags (whitelist `packaging.NICHE` per kind: lore / true / fiction) / 12
     search phrases; code validates everything, deterministic fallback ("<Subject> | <Category>") if the call fails.
     YouTube title <= 70 chars "<hook>... <Subject> of <Place> #shorts" (no ALL CAPS, max 1 emoji, no clickbait
     words; "true"/"unsolved" never on legends/fiction/solved cases). Description: line 1 hook sentence (different
     wording from the title), line 2 "TRUE STORY" / "Fictional story." (only when it applies), music credit,
     then #topic #place #niche #niche #shorts (<= 8 hashtags with the title). snippet.tags = 10-15 search phrases
     (< 400 chars). Tags: lowercase letters/digits, topic/place tags must appear in the story, no spam (#fyp/#viral),
     no other creators' names, no #truecrime etc. on non-true stories, no #unsolved on solved cases. TikTok caption =
     hook (+ label) + credits + 3-5 hashtags (no #shorts). caption.json carries yt_title / yt_description / yt_tags;
     history + analytics.json store yt_title / hashtags / yt_tags (analytics `by_hashtag`).
   - **Captions** (flag `caption_search_style`, `notify.normalize_caption`; used only when `packaging` is off): line 1 = the search phrase ("What
     happened to D.B. Cooper?") + " | illustrated horror story"; hashtags = 5 topic tags + #illustratedhorror
     #horrorstory (+ #truestory only for true stories); fyp/foryou/viral removed. True stories whose own facts
     show an official ruling or a solved case (`notify.is_resolved`: ruled, convicted, confessed, cause of death,
     accidental drowning...) never get "unsolved" / #unsolved (caption "Unsolved" -> "Strange").
   - **Hook candidates**: the real-story prompts return `hook_candidates` (3 first sentences); the editor pass
     scores them (`hook_scores`, "score | sentence") and `use_best_hook()` makes scene 1 start with the best one
     that passes `hook_problem()`; then `fix_hook()` still runs as a safety net.
2. **Voice**: Kokoro TTS `am_michael` (`voice_lang` "a", start speed 1.1, fitted within 1.0-1.2; the original voice, back after a bm_george test), word timings
   tagged by scene. `voice_samples.yml` renders the same hook in several voices for comparison.
3. **Images** (`images.py`), all free: Cloudflare Workers AI FLUX schnell (10,000 neurons/day, resets 00:00 UTC =
   8 PM New York; Cloudflare BILLS 172.8 neurons per image (response header `cf-ai-neurons`, Oct 2), not the
   57.6 estimate, so ~57 images/day; the ledger uses the header. DAILY LIMIT = ONLY Cloudflare's documented
   answer: code 3036 (HTTP 429) "You have used up your daily free allocation of 10,000 neurons" (`images.cf_daily_limit`;
   docs: developers.cloudflare.com/workers-ai/platform/errors + /pricing "All limits reset daily at 00:00 UTC").
   Until Oct 2 the code also treated an undocumented code 4006 (and, for image calls, any message mentioning
   "neurons") as the daily limit, and every "limit used up" of Oct 1-2 came from the bge-small quota PROBE whose
   answer was never logged, so those may have been false. 429 / 3040 out of capacity / 408 / 5xx = wait 10 s, 30 s,
   60 s and retry, then skip that one image only; never the day. Every non-200 answer logs status, codes, headers, body)
   -> free HF ZeroGPU Spaces running FLUX.1-schnell (config `image_spaces`, 576x1024, gradio_client like ai_motion;
   shares the daily GPU minutes with the AI hook) -> local SD-Turbo on the runner CPU (`local_image_model`,
   512x896, 2 steps, guidance 0; ~23 s load + ~20 s/image on 4 CPUs; Stability AI Community License: free under
   $1M/yr revenue, register once at stability.ai/community-license). Pollinations and the paid HF router were
   removed (always 402). The render upscales everything to 1080x1920 with lanczos. Log shows the source of every
   image and the local model's total time. `preflight()` runs BEFORE the story: tiny Cloudflare quota check; if
   it's out, it tests the Spaces and goes on as a **low-quota build** (never skips a slot for quota alone).
   **Neuron ledger** (`pipeline/cf_budget.py`, cache/cf-usage/usage.json, Actions cache `cf-usage-*` saved even on
   failed builds): neurons per UTC day split tests / production; log "Cloudflare today: N/10000 (tests N,
   production N)". Test builds may use `cloudflare_test_share` (0.35) of `cloudflare_daily_neurons`; a fresh test
   whose video wouldn't fit (scenes x shots x 172.8) runs without Cloudflare (real media + library + local gap
   fillers; tests never use the Spaces), and a test that hits the cap mid-run switches off Cloudflare.
   **Low-quota build** (Cloudflare out in production, at preflight or mid-run): real media first (library / stock /
   archive) + Spaces + max 6 SD-Turbo gap fillers, no early stop; log "Low-quota build: N real, N AI", history
   `low_quota`. It ships only if the full QA gate passes. A QA failure that is only visual (variety) = "waiting
   for image quota" alert: not counted toward the 2-strikes skip, the story stays in the checkpoint and its SD-Turbo
   shots are deleted so Cloudflare redraws them; a scene left empty after its redraw = the same wait.
   If Cloudflare is out (or hits its limit mid-run), at most 2 shots per scene for the rest of the run.
   **2 images per scene** (`shots_per_scene` 2, was 4; 3-4 still work if configured): shot a = the narration's
   main visual, shot b = a DIFFERENT subject/action/angle of the same words (render motion covers the rest).
   Quota order: every scene's "a" shot first, then every "b", then "c"/"d", so running out of quota (or the local
   time budget) loses extra cuts, never whole scenes. SD-Turbo is a GAP FILLER only: max `local_image_max` (6; ChatGPT's 12 reverted Oct 5)
   local images per video (test builds too). No early stop any more (low-quota builds): a scene still empty after
   its redraw = `images.ImageQuotaWait` (ntfy "waiting for image quota"; the checkpoint keeps story + narration).
   Hook shot (scene 0 shot a): up to 3 draws (new seed, then `build_simple_prompt`) before it's dropped.
   Cloudflare daily cap vs short rate limit are told apart (short limit = wait and retry).
   A Space quota error marks the Spaces out for the run; the local model is always the last step.
   **Shot rules** (`pipeline/shot_rules.py`, run once in main.py right after the story is written): legends get
   their creature as a character (fixed look; LLM, else a plain no-gore fallback) SHOWN by name in >=
   `lore_creature_shots` (3) shots incl. the hook shot 0a and the twist scene; the hook + twist scenes always have
   a real subject (person / creature / story object in the moment); filler shots (a texture, surface, wall,
   threads, or a generic object "resting on a table") are rewritten (one LLM call, template fallback). These shots   are locked AI (`story["_ai_only"]`): library, stock, archive and honest place shots never take them. Log
   "Creature on screen: '<name>' in N shot(s) (AI only), hook shot yes".
   **No cross-scene borrowing** (Oct 1: a woodcut ran 12 s over two scenes): a scene whose shots all failed QA is
   REDRAWN (main shot, a new seed, every source still usable); if it still has nothing, the build waits for the
   quota (Cloudflare out) or fails; another scene's picture is never stretched over it (`MAX_FILLS` 1).
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
   brand / person identity (a painterly "old downtown hotel" is fine for the Cecil Hotel), and NEVER fails an image
   for its art style or quality alone; NO only for wrong subject/action/setting, several panels, garbled text or
   broken anatomy. "YES / NO: reason". Paced to
   `image_check_per_minute` (10); a 429 skips QA for that image only (qa=SKIPPED); never fails the build.
   Fallback images always get QA (waits a few s for the slot); Cloudflare images only when a slot is free right now
   (`image_check_cloudflare`), so fallbacks keep the quota. NO = rejected (file renamed `*.rejected*.png`, never
   used): after a Cloudflare NO the fallbacks draw it; after a fallback NO the next source tries once with a
   simpler prompt (`build_simple_prompt`); the same prompt is never sent twice; one try per provider (no blind
   retries). Also refused: files < 256 px or landscape. A shot with no usable image gets a virtual shot (75% crop)
   only from the SAME scene and the same place (never a cabin image for a forest shot); a scene with no image at
   all is redrawn (see No cross-scene borrowing), never filled from another scene.
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
   **Visual source order** (log "Visual sources: N reused, N archive/stock, N AI", history `visual_sources`):
   asset library -> real media (stock / photos / archive prints) -> AI. Existing QA on everything.
   **Asset library** (`pipeline/library.py`, flag `asset_library`): after a classic video enters the buffer,
   `record_video` stores every shot that clearly PASSED QA (AI: `story["_shot_qa"]`; real media: `.json` qa) in the
   GitHub release **"assets"** (`<id>.jpg` / `<id>.mp4` + `index.json`; test builds never write): source, license,
   attribution, url, description (the shot), tags, style (painted / stock_video / archive_print / photo), setting
   (interior / exterior + place words), era bucket (`era_of`: pre1800 / 1800s / 1900-1949 / 1950-1999 / modern /
   folk; nature shots "any"), subjects, character_specific, CLIP embedding (float16), times_used, last_used_video /
   seq, uses [position, crop, grade, move]. Embeddings: openai/clip-vit-base-patch32 (benchmarked against
   google/siglip-base-patch16-224 on 4 CPUs: same top-1 0.93 / P@3 0.69 on 41 Openverse/LOC images, 60 vs 237
   ms/image, no sentencepiece). `fill_shots` (before media.fill_shots) reuses an asset only if: the shot has no
   story character / person (never a named person/creature across stories; such assets are flagged and never
   reused), style allowed for the story, interior/exterior equal, same era (or "any"), times_used < 4
   (`asset_max_uses`), not used in the last 10 videos (`asset_reuse_window`), not used at the same position
   (early/middle/late) before, CLIP similarity >= `asset_min_similarity` 0.27 (63% of true matches, 1% false), then
   the normal QA; max `asset_reuse_max_per_video` 6; the hook (0a) is always fresh. Each reuse gets a new crop
   (left/right/tight/top/bottom/center) + grade (cool/warm/dark/faded/base) than its earlier uses, and render's
   `_pick_move` avoids its earlier camera moves (`scene_XXl.reuse.json` avoid_moves; every picture's move is
   written to `scene_XXl.move` for the library). Log "Reused asset <id> (use N)". `asset_library_max` 800 (used-up
   and least recently used pruned). HF cache key hf-models-v4 (+ CLIP).
   **Library of Congress** (`media.loc_print` / `loc_photo`, no key, loc.gov JSON, 3 s between requests
   `loc_min_interval`, max 4 item lookups per search): rights from the item page: public domain / "free to use and
   reuse" / "No known restrictions on publication" (flag `loc_accept_no_known_restrictions`); rejected:
   "publication may be restricted", "rights status not evaluated", missing / unclear. Stored: item url, title,
   creator, date, rights text. **Openverse** (`media.openverse`, /v1/images/, license pdm,cc0,by only, never NC/ND/SA,
   not mature): id, provider, creator, urls, license + license URL, attribution; CC BY credits (with license URL)
   go in the YouTube description. **Archive prints** (`archive_print`, flag `real_media_sources.archive`, max
   `archive_max` 3 per video): for legends and stories set before 1950 (`library.archive_story`), a no-person shot
   tagged stock_video first tries LOC prints -> Openverse with `media.archive_query`: 2-3 concrete nouns + ONE
   print term chosen per shot (apparition / macabre engraving / etching / woodcut / folklore illustration...) from
   the story's culture (`culture_of`: Japanese stories get ukiyo-e only, European ones woodcuts / engravings,
   others neutral terms). Graded with `GRADE_PRINT` (highlights crushed, desaturated toward teal/amber, vignette,
   grain) so prints sit next to painted shots; QA fails colour calibration charts, rulers and scan borders (LOC
   scans often show Kodak strips). real_photo also searches LOC photos (true stories only, as before).
   **The planner's source tag is NOT trusted** (Groq tagged every shot "ai"): `media.auto_tag` re-classifies every
   shot after planning, for every story incl. inbox SCRIPT / TRUE SCRIPT (flag `real_media_auto_tag`): no story
   character / person + atmosphere, place or object -> stock_video; a named real place/object in a TRUE story ->
   real_photo (query = the name); else ai; the hook (0a) stays ai. scene_plan.txt has few-shot tagging examples.
   **Cloudflare out** (daily limit, no token, or a test build without Cloudflare images; flag
   `real_media_when_cf_out`): every eligible shot tries real media first (`stock_video_max_share_cf_out` 1.0),
   then Spaces, then SD-Turbo (max 6, test builds too).
   **Real victims** (flag `no_victim_images`, `images.sanitize_victim_shots`, run before media search and image
   generation; also a hard rule in scene_plan.txt + mystery.py): in true stories a shot showing a real victim's
   death, body, body parts or remains ("Elisa floats in the tank", "a pale hand breaks the water") is rewritten to
   the place/object with no people (the tank, the open hatch, the dark water). Ordinary hands ("presses buttons
   with trembling hands") are not touched.
   **Real-media QA** (`images.REAL_QA_QUESTION`, `check_image(kind="real")`): the poster is ONE frame from the middle
   of the clip; the question says so and fails only for a wrong subject/setting, visible text/logo/watermark, a
   close-up real face, or a split frame; never for colour, lighting, warm/cold tones, time of day or style (our
   grade fixes those). Archive prints are asked "Does this image depict: <the shot>?" and must show what it MEANS,
   not share a keyword (a coin workshop is not "a coin in a dead man's mouth"). Stock clips for legends / fiction /
   pre-1950 stories (`media._historic_note`) fail anything modern (cars, asphalt, signs, power lines, modern
   windows/lamps/clothes, tourists, postcard streets), bright sunny daylight / blue sky or clean touristy footage. Groq vision QA is paced (`groq_vision_per_minute` 20) and a 429 waits (Retry-After, max 30 s)
   and retries up to 3 times instead of skipping. Stock queries = 2-4 concrete nouns (`media.clean_query`: no
   framing/mood/colour words), then a broader 2-noun query; a clip that failed QA is never retried.
   Stock clips must not show a person as the main subject (QA request "NO PERSON as the main subject"; a stranger
   walking a hotel corridor over "Elisa Lam checked in" read as the victim), and a document / report / sign as the
   main subject fails like text. real_photo only for a proper name the NARRATION itself says (auto_tag and place
   shots): a capitalised planner phrase ("Coroner Report") had pulled another person's toxicology report.
   Stock-clip QA also gets the story's place/era ("STORY SETTING: Los Angeles, 2013; <the shot's location look>",
   `media._setting_note`) and fails a clip whose setting or era clearly doesn't fit (a modern luxury living room
   for a 2013 coroner scene).
   Stock clips get TWO single-frame QA checks (1 s in = what viewers see first, and the middle); the first NO
   rejects the clip (a stranger's close-up face at the start slipped past the middle frame).
   Real photos are pinned to the story's place: `media.place_context` adds the city the narration gives in the same
   sentence ("Cecil Hotel office" -> "... Los Angeles"), and a result whose title names a world city/country the
   story never mentions is skipped (the London "Hotel Cecil 1896" had been used for the LA hotel), and the photo's
   title must contain the query's distinctive name word (`media._missing_name`: "Cecil"; a London "roof, showing
   Waterloo Bridge" photo had passed QA as "Cecil Hotel roof").
   QA judges the UNGRADED frame (`scene_XXl.qa.png`, deleted after QA; grain/vignette confused it) against the
   searched concept (stock: the cleaned query; photo: "<name> (any view: outside, inside, entrance, detail)"),
   not the story's exact moment. Reflections/ripples/windows are not "panels". At most
   `real_media_max_candidates` (4) candidates per shot. Shots about screen content / brands / logos / footage
   ("netflix logo", "news ticker") are tagged ai (no stock clip matches them).
   **Honest place shots** (flag `honest_place_shots`, Cloudflare-out days only): a scene where every shot shows a
   character gets its 2nd shot replaced by its own known location, empty (real_photo for a named real place in a
   true story, else stock_video). After the search, a second pass gives every scene that still has no real media
   one place shot of its own location (photo query: with the story's city first, then the plain name). On
   local-only days SD-Turbo draws in this order: scenes with NO image at all (main shot), the hook 0a (only 1 draw,
   not 3, when scene 0 already has real media), empty scenes' 2nd shots, then extra cuts. Never invents a place; if scenes still lack images, "waiting for image
   quota" is the correct result (the early-stop count skips scenes that already have ANY image, real media incl.).
4. **Render** (`render.py`, `effects.py`, `ai_motion.py`), FFmpeg 1080x1920:
   - Hook shot (Oct 6): NEVER the AI clip: shot 0 always starts on the original sharp still with 3D parallax
     (`render.py` pops ai_targets[0]); the ZeroGPU clip, upscaled from <= 576 px and smeared by the video model, made
     the first ~2 s look blurry (Lougawou 2026-10-06_0144). Fast mode's twist clip stays. Note: `start_blur_problems`
     did NOT catch that smear (sharpen + grain + scanlines read as detail); it only catches plain low-res / blur.
     Old text: real AI animation via free Hugging Face ZeroGPU Spaces (list in config `ai_motion.spaces`,
     live API discovery, never hard-wired) -> falls back to 3D parallax -> falls back to Ken Burns zoom.
     The Space is asked for its HIGHEST 9:16 size (`ai_motion._size`: the max its API publishes, height <= 1280;
     1024x576 if it publishes none; a refused size -> once more at its default). `render._ai_into_still`: a clip
     under 400 px wide is skipped (parallax); else max 2 s of it (lanczos upscale + light unsharp; the final pass
     adds the same grain as every still), then a 0.5 s crossfade into the ORIGINAL high-res still it came from,
     which continues with the normal parallax ("the clip freezes into the picture").
   - Other shots: Depth Anything V2 Small (Apache-2.0, CPU) 2.5D parallax; fog + dust overlays; light flicker
     only on scenes whose narration mentions lights; camera shake on the twist.
   - Cuts land on punctuation; min shot 1.2 s. Captions: one word at a time, white, centered (Anton font).
   - **Visual A/B test** (flag `visual_ab`, `visual_modes` [classic, fast, analog]; `render.pick_visual_mode`
     rotates per buffered video; build.yml input `visual_mode` / env VISUAL_MODE forces one; saved as
     `visual_mode` in story, caption.json and history for the analytics). classic = as before. fast = a new
     framing of the same picture every 1.5-2 s (punch-in / detail / left-right crops, never the same framing twice
     in a row, varied moves), hard cuts on punctuation / key words, whip-pan (slide) or white flash at scene
     changes, zoom punch on key words, shake at the hook's end + the twist, AI motion on hook + twist (max 2).
     analog = classic cutting + VHS look (soft blur, chroma bleed, heavy grain, scanlines, camcorder timestamp +
     "PLAY" via the captions .ass). No fake emergency-broadcast screens or alert tones.
   - Sound effects: real recordings in `assets/sfx` (BigSoundBank / Freesound CC0). `clean_sfx()` removes any
     sound the narration doesn't literally mention; max 4; never on the hook.
   - Music ducked under the voice, per-track volumes in config. Video bitrate capped (TikTok API limit 64 MB).
5. **TikTok** (`tiktok.py`): own developer app "Night Files" (sandbox). `tiktok_mode: "draft"`: videos go to
   the owner's TikTok inbox and he posts them himself (account stays PUBLIC). Direct Post app review was
   submitted, but TikTok's guidelines reject "tools that upload to your own/team accounts", so expect rejection.
   Plan if needed: an approved third-party posting service, or turn this into a public product later.
   **YouTube Shorts** (`youtube.py`, Data API v3, scope youtube.upload): the same mp4 right after TikTok, in
   publish.py. Title / description / tags from yt_packaging.py (caption.json yt_title / yt_description / yt_tags;
   older buffer entries: story title + " #Shorts" and the TikTok caption), category 24, containsSyntheticMedia true, not made for kids, privacy from
   config `youtube_privacy` (`youtube_enabled` switches it off). Uploads from an UNVERIFIED Google Cloud project
   are forced private until YouTube's API audit passes; the log/alert shows the privacy YouTube returned.
   TikTok and YouTube are independent: the video leaves the buffer if at least one worked (never double-posted);
   only if both fail does it stay for the next slot. Refresh token: run `pipeline/connect_youtube.py` once
   locally (OAuth consent screen must be "In production", or Google expires the token after 7 days).
   **YOUTUBE PAUSED (Oct 6, owner)**: the Google account that owns project night-files-510012 has its Google
   Cloud access restricted (appeal submitted). Config `youtube_paused` true until the OWNER says it is restored. Do
   NOT create or suggest new Google projects or credentials. While paused: publish.py makes no YouTube call
   (TikTok only), `pipeline/youtube_pending.py` records each video in `data/youtube_pending.json` and keeps its mp4
   + caption.json in the release **"youtube-pending"** (the buffer and the 7-day artifacts would lose it; #38
   Lougawou is stashed from its artifact by `stash()`); history `youtube` = {"pending": "youtube_paused"}; at most
   ONE ntfy a day about the pause; yt_backfill.py (TikTok-era backfill) only stashes, no upload; analytics.py exits 0.
   push_state.sh merges youtube_pending.json (uploaded beats pending). On restore: set `youtube_paused` false;
   every daily post then runs `upload_some()`: oldest first, max `youtube_pending_per_day` (6) per UTC day, history
   gets the YouTube link, the release copy is deleted. Quota note: 6 backfill + 2 daily uploads ~ 12,800 units >
   YouTube's 10,000/day default, so some days a quota error leaves the rest pending for the next day (non-fatal).
6. **Notify**: ntfy phone alert with caption + pinned comment + YouTube link (`NTFY_TOPIC`).
7. **Analytics** (`analytics.yml` daily 09:17 UTC + manual, `pipeline/analytics.py`, flag `analytics`): YouTube
   Analytics API per Short (creatorContentType==SHORTS): views, engagedViews, averageViewDuration,
   averageViewPercentage, likes, comments, shares, subscribersGained, matched by YouTube id to history
   (video_number, mode, visual_mode, story_shape, writer) -> `data/analytics.json` (+ by_mode / by_visual_mode
   summaries). Needs the yt-analytics.readonly scope (connect_youtube.py now asks for it; re-run once and update
   YT_REFRESH_TOKEN); without it the log says "analytics scope missing" and it exits 0. Any other API / token
   failure prints the exact error and exits 1 (red run).
   Status Oct 5: red every day since Sept 30 because the YouTube Analytics API is NOT ENABLED in Google Cloud project
   685200856292 (enable it in the console). `yt_check.yml` now reads the token's real scopes from Google's tokeninfo
   (it used to echo the requested scopes as "granted") and fails if yt-analytics.readonly is missing.

8. **YouTube backfill** (`yt_backfill.yml` 04:20 / 08:20 / 20:20 UTC, `pipeline/yt_backfill.py`, state
   `data/backfill.json`): uploads the videos that were on TikTok before YouTube upload worked. Every run first copies
   queued videos out of their 7-day build artifacts into the release **"backfill"** (`<stamp>.mp4` + `<stamp>.json`),
   then uploads ONE (max `yt_backfill_per_day` 3/day; oldest first; public; same title/description/tags as daily
   posts via yt_packaging.py + youtube.upload; yt_backfill.yml has GEMINI/GROQ keys for it). Only videos the owner PUBLISHED on TikTok: `data/tiktok_posted.txt`
   (one title or caption per line, fuzzy-matched; unmatched lines in backfill.json `unmatched_lines`); no file =
   backfill PAUSED, nothing uploads (log "Backfill PAUSED"). A TikTok publish_id only means "sent to drafts", never
   "published" (the Oct 3 `yt_backfill_trust_publish_ids` path was removed Oct 5; it had uploaded 6 videos from
   publish ids: Footsteps on the Ceiling, Jim Thompson, Manananggal, Platform Four, Beast of Gevaudan, Backward Shadow). Waits within 60 min of a publish slot / post or while daily.yml runs; skips titles already on the
   channel (history, backfill.json, channel list when the token allows); `render.qa_gate(backfill=True)` (no 61 s
   floor, no TikTok size cap). Known bad: #27 airplane-cabin D.B. Cooper (panel grids), #28 frozen gavel. #26 Louvre
   was uploaded by hand (yt_upload_test, Khcw2HPvxTU). When nothing is left: drafts not in the list are skipped,
   `done` is set and the workflow disables itself (re-enable + remove `done` to run again).

## Buffer (buffer_fill.yml fills it, daily.yml posts from it) — workflows as of Oct 5
- **build.yml, deferred_test.yml and test mode are GONE** (ChatGPT, Oct 2: 28b2b8b, 4181116, 130adcb). There are no
  test builds; every run of main.py is production. Older notes below that mention build.yml / test builds /
  `--test` / TEST_MODE describe code that no longer runs.
- `buffer_fill.yml` (producer, cron `10 */6 * * *`, input `target_buffer` default 2): resumes an unfinished
  checkpoint first, else builds one video when fewer than 2 wait on the GitHub Release **"buffer"** (assets
  `<stamp>.mp4` + `<stamp>.json`). Inbox items / cases / history are marked used when the video enters the buffer.
  Then (always) it saves the Cloudflare ledger cache (`cf-usage-*`), the rotated TikTok token, and history.json /
  counter.json / missed_slot.json with `push_state.sh "Buffer story"` (until Oct 5 it saved NOTHING: posts #34-#37
  never reached history, so Lizzie Borden was picked 4 times and #34-#36 were the same story 50faf2e6f0f0; entries
  rebuilt by hand, `history_rebuilt`). It also makes up a missed slot (env MAKEUP_POSTS=1 -> `publish.post_missed_slot`),
  so it has the TikTok/YouTube secrets.
- **History hard check** (`pipeline/history_check.py`, last step of buffer_fill.yml and daily.yml): every video this
  run buffered (`.built`) or posted (`.posted`) must have its history entry on origin/main; else the run fails red +
  ntfy "history NOT saved". publish.py also rebuilds a missing entry from caption.json at post time (+ ntfy).
- `notify.notify` never crashes on a missing story (a failure while writing it): clean "FAILED" alert with the
  error text.
- `daily.yml` (slots 15:40 / 00:40 UTC; GitHub's cron runs it 3-5.5 h late): if the buffer is empty (or a checkpoint
  is pending) it first builds one video with main.py (`continue-on-error`, so a failed build never blocks posting a
  buffered video), then `pipeline/publish.py`: oldest buffered video -> TikTok + YouTube Shorts ->
  delete from buffer -> both results + "posted" time saved in history -> phone alert with the YouTube link
  (+ "buffer low" alert at 1 left). Only if both platforms fail does the video stay in the buffer.
- **Missed-slot make-up** (`publish.makeup_blocker`): a missed slot (data/missed_slot.json, max
  `missed_slot_max_hours` 24 h old) is made up by a build only when the buffer then holds 2+ videos (the next
  regular slot keeps one) and no post is within `min_post_gap_hours` (3) before (history `posted`) or after (next
  slot in `publish_slots_utc`); otherwise the file waits for a later build. A slot run that posts late (cron delay or a
  manual daily.yml run) serves the most recent regular slot: if that is the recorded missed slot, the file is
  deleted (`publish._late_slot_served`), so one missed slot is never posted twice. (Oct 1: GitHub's cron skipped the 15:40
  daily run entirely; its missed_slot.json was written by hand.)
- **Duplicate-post guard** (`publish._posted_entry`, Oct 2 freeze fix): a buffered video whose history entry
  (same stamp or story_id) already has `posted` is never posted again; only its buffer removal is retried. A failed
  `buffer.remove` after a successful post sets history `removal_pending` (cleared when a later run removes it).
  `post_missed_slot` deletes missed_slot.json only when the make-up post returned 0; a failure keeps it.
- **Concurrency groups**: build.yml, daily.yml, buffer_cleanup.yml (everything that writes history.json or the
  buffer) share `night-files`; analytics.yml (`analytics`), freeze_summary.yml (`freeze-summary`) and
  yt_backfill.yml (`yt-backfill`) have their own, so reports never wait behind or replace a build / publish run.
- **Empty buffer at a slot** (Oct 5 restore of what 249ea6a / 0bc8abb removed): daily.yml's own build made no video
  either, so publish.py writes `data/missed_slot.json` {"slot", "at"}, sends "publish FAILED (slot missed)" and the
  run is red. When buffer_fill.yml then buffers a video, main.py (MAKEUP_POSTS=1) calls `publish.post_missed_slot()`
  with the make-up rules above. Both workflows save history.json + missed_slot.json + counter.json with
  `pipeline/push_state.sh` (merge_history.py + 3 push tries), `if: always()`.
- **Video numbers** (`data/counter.json` {"next_video": N}): GitHub run numbers are per workflow, so the bot keeps
  its own post counter. `publish.take_video_number()` gives the number only once a video actually went out
  (TikTok or YouTube accepted it, also for a make-up post from build.yml); test builds, failed publishes and
  empty-buffer slots never use one. The number is in history.json (`video_number`), the ntfy title ("#26 ..."),
  the logs and the artifact name (`video-26`). Before posting, a video is known by its story id (build
  artifacts `build-<story_id>` / `test-<story_id>`, buffer caption.json `story_id`). push_state.sh commits
  counter.json with history (higher next_video wins). #26 = the Louvre heist, #27 = D. B. Cooper (backfilled);
  the counter continues at #28.
- Note: while the repo is public, buffered (unposted) videos on the release are publicly downloadable.
- README.md (overview) and SETUP.md (secrets, one-time connections, tests) are kept in line with this file;
  CLAUDE.md stays the main source.

## Reliability (build side)
- **Render join**: every clip (AI motion, parallax, Ken Burns) is normalized to 1080x1920 / 30 fps / yuv420p /
  SAR 1 / one timebase, video only, before the xfade chain (`render.NORMALIZE`, `_join`), so odd AI clips can't
  crash it.
- **Checkpoints** (`checkpoint.py`, Actions cache `ckpt-<run id>`): a build keeps story.json, the narration
  (wav + timings, tied to a hash of the text + speed) and every finished image in `cache/checkpoint/`. A failed
  build's next try resumes the same story and only makes what's missing. Success writes `done.json`, so an older
  cache entry is never resumed; a story already in history is never resumed. Test builds skip checkpoints.
- **QA gate** (`render.qa_gate`) before the buffer: 1080x1920, video 61-68 s (hard floor 61.0 s), audio
  stream, integrated loudness -18..-12 LUFS (ffmpeg ebur128; the mix is loudnormed to -14), caption lines in the
  burned-in .ass cover the words, 5-64 MB.
  **What blocks (Oct 5)**: HARD = `main.HARD_QA`: one picture over 20% of the video, a frozen / one-image finished
  video, and a **blurry start** (`render.start_blur_problems`: median contrast-normalised sharpness of 4 frames in the
  first 2 s must be >= `qa_blur_min` 0.06 and >= `qa_blur_ratio` 25% of the rest of the video; calibrated: native
  0.47, 576 px upscale 0.19, VHS analog 0.21, 270 px upscale 0.04). A hard fail is never buffered (twice = story
  skipped for good; low-quota builds wait for quota). Everything else in qa_gate (duration, loudness, captions, size,
  too few distinct pictures) is REPORT-ONLY since ChatGPT's 130adcb: logged + ntfy, the video still ships. The
  separate production gate below (file / duration / streams / provenance) is also hard.
  **Visual variety** (`render.visual_problems`, after video #28 froze on ONE gavel frame for 56 of 62 s):
  (1) shot list: seconds per SOURCE picture (`images.source_key`: content hash; virtual crops point to their
  source via `scene_XXl.origin`, fast-mode framings / borrowed / copied files are the same picture) -> fail if
  one picture > `qa_max_visual_share` (0.2) of the video or fewer than `qa_min_visuals` (8 per 60 s) distinct;
  (2) the FINISHED mp4 (`render.frame_visuals`: 2 frames/s, captions/logo/bottom masked, contrast-normalised,
  near-identical frames grouped) -> fail if one look > 20% or unchanged for > 20% of the duration, or too few
  looks. Every video logs "Visuals: N distinct picture(s); longest on screen ..." and "Final frames: ...";
  history saves `visuals`. No cross-scene borrowing any more (`images.MAX_FILLS` 1): an empty scene is redrawn
  or the build waits / fails.
  **Join** (`render._join`): xfade offsets come from each clip's REAL frame count (not summed word timings) and
  transitions are whole frames; a joined video shorter than its shots raises. Cause of #28: rounding drift over
  31 fast-mode cuts put an offset past the stream end, ffmpeg 6.1's xfade ended the chain at ~6 s, and the
  final pass (looping logo overlays) held the last frame (the gavel stock clip) for the rest. Fail = not buffered + ntfy alert; a duration failure drops the saved
  narration so it's re-fitted; the SAME story failing QA twice is skipped for good (history `skipped` + reason).
- **Concurrency**: build.yml and daily.yml share the group `night-files` (never write history.json at the same
  time); build cron is :50 every 3 h, just after the publish slots. Pushing history uses
  `pipeline/push_state.sh` -> `merge_history.py` (applies this run's new/changed entries onto origin/main's file)
  + push, 3 tries;
  no rebase conflicts. Note: GitHub keeps only ONE pending run per concurrency group; a newer queued run
  replaces an older pending one.

## EXPERIMENTAL: cutout render style (`cutout.py`, off by default)
- Switch: config `render_style` (classic | cutout), build.yml input `render_style` (env RENDER_STYLE),
  `cutout_for_modes` (e.g. ["coldcase"]). Any cutout failure -> logged, the video renders classic; a FORCED
  cutout (RENDER_STYLE=cutout) never ships classic: the build fails with "Cutout render was forced but failed in
  <where>: <why>", and stops before the story if Cloudflare's daily limit is already used up (cutout is
  Cloudflare-only). A forced cutout TEST that doesn't fit the tests' share (`cutout_hard_max_images` 20 x 172.8 =
  3,456 of the 3,500 test neurons: it must be the day's first test; each cutout draw also checks the cap) or
  finds Cloudflare out is deferred instead of failing: main.py writes output/*/deferred_test.json, build.yml commits
  it to data/deferred_test.json, and `deferred_test.yml` (00:03 / 00:23 / 02:13 UTC) starts build.yml with the same
  inputs once and deletes the file. Legends whose shots name no figure get their creature (+ one adult witness) as the cast
  (`derive_characters`, aliases corpse/creature/revenant...); a character-less stage never repeats an empty plate.
- Characters (max 2, adults) = a pose set drawn once (Cloudflare, NO seed: FLUX schnell on Workers AI answers 400
  "'/seed' not allowed"; config `cloudflare_seed` re-enables it; look word-for-word, plain gray
  background), each pose checked against pose 1 (`images.same_character`, Gemini / Groq vision; NO -> redraw up to
  2x, else dropped -> fallback pose), cut out with rembg (isnet-anime, u2net; gray-key fallback; a nearly empty
  cut-out drops the pose), composited on empty plates (wide/medium/detail per location, reused). Inserts = AI
  object close-ups; screens (phone chat / note / laptop) drawn by code with only words the narration says.
  Compositor: plate 80% brightness/saturation, character 107%, room tint, rim light, contact shadow, breathing,
  enter/walk/turn moves. Budget `cutout_max_images` 18 (hard `cutout_hard_max_images` 20; was 22/26 before the 172.8-neuron finding). Review artifacts:
  poses_sheet.png (labelled "Who: pose"), plates_sheet.png ("location / kind"), contact_sheet.png, summary.txt.
  Inserts/plates: no text requests (`images._no_text`), "blank unmarked surfaces", QA fails visible letters (run
  36848613329 had garbled sign/tombstone lettering). STATUS (Oct 1): offline end-to-end passes; runner test runs:
  36847389674 = seed 400, 36848613329 = QA fail (one empty plate 27%, fixed), 36850352869 = Cloudflare daily
  limit used up; next test right after 00:00 UTC with `inbox_file=nachzehrer_remake.txt`. Not used in production.

## FEATURE FREEZE (Oct 2-8, 2026)
- Owner's rules: bug fixes only, no new features, NO test builds unless production fails; Cloudflare (~57
  images/day) is production's alone (the deferred cutout test was cancelled; cutout stays untested/off).
- `freeze_summary.yml` (00:52 UTC = ~9 PM New York, `pipeline/freeze_summary.py`): one ntfy a day with posts,
  builds, buffer, missed slot, hold and yesterday's Cloudflare ledger; appended to `data/freeze_log.md` (the
  freeze log; stops itself after day 7). Replies to the owner during the freeze: daily summaries only.
- Production hold: lifted after the first supervised production build (build.yml input `ignore_hold`, Oct 2
  ~07:10 UTC, after Gemini's 07:00 UTC quota reset) passes QA, then left lifted.
- Cloudflare early-limit investigation (Oct 2: "daily limit used up" at 00:44 UTC after only 16 images): every
  call logs "Cloudflare call: HTTP ..., cf-ai-neurons=..., ledger ..." (+ any quota/rate-limit headers); the
  preflight, every 4006 and the end of image generation log Cloudflare's own GraphQL analytics count
  (`cf_budget.analytics_report`, dataset aiInferenceAdaptiveGroups; needs Account Analytics: Read on the token,
  else the log says "Cloudflare analytics unavailable"). The ledger keeps the last 8 days (`past`).

## Schedule
- 2 videos a day, **11:40 AM and 8:40 PM New York**. GitHub's own cron was unreliable (4 h late / skipped),
  so the plan is **cron-job.org** calling the `workflow_dispatch` API for `daily.yml` with a fine-grained token
  (Actions: read & write). Only remove the `schedule:` block from daily.yml AFTER cron-job.org is tested.
- `build.yml` has `timeout-minutes: 60` and HF cache key `hf-models-v4` (SD-Turbo + CLIP for the asset library); `daily.yml` 15 min.
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


## Ruflo implementation ledger, 2026-10-02

This section is cumulative. Every Ruflo-related commit made so far is recorded here so the repository remains self-documenting and the next implementation can start from a known state.

### Commits completed

1. `55dba71653467bce61c0e72867f5d189e2977548` - Add concrete Ruflo first-stage integration design. Established the first-stage architecture and explicitly kept Ruflo outside production.
2. `157a9875aa0945d0dfe8fc0fcaaeaa5ff3a6cbb9` - Document Ruflo integration plan and safety constraints. Recorded the activation sequence, production boundary, and safety rules.
3. `767242e1f811885ee513a7a3c2ea4359f6527e64` - Add Ruflo integration `pipeline/ruflo_plan.json`. Added the declarative stage/dependency/role map for research through publishing.
4. `9ff04cfce6cc7338525bc0efa49131fd6850f1b6` - Add Ruflo integration `pipeline/ruflo_check.py`. Added the zero-dependency manifest validator and delegation-graph check.
5. `a24cd4f27bc0789dd14b83850bf6ffd79561a93f` - Add Ruflo integration docs. Added the dedicated integration reference and activation boundaries.
6. `4879e18f0a60cdebcdddd1c3b4c1f7fa2cf74481` - Add planner task contract. Defined how Ruflo planning maps onto existing Night Files stages without replacing them.
7. `01cd3726fe82ff8de6663e3777f897daec2cb6bf` - Add researcher task contract. Defined source-backed research, evidence tracing, and folklore/speculation separation.
8. `9f3bda761e04662b2ddee12e5e58277612fdc55f` - Add story-writer task contract. Defined narration generation/revision under fact-lock, hook, duration, and fiction rules.
9. `a2b1bd4bb8775f97dd39c6725fb8fdaf8c8416b3` - Add visual-planner task contract. Defined shot planning, continuity, and visual safety requirements.
10. `f4099b098e1f32e8ea85af0f30a8114caa8ff01e` - Add QA-reviewer task contract. Defined diagnostic review and failure reporting without bypassing gates.
11. `4d05bc1c3d7efdb8ba362ade2e075125bd50af3f` - Add packaging-reviewer task contract. Defined metadata review while leaving TikTok/YouTube transport untouched.
12. `b7c6a6d9c8cf2737f7fcdc23c0244631cd561210` - Add Ruflo task-contract validator. Added `pipeline/ruflo_task_check.py` to verify all six contracts and their required sections.
13. `e4b61ac216553a1ce0501b16e5274db587aeb216` - Document implemented Ruflo task contracts. Expanded `docs/RUFLO_INTEGRATION.md` with exact files, validator behavior, and current activation state.
14. `0242173df1e81a52e07640c8716a8bce501f7f9b` - Record implemented Ruflo task contracts. Added the cumulative implementation update to `NIGHT_FILES_UPDATE.md`.
15. `6f6d428eb5396b1a1fac34ea2ee53f38262353eb` - Mark Ruflo contract layer implemented. Updated `CLAUDE.md` so future sessions treat the contract layer as implemented, production-disabled.

### Validation state before the next implementation

The repository state has been statically checked from the current GitHub files. The manifest and task-contract definitions are internally consistent. The validators are dependency-free and are designed not to start agents, swarms, MCP, daemons, or publishing.

### Ready state

**Current Ruflo state: contract-ready, production-disabled.**

**Next implementation:** isolated non-production Ruflo execution of exactly one task, with captured output and comparison against the existing Night Files result. Do not connect that execution to `daily.yml`, publishing, TikTok auth, YouTube auth, or the production buffer yet.

The next implementation is considered ready only if it preserves these properties:
- no new production secret unless a verified runtime requirement is discovered;
- no production workflow dependency;
- no automatic publishing;
- no bypass of research, fact-lock, visual QA, duration QA, or packaging safeguards;
- clear artifact/output location for comparison;
- failure of Ruflo remains non-fatal to production.

## Persistent checkpoint/resume fix, 2026-10-03

The recent buffer-fill logs exposed a real gap in the checkpoint implementation. pipeline/checkpoint.py already had the correct idea: keep the story, narration, and finished images after a failed build. The problem was workflow persistence, not the checkpoint data model.

The failed image run explicitly reported that the story was kept and that the next build should continue it, but the buffer-fill workflow did not restore or save cache/checkpoint. The daily workflow restored a checkpoint but did not save the checkpoint cache after the run. That meant a failed run could not reliably hand its unfinished story to the next scheduled producer.

### What changed

- .github/workflows/buffer_fill.yml restores the newest ckpt-* cache before generation.
- .github/workflows/buffer_fill.yml detects cache/checkpoint/story.json without done.json.
- Unfinished checkpoints take priority over starting a new story.
- buffer_fill.yml saves cache/checkpoint after every run, including failures.
- buffer_fill.yml now uses the same night-files concurrency group as daily.yml.
- daily.yml detects an unfinished checkpoint after restoring it.
- daily.yml now generates when the buffer is empty OR a checkpoint is pending.
- daily.yml saves cache/checkpoint after every run, including failures.
- pipeline/checkpoint.py required no runtime change because resume(), save_story(), save_narration(), and finish() already implement the intended state machine.

### Resulting behavior

Run A starts Story X -> story.json saved -> narration saved -> images saved as they finish -> image/provider/render failure -> run fails -> checkpoint cache is saved.

Run B (daily or buffer-fill) -> checkpoint cache restored -> unfinished Story X detected -> Story X resumes -> no new Story Y is started -> completed narration/images are reused -> only missing work is attempted.

If Run B fails again, the checkpoint is saved again. If Run B succeeds, buffer.add() completes the durable queue entry and checkpoint.finish() clears the heavy checkpoint state and writes done.json.

This is specifically designed for the current image-quota failure mode. The recent run stopped at ImageQuotaWait and explicitly logged that the story is kept and the next build continues it. fileciteturn544file0L5-L8

### Commits

- 6c254577529d22d5e763093eda26aa9fe0c76c7a - persist and resume checkpoints in buffer-fill.
- c2f7ec3d481903b5a6e0f8b30b15dbffe5277f73 - let daily runs resume unfinished checkpoints.

### Important limitation

GitHub Actions cache is the persistence layer. A checkpoint is not a permanent artifact in the repository and is subject to GitHub Actions cache retention/eviction. As long as the checkpoint cache is available, the workflows restore it by the ckpt- prefix. A completed story is protected by done.json and by history duplicate checks.

### Validation status

The workflow files were updated directly and re-read from GitHub after the changes. The actual scheduled recovery path has not yet been executed on a failed production run, so the next real buffer-fill or daily run is the live validation.
## Production media tools implementation, 2026-10-02

Two production-capable media integrations are now implemented in an isolated test lane.

- HyperFrames: pipeline/hyperframes_adapter.py wraps a generated Night Files MP4 in an isolated HyperFrames composition, runs the HyperFrames linter, and renders a second MP4. The test pins hyperframes@0.8.100 and uses Node 22. The existing FFmpeg final pass remains the production source of truth until this renderer is compared against it.
- Adobe Premiere Pro MCP: .mcp.json registers the local premiere-pro-mcp MCP server for agent clients. pipeline/premiere_mcp_adapter.py creates a review-only handoff manifest. GitHub-hosted Linux cannot run Adobe Premiere, so the test lane does not claim a live Premiere edit.
- Isolated test runner: pipeline/media_production_test.py runs the existing generator while blocking buffer/history/checkpoint/cache side effects, then exercises HyperFrames and creates the Premiere handoff.
- Test workflow: .github/workflows/daily_media_test.yml is manual only and separate from daily.yml. It never calls publish.py.

Production daily behavior is unchanged. See docs/PRODUCTION_MEDIA_TOOLS.md.


## Buffer-first publishing architecture, 2026-10-02

The Night Files production queue is now the durable source of truth between generation and publishing.

- `pipeline/buffer.py` stores complete `.mp4` + `.json` pairs in the GitHub Release named `buffer`.
- `.github/workflows/daily.yml` checks the buffer before generating anything. If one or more complete videos are waiting, it does not generate another video and publishes the oldest buffered item.
- If the buffer is empty, the daily workflow generates exactly one video. `pipeline/main.py` places it into the buffer, and the same daily run then publishes the next buffered item.
- `.github/workflows/buffer_fill.yml` is the separate producer lane. It runs every six hours and can be manually dispatched. It checks the queue and generates one video only when the queue is below its target, defaulting to two waiting videos.
- The buffer-fill workflow calls TikTok / YouTube ONLY to make up a missed slot (`publish.post_missed_slot`, Oct 5). Its generated video, caption, story, and supporting artifacts are uploaded to the GitHub Actions run.
- `pipeline/media_production_test.py` now uses the real `buffer.add()` path. Media tests therefore queue finished videos for later scheduled publication instead of discarding them.
- `pipeline/publish.py` remains the consumer. After at least one platform succeeds, it removes the buffered pair. Existing history-based duplicate protection remains in place.

This separates **production generation** from **scheduled distribution**. Repeated media tests can build the queue without immediately spamming TikTok or YouTube. The scheduled daily workflow consumes the queue one item at a time.

The buffer is FIFO: oldest complete pair first. A buffered item stays available if publishing fails. A successfully posted item is removed so it cannot be posted again.

Artifacts from the producer/test workflows remain downloadable from their GitHub Actions runs for seven days. The durable media queue is the GitHub Release buffer itself.


## DESIGN.md integration, 2026-10-02

- Added repository-level `DESIGN.md` as the visual source of truth for future Night Files UI surfaces.
- It follows the DESIGN.md convention used by VoltAgent/awesome-design-md: visual theme, tokens, typography, components, layout, depth, responsive behavior, and explicit do/don't rules. It is a convention/reference, not a dependency or runtime package.
- Before changing any dashboard, buffer viewer, run monitor, media review surface, integration page, or other UI, read `DESIGN.md` first.
- The Night Files design intentionally does NOT copy one external brand. It uses a dark production-control-room aesthetic tailored to this project.
- The buffer-first architecture is part of the UI contract: Generate -> Buffer -> Scheduled Publisher -> TikTok / YouTube.
- External media review must expose provenance/license metadata. yt-dlp downloading a file does not make that file copyright-free.


## YouTube backfill eligibility update, 2026-10-03 (REVERTED Oct 5)

REVERTED by the owner on Oct 5: only videos listed in data/tiktok_posted.txt are backfilled; without the file the backfill is paused. A publish_id only means "sent to drafts". The text below is the Oct 3 history.

The YouTube historical backfill no longer hard-depends on data/tiktok_posted.txt when the explicit config flag yt_backfill_trust_publish_ids is enabled. The current config enables this mode because data/backfill.json already contains tiktok_publish_id values captured during TikTok publishing.

Rules:
- data/tiktok_posted.txt remains the preferred explicit owner inventory when present.
- If that file is absent, queued videos with tiktok_publish_id are eligible under the explicit trust flag.
- Videos without a recorded TikTok publish ID remain ineligible.
- Existing YouTube duplicate detection, render QA, upload quota, daily publish-slot guard, one-upload-per-run limit, and post-success asset deletion remain unchanged.
- This is historical TikTok -> YouTube backfill only. It does not change the normal buffer -> scheduled publisher flow.


Provider architecture rule: read docs/FREE_PROVIDER_ARCHITECTURE.md before changing provider, media, or orchestration code.


## Hard production boundary (2026-10-03)

Before a generated video enters the durable buffer, `pipeline/main.py` must pass `pipeline/production_gate.py`.
The gate validates the actual final MP4 with ffprobe + full FFmpeg decode, requires 1080x1920 video, audio,
configured 61-68s duration, and a sane file size. It also validates external-media provenance and the configured
music policy. `production_gate.json` is written beside the final artifact.

Do not downgrade this gate to report-only. `render.qa_gate()` is report-only EXCEPT the visual hard blocks
(`main.HARD_QA`: one picture > 20%, frozen / one-image video, blurry first 2 s; Oct 5), and a missing/corrupt
final file must be a hard failure.

`pipeline/publish.py` repeats the media/provenance validation after downloading the buffered asset. This protects
the publish boundary from corrupted or incomplete durable-buffer entries.

`pipeline/production_readiness.py` is an offline, zero-provider-cost preflight used by `daily.yml` and
`buffer_fill.yml`. It checks local tooling/configuration and reports credential warnings. It must not become a
provider-probing step in the normal free-tier workflow.


### Background music and checkpoint completion boundary

The production renderer intentionally separates soundtrack work from the core visual render. `pipeline/render.py` creates the complete visual + narration/SFX video; `pipeline/background_music.py` then adds the background music. Since Oct 5 the owner's own tracks (`unsolved_mystery.mp3`, `bk_grnde.mp3`) rotate with the original FFmpeg-generated ambient bed (`music_policy=approved_files`, `approved_music`, `music_rotation`). Never restore the Radiohead or Patience & Prudence recordings.

The production gate runs after the separate music stage.

Checkpoint rule: keep the checkpoint for failures before a complete final MP4 is preserved. If the workflow successfully uploads a complete `final.mp4` artifact, it may mark the checkpoint complete with `done.json`, per the owner's requested completion boundary. Buffer admission also completes the checkpoint normally.

## Analytics-driven Bloody Mary content cluster

YouTube Studio analytics now provide a strong Bloody Mary signal. The current top Short is **Bloody Mary Mirror Legend #Shorts** at 321 views in the supplied 28-day view, with multiple Bloody Mary-related search terms appearing.

Night Files now has eight dedicated Bloody Mary prompt concepts covering folklore variants, a dark fun fact, uncertain origins, lesser-known variations, the role of mirrors, and three clearly fictional spin-offs.

config.json uses an analytics-priority lane with priority_subgenre_probability=0.40 and a three-story recent-repeat block. This is intentionally not a hard Bloody Mary-only mode. The normal least-recently/least-often-used rotation remains the fallback, and the priority lane cannot immediately repeat a Bloody Mary concept from the recent window.

When writing Bloody Mary content:
- Do not simply remake the existing mirror video.
- Expand the cluster into different story angles and formats.
- Treat folklore as folklore, not verified supernatural fact.
- Do not present disputed historical origins as proven.
- Fun-fact scripts should center on one fact rather than becoming a list.
- Fictional spin-offs must be original and clearly fictional.
- Do not provide ritual instructions.
- Preserve the normal Night Files safety and duplicate-history rules.
