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
1. SCENE 1 = THE HOOK (spoken, 1-2 sentences, max 25 words): the single strangest true fact of the case, told so a scroller stops. Pattern ideas:
   - "In [year], [number] people walked into [place]. None of them came back, and no one can explain why."
   - "This is one of the strangest unsolved cases ever recorded."
   - "[Strange fact]. To this day, nobody knows why."
2. SCENE 2 = CONTEXT: when and where it happened, and who was involved, in plain words.
3. SCENES 3+ = what happened, in order, with the eeriest real details. Then the main theories, clearly framed as theories ("Some believe...", "Investigators suggested...").
4. LAST SCENE = what remains unexplained, ending with a direct question to the viewer, e.g. "What do you think really happened?"

HARD RULES
- TRUE FACTS ONLY. Use only details in the source text. Do not invent names, quotes, dates, numbers, dialogue, or details. If unsure, leave it out.
- Never state or imply that a named real person is guilty of anything the source doesn't establish. Theories must be labelled as theories.
- Be respectful to victims and families. No graphic injury detail, no gore, no mocking.
- Third person, past tense, plain spoken English. Short sentences. Calm, serious documentary tone.
- 170 to 210 words of narration total. 8 to 10 scenes. Each scene 1-3 sentences.

IMAGE PROMPTS
- A painted illustration of the place, era, objects, or atmosphere of that moment. Match the real setting and time period.
- TWO images per scene: "image_prompt" shows the FIRST sentence of that scene, "image_prompt_2" shows the SECOND half. They must be different shots, like a film editor would cut: e.g. "I was 23, living alone in an old brick duplex" = shot 1: the young man in his room; shot 2: wide exterior of the old brick duplex at night. Mix close-ups, wide establishing shots of the location, objects, and over-the-shoulder views.
- Never depict a real person's face. People appear only as distant silhouettes, from behind, or in shadow.
- No text, no writing, no blood, no bodies.

SOUND EFFECTS
- For each scene, set "sfx" to ONE sound from this list that fits that moment, or "none": {sfx_list}
- Use sound effects on 2 to 4 scenes only. Never on the hook scene.

OTHER FIELDS
- title: the case name, 3-7 words.
- premise: one-sentence summary of the case.
- hook_overlay: 3-6 word on-screen title, e.g. "Still unsolved after 60 years".
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
1. SCENE 1 = HOOK, "did you know" style (1-2 sentences, max 25 words), using the creepiest detail of the legend. Patterns:
   - "Did you know that in [place], people believed [creepy belief]?"
   - "There's a creature in [culture] folklore that [creepy trait], and people still [what they do] today."
   - "If you ever [situation] in [place], the old stories say you should never [action]."
2. SCENE 2 = CONTEXT: where the legend comes from and how old it is.
3. What the creature/legend is, what it does, its rules (how it hunts, what attracts it), with the eeriest details.
4. The most famous story, sighting, or belief about it (framed as "people claimed", "the legend says").
5. How people protected themselves, according to the legend.
6. LAST SCENE = a chilling closing line that ties back to the hook and ends the video cleanly, e.g. "So next time you [situation]... maybe don't [action]."

HARD RULES
- Use only facts from the source. Present the legend as a legend ("the story goes", "people believed"), never as proven fact.
- Respectful to the cultures these stories come from: no mocking, no stereotypes, and no treating anyone's religion as evil.
- No gore, no harm to children, no sexual content.
- Third person, plain spoken English, short sentences. 170 to 210 words. 8 to 10 scenes, 1-3 sentences each.

IMAGE PROMPTS
- Painted illustrations showing the creature, the setting, the era, or the moment. The creature can be shown (it is folklore), but no gore.
- TWO images per scene: "image_prompt" shows the FIRST sentence of that scene, "image_prompt_2" shows the SECOND half. They must be different shots, like a film editor would cut: e.g. "I was 23, living alone in an old brick duplex" = shot 1: the young man in his room; shot 2: wide exterior of the old brick duplex at night. Mix close-ups, wide establishing shots of the location, objects, and over-the-shoulder views.
- No text or writing in the image.

SOUND EFFECTS
- For each scene, set "sfx" to ONE sound from this list that fits, or "none": {sfx_list}
- Use sound effects on 2 to 4 scenes only. Never on the hook scene.

OTHER FIELDS
- title: the legend name, 3-7 words.
- premise: one-sentence summary.
- hook_overlay: 3-6 word on-screen title, e.g. "The legend of the Wendigo".
- twist_scene: 0-based index of the creepiest reveal.
- caption: 1-2 short lines ending with a question for comments. Max 150 characters. May use 1 emoji.
- hashtags: 5 hashtags without #, e.g. folklore, legends, creepy, plus 2 specific.
- pinned_comment: a question that invites people to share their own local legends.
"""


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
    # Drop reference-style tail sections
    text = re.split(r"\n==\s*(See also|References|Notes|Further reading|External links|In popular culture)\s*==", text)[0]
    return text[:limit]


def build_prompt(channel: str, case: str, sfx_list: str = "none", kind: str = "mystery") -> tuple[str, str]:
    facts = fetch_facts(case)
    log(f"Topic: {case} ({len(facts)} chars of source)")
    template = LORE_PROMPT if kind == "lore" else MYSTERY_PROMPT
    return template.format(channel=channel, case=case, facts=facts, sfx_list=sfx_list), facts
