"""Real unsolved mysteries: pick a historical case, fetch its facts from Wikipedia, build a fact-locked prompt."""
import json
import random
import re
import time

import requests

from common import CONFIG, ROOT, blocked_topic, log

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
1. SCENE 1 = THE HOOK. Its FIRST sentence (MAX 18 words) is the single most disturbing or impossible TRUE detail of the case, stated flat; the first 6 words must already be unsettling. Right after that hook sentence, scene 1 continues with the exact words "This is a true story." Style examples of the hook sentence (write new ones):
   - "Nine hikers cut their tent open from the inside and ran into the snow barefoot."
   - "A man boarded a plane with two hundred thousand dollars, then jumped out. He was never found."
   Never open with generic lines like "This is one of the strangest cases ever" or "Have you ever heard of".
   NEVER open with a date, a year, or a place name. Put when/where in scene 2. The first words must be the strangest or most shocking detail.
   The first sentence is the most ironic, specific or unbelievable REAL detail in the source (e.g. "The password to the Louvre's security cameras was 'Louvre.'"), NOT a summary of the event. It must be literally true as the source states it, and must never imply a cause, motive or connection the source doesn't state.
2. SCENE 2 = CONTEXT: when and where it happened, and who was involved, in plain words.
3. SCENES 3+ = what happened, in order, with the eeriest real details. Then the main theories, clearly framed as theories ("Some believe...", "Investigators suggested...").
4. LAST SCENE = what remains unexplained, ending with a direct question to the viewer, e.g. "What do you think really happened?"

HARD RULES
- FACT LOCK: before writing, build a fact ledger from the SOURCE in "fact_ledger" (one "label: value" line each: names, numbers, money, dates, years, ages, places, counts, organizations, vehicles/aircraft, quotes). Write the story ONLY from that ledger. Values may be turned into spoken words but NEVER changed, rounded, estimated or slangified ("$200,000" -> "two hundred thousand dollars"; never "twenty-k", "twenty thousand" or "about two hundred thousand"). Before returning, silently compare every value in the narration with the ledger.
- Never distort a fact to make a hook more shocking. A specific true detail beats a dramatic interpretation.
- TRUE FACTS ONLY. Use only details in the source text. Do not invent names, quotes, dates, numbers, dialogue, or details. If unsure, leave it out.
- Never state or imply that a named real person is guilty of anything the source doesn't establish. Theories must be labelled as theories.
- Be respectful to victims and families. No graphic injury detail, no gore, no mocking.
- Third person, past tense, plain spoken English. Short sentences. Calm, serious documentary tone.
- {words} words of narration total (about one minute). 7 to 9 scenes. Each scene 1-3 sentences.

IMAGE PROMPTS
- A painted illustration of the place, era, objects, or atmosphere of that moment. Match the real setting and time period.
- TWO images per scene: "image_prompt" = the main visual of what the narration says (when the words say "the bridge", show the bridge); "image_prompt_2" = a genuinely DIFFERENT visual from the same narration: another subject, action or angle (e.g. the key object in close-up, the place as a wide shot, another person's reaction). Never the same picture twice. Leave "image_prompt_3" and "image_prompt_4" empty (and their image_location fields "none").
- REAL PEOPLE: real people are shown with normal visible faces in the channel's illustrated style, matching only basic public facts (approximate age, hair, clothing, era). Do NOT try to copy a real private person's actual face. Historical figures (dead 100+ years) may follow known portraits. Masked or hooded figures are fine when the story fits (thieves, disguises). Each real person gets a "characters" entry with a fixed look that is reused word-for-word in every shot they appear in, so they stay consistent.
- No text, no writing, no blood, no bodies.

- No all-seeing eye, eye-in-a-triangle or Illuminati-style symbols in any image, UNLESS the story itself is about that topic (e.g. a video about the Illuminati or the eye on the dollar bill). Eyes in the dark are fine.
- Keep every shot simple and drawable: one clear subject from a normal eye-level angle. Never ask for over-the-shoulder shots, people seen from behind, close-ups of hands or isolated body parts, or extreme low/high angles (the image AI twists bodies and puts faces on the back of heads). Prefer places, objects and wide shots.
- ONE FRAME ONLY: every image is ONE continuous full frame, like a single frame from a film. Never comic panels, page layouts, storyboards, collages, split screens or multiple versions of a scene.
- NO READABLE TEXT: never ask for readable text, words, signs with lettering, neon lettering, title cards, headlines, or documents/screens/phones with words on them (the image AI turns them into garbled fake text). Show those objects without legible text: "a blank hotel sign glowing red", "a laptop screen glowing in the dark".
- REAL VICTIMS: never depict a real victim's death, body, body parts, injuries or remains (never "Elisa floats in the tank", "a pale hand breaks the water", "the body in the river"). Show the place or object instead: the tank, the open hatch, the dark water, the empty room, the closed door.
- MEDIA SOURCE per shot: "image_source" (and "image_source_2".."_4") is "ai", "stock_video" or "real_photo", and "image_query" (and "_2".."_4") is a 2-5 word search query for that shot. real_photo = TRUE STORIES ONLY: a real place, building, vehicle, object, document or official sketch/wanted poster that exists in public archives (query = its real name, e.g. "Cecil Hotel Los Angeles", "Boeing 727"); NEVER private people, victims, bodies or crime-scene photos. stock_video = generic atmosphere with NO story character in it (rain on a window at night, fog between pine trees, a flickering hallway light, a city street at night). ai = every shot with a story character or a specific story moment. The first shot of scene 1 is always "ai". At most 3 real_photo shots and about 40% stock_video shots per video; fiction never uses real_photo.
- TRUE STORY VISUALS: keep objects, clothing, vehicles, buildings and era historically accurate. If the source doesn't establish a visual detail, keep it generic.
- CONSISTENCY: fill "locations" with the 1-3 key places (short "name" + fixed "look", max 20 words, matching the real place and era) and set each scene's "location". List recurring figures in "characters" (e.g. "the hijacker": "man in his 40s, short dark hair, dark business suit, thin black tie, sunglasses, 1970s"). In image prompts, refer to them by that exact name; their look is added automatically.
- PER-SHOT LOCATION: every image prompt has its own location field: "image_location", "image_location_2", "image_location_3", "image_location_4" = the exact "locations" name where THAT shot takes place, or "none" (object close-ups, sky, anything not in a listed place). An outdoor shot (forest, river, road, sky) never uses an indoor location like a cabin; if the story goes outside, add that outdoor place to "locations".
- OBJECT SHOTS: in a close-up of a thing (a note, a briefcase, money), the object is the subject: describe the object and the surface it lies on, nothing else; its location is "none".
- Write every image prompt as plain descriptive text, never labels like "SHOT:" or "SETTING:". The main subject + action + key object come in the first 12 words; then framing, lighting, mood.
- Every shot in the video is a different picture: never two prompts with nearly the same subject and framing.
- POP CULTURE HOOK: if the source says a famous movie, TV show, video game, song or book was based on or inspired by this (for example, the Beast of Gevaudan appears in Teen Wolf), add ONE short line near the end that connects it, e.g. "Sound familiar? It's the same beast from Teen Wolf." Put that title in the caption and one hashtag. ONLY use references stated in the source. Never invent or guess one; if the source has none, skip this.

SOUND EFFECTS
- For each scene, set "sfx" to ONE sound from this list that fits that moment, or "none": {sfx_list}
- Use sound effects on 2 to 4 scenes only. Never on the hook scene.

OTHER FIELDS
- title: the case name, 3-7 words.
- premise: one-sentence summary of the case.
- hook_overlay: 2-5 word shocking on-screen text, e.g. "They cut the tent open", "Never found. Still unsolved."
- hook_candidates: 3 DIFFERENT candidate first sentences for scene 1 (each max 18 words, strangest or most shocking detail first, never a date, year or place name). Scene 1 must start with the best one.
- twist_scene: 0-based index of the scene with the strangest reveal.
- caption: line 1 = the exact phrase people type into search for this story (e.g. "What happened to D.B. Cooper?", "What is the Wendigo?"); the channel adds "illustrated horror story" itself. Line 2 = a question for comments. Max 150 characters. May use 1 emoji.
- hashtags: 5 topic hashtags without # (the case, place, legend or subject + its genre, e.g. dbcooper, unsolvedmysteries). The channel adds #illustratedhorror #horrorstory itself. Never fyp, foryou or viral. For true stories, hashtags and caption must match the source: never "unsolved" / #unsolved when the source gives an official ruling (e.g. a coroner's finding) or the case was solved.
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

STRUCTURE (follow exactly). This is a STORY, not a list of facts: one specific scenario, told the way the legend
is told, with people, a place, rising tension and an ending. Every fact from the ledger is woven INTO that scene.
- THE SCENARIO: a scenario the source describes, or a typical one built only from what the source says the legend
  involves (e.g. for a revenant: a death in a village, the family and neighbours falling ill one by one, the
  villagers' suspicion turning to the grave, the gravedigger opening it and finding the signs the source names,
  then the remedy the source names). If the source gives no specific case, frame it plainly as how the legend is
  told ("The story always starts the same way.", "In the old tellings, ..."), never as a documented event, and
  never invent names, dates, places or numbers. 1-2 recurring people (a gravedigger, a widow, a villager) with
  roles, no names unless the source names them.
1. SCENE 1 = HOOK (1-2 sentences, MAX 18 words): the most unsettling MOMENT of the scenario, stated plainly, e.g.
   "When they opened her grave, the burial shroud was chewed to rags." The first 6 words must already be unsettling.
   Never "Did you know", never a vague line like "There is an old legend".
   NEVER open with a date, a year, or a place name. The first words must be the strangest or most shocking detail.
   It must be literally what the legend says (a sign, a belief, a remedy from the source); never imply a cause,
   motive or connection the source doesn't state.
2. SCENE 2 = name the legend out loud (the way people search for it) and where/when it is told.
3-5. THE SCENARIO with tension: the death, what starts happening to the living, the suspicion, the decision to
   open the grave. Each scene adds one new detail from the ledger (what it is, what it does, its signs).
6. THE REVEAL (twist_scene): what they find, from the source (e.g. the open mouth, the chewed shroud).
7. THE REMEDY from the source, done in the scene (the coin or stone placed in the mouth, the head...), and
   whether it worked, as the legend tells it.
8. LAST SCENE = a chilling closing line that pays off the hook and ends the video cleanly.
Include ONE surprising real detail the viewer will want to repeat to a friend.
NEVER write "according to the sources", "from the sources", "the sources say", "folklore held", "according to
folklore" or any line about where the information comes from: the narrator TELLS the legend ("the story goes",
"people swore", "villagers believed" are fine).

HARD RULES
- FACT LOCK: before writing, build a fact ledger from the SOURCE in "fact_ledger" (one "label: value" line each: names, numbers, money, dates, years, ages, places, counts, organizations, vehicles/aircraft, quotes). Write the story ONLY from that ledger. Values may be turned into spoken words but NEVER changed, rounded, estimated or slangified ("$200,000" -> "two hundred thousand dollars"; never "twenty-k", "twenty thousand" or "about two hundred thousand"). Before returning, silently compare every value in the narration with the ledger.
- Never distort a fact to make a hook more shocking. A specific true detail beats a dramatic interpretation.
- Use only facts from the source. Present the legend as a legend ("the story goes", "people believed"), never as proven fact.
- Respectful to the cultures these stories come from: no mocking, no stereotypes, and no treating anyone's religion as evil.
- No gore, no harm to children, no sexual content.
- Third person, plain spoken English, short sentences. {words} words (about one minute). 7 to 9 scenes, 1-3 sentences each.

IMAGE PROMPTS
- Painted illustrations of the SCENARIO: the people, the creature, the place, the moment. No gore.
- THE CREATURE ON SCREEN: put the creature/revenant in "characters" (name = the legend's name in lower case, e.g.
  "nachzehrer"; a fixed 15-20 word look exactly as the legend describes it, no blood, no gore, no occult symbols)
  and SHOW it, by that exact name, in at least 3 shots: scene 1's "image_prompt" (the hook shot), the reveal
  scene, and one more. Those shots are "ai". Also give the 1-2 recurring people a "characters" entry.
- No filler shots: never a blank wall, a bare texture, a surface, threads or a generic object on a table. Every
  shot shows a person, the creature, or a story object IN the story's moment (the coin in the corpse's mouth,
  not "silver coins on a table").
- TWO images per scene: "image_prompt" = the main visual of what the narration says (when the words say "the bridge", show the bridge); "image_prompt_2" = a genuinely DIFFERENT visual from the same narration: another subject, action or angle (e.g. the key object in close-up, the place as a wide shot, another person's reaction). Never the same picture twice. Leave "image_prompt_3" and "image_prompt_4" empty (and their image_location fields "none").
- No text or writing in the image.
- REAL PEOPLE (if the legend involves real people): real people are shown with normal visible faces in the channel's illustrated style, matching only basic public facts (approximate age, hair, clothing, era). Do NOT try to copy a real private person's actual face. Historical figures (dead 100+ years) may follow known portraits. Masked or hooded figures are fine when the story fits. Each real person gets a "characters" entry with a fixed look that is reused word-for-word in every shot they appear in.

- No all-seeing eye, eye-in-a-triangle or Illuminati-style symbols in any image, UNLESS the story itself is about that topic (e.g. a video about the Illuminati or the eye on the dollar bill). Eyes in the dark are fine.
- Keep every shot simple and drawable: one clear subject from a normal eye-level angle. Never ask for over-the-shoulder shots, people seen from behind, close-ups of hands or isolated body parts, or extreme low/high angles (the image AI twists bodies and puts faces on the back of heads). Prefer places, objects and wide shots.
- ONE FRAME ONLY: every image is ONE continuous full frame, like a single frame from a film. Never comic panels, page layouts, storyboards, collages, split screens or multiple versions of a scene.
- NO READABLE TEXT: never ask for readable text, words, signs with lettering, neon lettering, title cards, headlines, or documents/screens/phones with words on them (the image AI turns them into garbled fake text). Show those objects without legible text: "a blank hotel sign glowing red", "a laptop screen glowing in the dark".
- REAL VICTIMS: never depict a real victim's death, body, body parts, injuries or remains (never "Elisa floats in the tank", "a pale hand breaks the water", "the body in the river"). Show the place or object instead: the tank, the open hatch, the dark water, the empty room, the closed door.
- MEDIA SOURCE per shot: "image_source" (and "image_source_2".."_4") is "ai", "stock_video" or "real_photo", and "image_query" (and "_2".."_4") is a 2-5 word search query for that shot. real_photo = TRUE STORIES ONLY: a real place, building, vehicle, object, document or official sketch/wanted poster that exists in public archives (query = its real name, e.g. "Cecil Hotel Los Angeles", "Boeing 727"); NEVER private people, victims, bodies or crime-scene photos. stock_video = generic atmosphere with NO story character in it (rain on a window at night, fog between pine trees, a flickering hallway light, a city street at night). ai = every shot with a story character or a specific story moment. The first shot of scene 1 is always "ai". At most 3 real_photo shots and about 40% stock_video shots per video; fiction never uses real_photo.
- CONSISTENCY: fill "locations" with the 1-3 key places (short "name" + fixed "look", max 20 words, matching the real place and era) and set each scene's "location". List recurring figures in "characters" (e.g. "the hijacker": "man in his 40s, short dark hair, dark business suit, thin black tie, sunglasses, 1970s"). In image prompts, refer to them by that exact name; their look is added automatically.
- PER-SHOT LOCATION: every image prompt has its own location field: "image_location", "image_location_2", "image_location_3", "image_location_4" = the exact "locations" name where THAT shot takes place, or "none" (object close-ups, sky, anything not in a listed place). An outdoor shot (forest, river, road, sky) never uses an indoor location like a cabin; if the story goes outside, add that outdoor place to "locations".
- OBJECT SHOTS: in a close-up of a thing (a note, a briefcase, money), the object is the subject: describe the object and the surface it lies on, nothing else; its location is "none".
- Write every image prompt as plain descriptive text, never labels like "SHOT:" or "SETTING:". The main subject + action + key object come in the first 12 words; then framing, lighting, mood.
- Every shot in the video is a different picture: never two prompts with nearly the same subject and framing.
- POP CULTURE HOOK: if the source says a famous movie, TV show, video game, song or book was based on or inspired by this (for example, the Beast of Gevaudan appears in Teen Wolf), add ONE short line near the end that connects it, e.g. "Sound familiar? It's the same beast from Teen Wolf." Put that title in the caption and one hashtag. ONLY use references stated in the source. Never invent or guess one; if the source has none, skip this.

SOUND EFFECTS
- For each scene, set "sfx" to ONE sound from this list that fits, or "none": {sfx_list}
- Use sound effects on 2 to 4 scenes only. Never on the hook scene.

OTHER FIELDS
- title: the legend name, 3-7 words.
- premise: one-sentence summary.
- hook_overlay: 2-5 word shocking on-screen text, e.g. "It mimics your mother's voice".
- hook_candidates: 3 DIFFERENT candidate first sentences for scene 1 (each max 18 words, strangest or most shocking detail first, never a date, year or place name). Scene 1 must start with the best one.
- twist_scene: 0-based index of the creepiest reveal.
- caption: line 1 = the exact phrase people type into search for this story (e.g. "What happened to D.B. Cooper?", "What is the Wendigo?"); the channel adds "illustrated horror story" itself. Line 2 = a question for comments. Max 150 characters. May use 1 emoji.
- hashtags: 5 topic hashtags without # (the case, place, legend or subject + its genre, e.g. dbcooper, unsolvedmysteries). The channel adds #illustratedhorror #horrorstory itself. Never fyp, foryou or viral. For true stories, hashtags and caption must match the source: never "unsolved" / #unsolved when the source gives an official ruling (e.g. a coroner's finding) or the case was solved.
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
1. SCENE 1 = THE HOOK. Its FIRST sentence (MAX 18 words) is the most gripping true detail, stated flat; the first 6 words must already grab. Right after that hook sentence, scene 1 continues with the exact words "This is a true story." Style examples of the hook sentence (write new ones):
   - "Eleven men walked into the most secure vault in the city and walked out with two million dollars."
   - "The man paid for his plane ticket in cash. Two hours later, he parachuted into the dark with the ransom."
   NEVER open with a date, a year, or a place name. Put when/where in scene 2. The first words must be the strangest or most shocking detail.
   The first sentence is the most ironic, specific or unbelievable REAL detail in the source (e.g. "The password to the Louvre's security cameras was 'Louvre.'"), NOT a summary of the event. It must be literally true as the source states it, and must never imply a cause, motive or connection the source doesn't state.
2. SCENE 2 = CONTEXT: when, where, who, in plain words.
3. WHAT HAPPENED: the key turns in order, with the most vivid real details.
4. HOW IT ENDED: caught, solved, escaped, or still unknown. This must pay off the hook.
5. LAST SCENE: one strong closing line, then a short question to the viewer.

HARD RULES
- FACT LOCK: before writing, build a fact ledger from the SOURCE in "fact_ledger" (one "label: value" line each: names, numbers, money, dates, years, ages, places, counts, organizations, vehicles/aircraft, quotes). Write the story ONLY from that ledger. Values may be turned into spoken words but NEVER changed, rounded, estimated or slangified ("$200,000" -> "two hundred thousand dollars"; never "twenty-k", "twenty thousand" or "about two hundred thousand"). Before returning, silently compare every value in the narration with the ledger.
- Never distort a fact to make a hook more shocking. A specific true detail beats a dramatic interpretation.
- TRUE FACTS ONLY. Never invent names, quotes, dates, numbers, dialogue or details. If unsure, leave it out.
- Only call someone guilty if the source says they were convicted or confessed. Otherwise say "suspected" or "accused".
- Respectful to victims and families. No graphic injury detail, no gore, no mocking.
- Third person, past tense, plain spoken English, short sentences.
- {words} words of narration total (about one minute). 7 to 9 scenes, 1-3 sentences each.

IMAGE PROMPTS
- Illustrated scenes of the real place, era, objects and moments. Match the real setting and time period.
- TWO images per scene: "image_prompt" = the main visual of what the narration says (when the words say "the bridge", show the bridge); "image_prompt_2" = a genuinely DIFFERENT visual from the same narration: another subject, action or angle (e.g. the key object in close-up, the place as a wide shot, another person's reaction). Never the same picture twice. Leave "image_prompt_3" and "image_prompt_4" empty (and their image_location fields "none").
- REAL PEOPLE: real people are shown with normal visible faces in the channel's illustrated style, matching only basic public facts (approximate age, hair, clothing, era). Do NOT try to copy a real private person's actual face. Historical figures (dead 100+ years) may follow known portraits. Masked or hooded figures are fine when the story fits (thieves, disguises). Each real person gets a "characters" entry with a fixed look that is reused word-for-word in every shot they appear in, so they stay consistent.
- Lighting gets darker and tenser as the story builds. No text, no writing, no blood, no bodies.

- No all-seeing eye, eye-in-a-triangle or Illuminati-style symbols in any image, UNLESS the story itself is about that topic (e.g. a video about the Illuminati or the eye on the dollar bill). Eyes in the dark are fine.
- Keep every shot simple and drawable: one clear subject from a normal eye-level angle. Never ask for over-the-shoulder shots, people seen from behind, close-ups of hands or isolated body parts, or extreme low/high angles (the image AI twists bodies and puts faces on the back of heads). Prefer places, objects and wide shots.
- ONE FRAME ONLY: every image is ONE continuous full frame, like a single frame from a film. Never comic panels, page layouts, storyboards, collages, split screens or multiple versions of a scene.
- NO READABLE TEXT: never ask for readable text, words, signs with lettering, neon lettering, title cards, headlines, or documents/screens/phones with words on them (the image AI turns them into garbled fake text). Show those objects without legible text: "a blank hotel sign glowing red", "a laptop screen glowing in the dark".
- REAL VICTIMS: never depict a real victim's death, body, body parts, injuries or remains (never "Elisa floats in the tank", "a pale hand breaks the water", "the body in the river"). Show the place or object instead: the tank, the open hatch, the dark water, the empty room, the closed door.
- MEDIA SOURCE per shot: "image_source" (and "image_source_2".."_4") is "ai", "stock_video" or "real_photo", and "image_query" (and "_2".."_4") is a 2-5 word search query for that shot. real_photo = TRUE STORIES ONLY: a real place, building, vehicle, object, document or official sketch/wanted poster that exists in public archives (query = its real name, e.g. "Cecil Hotel Los Angeles", "Boeing 727"); NEVER private people, victims, bodies or crime-scene photos. stock_video = generic atmosphere with NO story character in it (rain on a window at night, fog between pine trees, a flickering hallway light, a city street at night). ai = every shot with a story character or a specific story moment. The first shot of scene 1 is always "ai". At most 3 real_photo shots and about 40% stock_video shots per video; fiction never uses real_photo.
- TRUE STORY VISUALS: keep objects, clothing, vehicles, buildings and era historically accurate. If the source doesn't establish a visual detail, keep it generic.
- CONSISTENCY: fill "locations" with the 1-3 key places (short "name" + fixed "look", max 20 words, matching the real place and era) and set each scene's "location". List recurring figures in "characters" (e.g. "the hijacker": "man in his 40s, short dark hair, dark business suit, thin black tie, sunglasses, 1970s"). In image prompts, refer to them by that exact name; their look is added automatically.
- PER-SHOT LOCATION: every image prompt has its own location field: "image_location", "image_location_2", "image_location_3", "image_location_4" = the exact "locations" name where THAT shot takes place, or "none" (object close-ups, sky, anything not in a listed place). An outdoor shot (forest, river, road, sky) never uses an indoor location like a cabin; if the story goes outside, add that outdoor place to "locations".
- OBJECT SHOTS: in a close-up of a thing (a note, a briefcase, money), the object is the subject: describe the object and the surface it lies on, nothing else; its location is "none".
- Write every image prompt as plain descriptive text, never labels like "SHOT:" or "SETTING:". The main subject + action + key object come in the first 12 words; then framing, lighting, mood.
- Every shot in the video is a different picture: never two prompts with nearly the same subject and framing.
- POP CULTURE HOOK: if the source says a famous movie, TV show, video game, song or book was based on or inspired by this (for example, the Beast of Gevaudan appears in Teen Wolf), add ONE short line near the end that connects it, e.g. "Sound familiar? It's the same beast from Teen Wolf." Put that title in the caption and one hashtag. ONLY use references stated in the source. Never invent or guess one; if the source has none, skip this.

SOUND EFFECTS
- For each scene, set "sfx" to ONE sound from this list that fits that moment, or "none": {sfx_list}
- Use sound effects on 2 to 4 scenes only. Never on the hook scene.

OTHER FIELDS
- title: the case name, 3-7 words.
- premise: one-sentence summary.
- hook_overlay: 2-5 word shocking on-screen text, e.g. "The perfect crime. Almost."
- hook_candidates: 3 DIFFERENT candidate first sentences for scene 1 (each max 18 words, strangest or most shocking detail first, never a date, year or place name). Scene 1 must start with the best one.
- twist_scene: 0-based index of the biggest turn.
- caption: line 1 = the exact phrase people type into search for this story (e.g. "What happened to D.B. Cooper?", "What is the Wendigo?"); the channel adds "illustrated horror story" itself. Line 2 = a question for comments. Max 150 characters. May use 1 emoji.
- hashtags: 5 topic hashtags without # (the case, place, legend or subject + its genre, e.g. dbcooper, unsolvedmysteries). The channel adds #illustratedhorror #horrorstory itself. Never fyp, foryou or viral. For true stories, hashtags and caption must match the source: never "unsolved" / #unsolved when the source gives an official ruling (e.g. a coroner's finding) or the case was solved.
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

def pick_case(history: list[dict], kind: str = "mystery") -> str | dict:
    """A topic title from the lists, or sometimes (discovery_share) a discovery lead dict with its own readable
    source text (old newspapers for mystery, LOC folklore / Dúchas for lore)."""
    try:
        import discover
        found = discover.lead(kind, history)
        if found and blocked_topic(found.get("title"), found.get("text", "")[:3000]):
            log(f"Discovery lead '{found.get('title')}' is a blocked topic: skipped")
        elif found:
            return found
    except Exception as e:  # noqa: BLE001
        log(f"Discovery skipped ({str(e)[:120]})")
    file = LORE_FILE if kind == "lore" else CASES_FILE
    used = {h.get("case") for h in history if h.get("case")}
    fresh = [c for c in json.loads(file.read_text()) if c not in used and not blocked_topic(c)]
    if not fresh:
        raise RuntimeError(f"All topics in {file.name} have been used. Add more titles.")
    import trends
    return trends.pick(fresh)  # prefer a topic whose Wikipedia views just jumped


def wiki_url(title: str) -> str:
    """'es:Chalino Sánchez' -> the Spanish article's URL; a plain title = English Wikipedia."""
    lang, _, name = title.partition(":") if re.match(r"^[a-z]{2}:", title) else ("en", "", title)
    return f"https://{lang}.wikipedia.org/wiki/{name.strip().replace(' ', '_')}"


def fetch_facts(title: str, limit: int = 9000) -> str:
    """Wikipedia article text; 'es:Title' reads another language's Wikipedia (Retry-After honored on 429)."""
    api = WIKI_API
    if re.match(r"^[a-z]{2}:", title):
        lang, title = title[:2], title[3:].strip()
        api = f"https://{lang}.wikipedia.org/w/api.php"
    for attempt in range(3):
        r = requests.get(api, headers=HEADERS, timeout=30, params={
            "action": "query", "format": "json", "prop": "extracts", "explaintext": 1,
            "redirects": 1, "titles": title,
        })
        if r.status_code != 429:
            break
        wait = min(60, int(r.headers.get("Retry-After") or 20 * (attempt + 1)))
        log(f"Wikipedia 429 for '{title}': waiting {wait}s")
        time.sleep(wait)
    r.raise_for_status()
    pages = r.json()["query"]["pages"]
    text = next(iter(pages.values())).get("extract", "")
    if len(text) < 800:
        raise RuntimeError(f"Wikipedia article for '{title}' is missing or too short")
    return _split_wiki(text, limit)


def build_prompt(channel: str, case: str | dict, sfx_list: str = "none", kind: str = "mystery",
                 holder: dict | None = None) -> tuple[str, str]:
    """holder: a dict that collects story["sources"] (Wikipedia page + research sources)."""
    if isinstance(case, dict):  # discovery lead / topic file: its readable source text is the base
        facts = f"SOURCE: {case.get('source')} - {case.get('url')}\n{case['text'][:12000]}"
        case = case["title"]
    else:
        facts = fetch_facts(case)
        if holder is not None:
            holder.setdefault("sources", []).append({"title": f"Wikipedia: {case}", "url": wiki_url(case),
                                                     "domain": "en.wikipedia.org"})
    if holder is not None:  # Gemini + Google Search grounding: 3-6 more sources (Wikipedia stays the base)
        import research
        facts = research.add_to(facts, holder, case, "legend / folklore" if kind == "lore" else "real mystery")
    log(f"Topic: {case} ({len(facts)} chars of source)")
    template = LORE_PROMPT if kind == "lore" else MYSTERY_PROMPT
    from common import mark_source
    words = "{} to {}".format(*CONFIG.get("story_words", [138, 152]))
    return template.format(channel=channel, case=case, facts=mark_source(facts), sfx_list=sfx_list,
                           words=words), facts
