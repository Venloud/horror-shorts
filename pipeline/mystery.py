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
- One per scene: a painted illustration of the place, era, objects, or atmosphere of that moment. Match the real setting and time period.
- Never depict a real person's face. People appear only as distant silhouettes, from behind, or in shadow.
- No text, no writing, no blood, no bodies.

OTHER FIELDS
- title: the case name, 3-7 words.
- premise: one-sentence summary of the case.
- hook_overlay: 3-6 word on-screen title, e.g. "Still unsolved after 60 years".
- twist_scene: 0-based index of the scene with the strangest reveal.
- caption: 1-2 short lines ending with a question for comments. Max 150 characters. May use 1 emoji.
- hashtags: 5 hashtags without #, e.g. unsolvedmysteries, truecrime, mystery, plus 2 specific to the case.
- pinned_comment: a question that invites theories.
"""


def _load_cases() -> list[str]:
    return json.loads(CASES_FILE.read_text())


def pick_case(history: list[dict]) -> str:
    used = {h.get("case") for h in history if h.get("case")}
    fresh = [c for c in _load_cases() if c not in used]
    if not fresh:
        raise RuntimeError("All mystery cases in data/mysteries.json have been used. Add more titles.")
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


def build_prompt(channel: str, case: str) -> str:
    facts = fetch_facts(case)
    log(f"Mystery case: {case} ({len(facts)} chars of source)")
    return MYSTERY_PROMPT.format(channel=channel, case=case, facts=facts)
