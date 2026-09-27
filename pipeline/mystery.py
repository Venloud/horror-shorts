"""Real unsolved mysteries: pick a historical case, fetch its facts from Wikipedia, build a fact-locked prompt."""
import json
import random
import re

import requests

from common import ROOT, log

CASES_FILE = ROOT / "data" / "mysteries.json"
WIKI_API = "https://en.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": "NightFilesBot/1.0 (https://venloud.github.io/nightfiles/)"}

MYSTERY_PROMPT = """You narrate REAL unsolved mysteries for a faceless TikTok channel called "{channel}".
The video is read aloud by a calm, low narrator over dark painted images, with eerie "unsolved mystery" music.

TODAY'S CASE: {case}

SOURCE FACTS (from Wikipedia). This is your ONLY source. Everything you say must come from this text:
\"\"\"
{facts}
\"\"\"

STRUCTURE (follow exactly)
1. SCENE 1 = THE HOOK. Its narration MUST start with the exact words "This is a true story." and then 1-2 sentences (MAX 18 words after that opener): the single most disturbing or impossible TRUE detail of the case, stated flat. The first 6 words after the opener must already be unsettling. Style examples of the part after the opener (write new ones):
   - "Nine hikers cut their tent open from the inside and ran into the snow barefoot."
   - "A man boarded a plane with two hundred thousand dollars, then jumped out. He was never found."
   Never open with generic lines like "This is one of the strangest cases ever" or "Have you ever heard of".
2. SCENE 2 = CONTEXT: when and where it happened, and who was involved, in plain words.
3. SCENES 3+ = what happened, in order, with the eeriest real details. Then the main theories, clearly framed as theories ("Some believe...", "Investigators suggested...").
4. LAST SCENE = what remains unexplained, ending with a direct question to the viewer, e.g. "What do you think really happened?"

HARD RULES
- TRUE FACTS ONLY. Use only details in the source text. Do not invent names, quotes, dates, numbers, dialogue, or details. If unsure, leave it out.
- Never state or imply that a named real person is guilty of anything the source doesn't establish. Theories must be labelled as theories.
- Be respectful to victims and families. No graphic injury detail, no gore, no mocking.
- Third person, past tense, plain spoken English. Short sentences. Calm, serious documentary tone.
- 120 to 140 words of narration total (about 50-60 seconds). 7 to 9 scenes. Each scene 1-3 sentences.

IMAGE PROMPTS
- A painted illustration of the place, era, objects, or atmosphere of that moment. Match the real setting and time period.
- FOUR images per scene, one for each quarter of the narration, and each shows EXACTLY what is being said at that moment (when the words say "the bridge", show the bridge; "the windshield", show the view through the windshield): "image_prompt" = first part, "image_prompt_2" = second, "image_prompt_3" = third, "image_prompt_4" = last part. Each is a different shot, like a fast film edit: mix wide establishing shots of the place, medium shots of people, close-ups of key objects and clues, and reaction shots. A short scene may use fewer (leave the extra ones empty).
- Never depict a real person's face. People appear only as silhouettes against light, in deep shadow, or small in a wide shot.
- No text, no writing, no blood, no bodies.

- No all-seeing eye, eye-in-a-triangle or Illuminati-style symbols in any image, UNLESS the story itself is about that topic (e.g. a video about the Illuminati or the eye on the dollar bill). Eyes in the dark are fine.
- Keep every shot simple and drawable: one clear subject from a normal eye-level angle. Never ask for over-the-shoulder shots, people seen from behind, close-ups of hands or isolated body parts, or extreme low/high angles (the image AI twists bodies and puts faces on the back of heads). Prefer places, objects and wide shots.
- CONSISTENCY: fill "locations" with the 1-3 key places (short "name" + fixed "look" matching the real place and era) and set each scene's "location". List recurring figures in "characters" (e.g. "the hijacker": "man in a dark business suit, thin black tie, sunglasses, seen only as a silhouette"). In image prompts, refer to them by that exact name; their look is added automatically.
- POP CULTURE HOOK: if the source says a famous movie, TV show, video game, song or book was based on or inspired by this (for example, the Beast of Gevaudan appears in Teen Wolf), add ONE short line near the end that connects it, e.g. "Sound familiar? It's the same beast from Teen Wolf." Put that title in the caption and one hashtag. ONLY use references stated in the source. Never invent or guess one; if the source has none, skip this.

SOUND EFFECTS
- For each scene, set "sfx" to ONE sound from this list that fits that moment, or "none": {sfx_list}
- Use sound effects on 2 to 4 scenes only. Never on the hook scene.

OTHER FIELDS
- title: the case name, 3-7 words.
- premise: one-sentence summary of the case.
- hook_overlay: 2-5 word shocking on-screen text, e.g. "They cut the tent open", "Never found. Still unsolved."
- twist_scene: 0-based index of the scene with the strangest reveal.
- caption: 1-2 short lines ending with a question for comments. Max 150 characters. May use 1 emoji.
- hashtags: 5 hashtags without #, e.g. unsolvedmysteries, truecrime, mystery, plus 2 specific to the case.
- pinned_comment: a question that invites theories.
"""


LORE_FILE = ROOT / "data" / "lore.json"

LORE_PROMPT = """You tell dark LEGENDS and FOLKLORE for a faceless TikTok channel called "{channel}".
The video is read aloud by a calm, low narrator over dark painted images, with eerie music.

TODAY'S LEGEND: {case}

SOURCE (from Wikipedia). This is your ONLY source for facts about the legend:
\"\"\"
{facts}
\"\"\"

STRUCTURE (follow exactly). It must feel like a complete mini-story with a clear ending.
1. SCENE 1 = HOOK, "did you know" style (1-2 sentences, MAX 18 words), built on the single creepiest detail of the legend. The first 6 words must already be unsettling. Patterns:
   - "Did you know [creepiest detail, stated plainly]?"
   - "In [place], people still [strange protective habit]. Because of what [creature] does."
   Never open with a vague line like "There is an old legend".
2. SCENE 2 = CONTEXT: where the legend comes from and how old it is.
3. What the creature/legend is, what it does, its rules (how it hunts, what attracts it), with the eeriest details.
4. The most famous story, sighting, or belief about it (framed as "people claimed", "the legend says").
5. How people protected themselves, according to the legend.
5b. Include ONE surprising real detail the viewer will want to repeat to a friend ("I didn't know that!").
6. LAST SCENE = a chilling closing line that ties back to the hook and ends the video cleanly, e.g. "So next time you [situation]... maybe don't [action]."

HARD RULES
- Use only facts from the source. Present the legend as a legend ("the story goes", "people believed"), never as proven fact.
- Respectful to the cultures these stories come from: no mocking, no stereotypes, and no treating anyone's religion as evil.
- No gore, no harm to children, no sexual content.
- Third person, plain spoken English, short sentences. 120 to 140 words (about 50-60 seconds). 7 to 9 scenes, 1-3 sentences each.

IMAGE PROMPTS
- Painted illustrations showing the creature, the setting, the era, or the moment. The creature can be shown (it is folklore), but no gore.
- FOUR images per scene, one for each quarter of the narration, and each shows EXACTLY what is being said at that moment (when the words say "the bridge", show the bridge; "the windshield", show the view through the windshield): "image_prompt" = first part, "image_prompt_2" = second, "image_prompt_3" = third, "image_prompt_4" = last part. Each is a different shot, like a fast film edit: mix wide establishing shots of the place, medium shots of people, close-ups of key objects and clues, and reaction shots. A short scene may use fewer (leave the extra ones empty).
- No text or writing in the image.

- No all-seeing eye, eye-in-a-triangle or Illuminati-style symbols in any image, UNLESS the story itself is about that topic (e.g. a video about the Illuminati or the eye on the dollar bill). Eyes in the dark are fine.
- Keep every shot simple and drawable: one clear subject from a normal eye-level angle. Never ask for over-the-shoulder shots, people seen from behind, close-ups of hands or isolated body parts, or extreme low/high angles (the image AI twists bodies and puts faces on the back of heads). Prefer places, objects and wide shots.
- CONSISTENCY: fill "locations" with the 1-3 key places (short "name" + fixed "look" matching the real place and era) and set each scene's "location". List recurring figures in "characters" (e.g. "the hijacker": "man in a dark business suit, thin black tie, sunglasses, seen only as a silhouette"). In image prompts, refer to them by that exact name; their look is added automatically.
- POP CULTURE HOOK: if the source says a famous movie, TV show, video game, song or book was based on or inspired by this (for example, the Beast of Gevaudan appears in Teen Wolf), add ONE short line near the end that connects it, e.g. "Sound familiar? It's the same beast from Teen Wolf." Put that title in the caption and one hashtag. ONLY use references stated in the source. Never invent or guess one; if the source has none, skip this.

SOUND EFFECTS
- For each scene, set "sfx" to ONE sound from this list that fits, or "none": {sfx_list}
- Use sound effects on 2 to 4 scenes only. Never on the hook scene.

OTHER FIELDS
- title: the legend name, 3-7 words.
- premise: one-sentence summary.
- hook_overlay: 2-5 word shocking on-screen text, e.g. "It mimics your mother's voice".
- twist_scene: 0-based index of the creepiest reveal.
- caption: 1-2 short lines ending with a question for comments. Max 150 characters. May use 1 emoji.
- hashtags: 5 hashtags without #, e.g. folklore, legends, creepy, plus 2 specific.
- pinned_comment: a question that invites people to share their own local legends.
"""


TRUE_PROMPT = """You retell REAL true stories (true crime, famous cases, strange true events) for a faceless TikTok channel called "{channel}".
The video is read aloud by a calm, serious narrator over illustrated images, with tense music.

TODAY'S STORY: {case}

SOURCE. This is your ONLY source. Everything you say must come from this text:
\"\"\"
{facts}
\"\"\"

MAKE IT TIKTOK-SAFE (never refuse a normal crime story):
- Tell dark stories safely: focus on the mystery, the investigation, the clues and how it ended. Say what happened in plain, non-graphic words ("she was killed", never how in detail). No gore, no cruelty described step by step.
- ONLY if the core of the story is harm to a child, a sexual crime, or suicide, do not retell it as true. Instead set "title" to exactly INSPIRATION and keep every other field minimal; it will be turned into an original fictional story that leaves those parts out.
- If the source is not a real story at all, set "title" to exactly SKIP.

STRUCTURE (follow exactly)
1. SCENE 1 = THE HOOK. Its narration MUST start with the exact words "This is a true story." and then 1-2 sentences (MAX 18 words after that opener): the most gripping true detail, stated flat. The first 6 words after the opener must already grab. Style examples of the part after the opener (write new ones):
   - "In 1950, eleven men walked into the most secure vault in Boston and walked out with two million dollars."
   - "The man paid for his plane ticket in cash. Two hours later, he parachuted into the dark with the ransom."
2. SCENE 2 = CONTEXT: when, where, who, in plain words.
3. WHAT HAPPENED: the key turns in order, with the most vivid real details.
4. HOW IT ENDED: caught, solved, escaped, or still unknown. This must pay off the hook.
5. LAST SCENE: one strong closing line, then a short question to the viewer.

HARD RULES
- TRUE FACTS ONLY. Never invent names, quotes, dates, numbers, dialogue or details. If unsure, leave it out.
- Only call someone guilty if the source says they were convicted or confessed. Otherwise say "suspected" or "accused".
- Respectful to victims and families. No graphic injury detail, no gore, no mocking.
- Third person, past tense, plain spoken English, short sentences.
- 120 to 140 words of narration total (about 50-60 seconds). 7 to 9 scenes, 1-3 sentences each.

IMAGE PROMPTS
- Illustrated scenes of the real place, era, objects and moments. Match the real setting and time period.
- FOUR images per scene, one for each quarter of the narration, and each shows EXACTLY what is being said at that moment (when the words say "the bridge", show the bridge; "the windshield", show the view through the windshield): "image_prompt" = first part, "image_prompt_2" = second, "image_prompt_3" = third, "image_prompt_4" = last part. Each is a different shot, like a fast film edit: mix wide establishing shots of the place, medium shots of people, close-ups of key objects and clues, and reaction shots. A short scene may use fewer (leave the extra ones empty).
- Never depict a real person's face: people appear only as silhouettes against light, in deep shadow, or small in a wide shot.
- Lighting gets darker and tenser as the story builds. No text, no writing, no blood, no bodies.

- No all-seeing eye, eye-in-a-triangle or Illuminati-style symbols in any image, UNLESS the story itself is about that topic (e.g. a video about the Illuminati or the eye on the dollar bill). Eyes in the dark are fine.
- Keep every shot simple and drawable: one clear subject from a normal eye-level angle. Never ask for over-the-shoulder shots, people seen from behind, close-ups of hands or isolated body parts, or extreme low/high angles (the image AI twists bodies and puts faces on the back of heads). Prefer places, objects and wide shots.
- CONSISTENCY: fill "locations" with the 1-3 key places (short "name" + fixed "look" matching the real place and era) and set each scene's "location". List recurring figures in "characters" (e.g. "the hijacker": "man in a dark business suit, thin black tie, sunglasses, seen only as a silhouette"). In image prompts, refer to them by that exact name; their look is added automatically.
- POP CULTURE HOOK: if the source says a famous movie, TV show, video game, song or book was based on or inspired by this (for example, the Beast of Gevaudan appears in Teen Wolf), add ONE short line near the end that connects it, e.g. "Sound familiar? It's the same beast from Teen Wolf." Put that title in the caption and one hashtag. ONLY use references stated in the source. Never invent or guess one; if the source has none, skip this.

SOUND EFFECTS
- For each scene, set "sfx" to ONE sound from this list that fits that moment, or "none": {sfx_list}
- Use sound effects on 2 to 4 scenes only. Never on the hook scene.

OTHER FIELDS
- title: the case name, 3-7 words.
- premise: one-sentence summary.
- hook_overlay: 2-5 word shocking on-screen text, e.g. "The perfect crime. Almost."
- twist_scene: 0-based index of the biggest turn.
- caption: line 1 = a searchable title the way people type it into TikTok search (e.g. "The Brink's Robbery: The Perfect Crime That Almost Worked"). Line 2 = a question for comments. Max 180 characters. May use 1 emoji.
- hashtags: 5 hashtags without #, e.g. truecrime, truestory, crimestory, plus 2 specific to the case.
- pinned_comment: a question that starts a discussion.
"""



def _split_wiki(text: str, limit: int) -> str:
    """Main article text plus a short 'In popular culture' section (used for pop-culture references)."""
    pop = ""
    m = re.search(r"\n==\s*(In popular culture|Popular culture|In fiction|Legacy|Cultural impact|In media)\s*==\n(.*?)(\n==[^=]|$)", text, re.S)
    if m:
        pop = m.group(2).strip()[:1500]
    main = re.split(r"\n==\s*(See also|References|Notes|Further reading|External links|In popular culture|Popular culture|In fiction|In media)\s*==", text)[0]
    main = main[: limit - len(pop) - 40]
    return main + (f"\n\nIN POPULAR CULTURE:\n{pop}" if pop else "")

def pick_case(history: list[dict], kind: str = "mystery") -> str:
    file = LORE_FILE if kind == "lore" else CASES_FILE
    used = {h.get("case") for h in history if h.get("case")}
    fresh = [c for c in json.loads(file.read_text()) if c not in used]
    if not fresh:
        raise RuntimeError(f"All topics in {file.name} have been used. Add more titles.")
    return random.choice(fresh)


def fetch_facts(title: str, limit: int = 9000) -> str:
    r = requests.get(WIKI_API, headers=HEADERS, timeout=30, params={
        "action": "query", "format": "json", "prop": "extracts", "explaintext": 1,
        "redirects": 1, "titles": title,
    })
    r.raise_for_status()
    pages = r.json()["query"]["pages"]
    text = next(iter(pages.values())).get("extract", "")
    if len(text) < 800:
        raise RuntimeError(f"Wikipedia article for '{title}' is missing or too short")
    return _split_wiki(text, limit)


def build_prompt(channel: str, case: str, sfx_list: str = "none", kind: str = "mystery") -> tuple[str, str]:
    facts = fetch_facts(case)
    log(f"Topic: {case} ({len(facts)} chars of source)")
    template = LORE_PROMPT if kind == "lore" else MYSTERY_PROMPT
    return template.format(channel=channel, case=case, facts=facts, sfx_list=sfx_list), facts
