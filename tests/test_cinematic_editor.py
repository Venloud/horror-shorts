"""Night Files universal editor: editorial intelligence in explainer.py (owner, Oct 25). Offline, story-agnostic:
legends, true stories, fiction, phones, routes, dates. No model call, no publishing, no buffer / history writes.
  python -m unittest discover -s tests -p test_cinematic_editor.py -v
"""
import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import explainer  # noqa: E402
import noir  # noqa: E402
import sprites  # noqa: E402


def _words(text: str, scene: int = 0, start: float = 0.0, step: float = 0.4) -> list[dict]:
    out = []
    for k, w in enumerate(text.split()):
        out.append({"word": w, "start": round(start + k * step, 3), "end": round(start + k * step + 0.3, 3),
                    "scene": scene})
    return out


class SemanticPhrases(unittest.TestCase):
    def test_choose_red_not_choose_covered(self):
        p = explainer.key_phrases("Choose red, and the legend says you'll be covered in blood.")
        self.assertEqual([x["text"] for x in p], ["CHOOSE RED", "COVERED IN BLOOD"])
        self.assertNotIn("CHOOSE COVERED", " ".join(x["text"] for x in p))
        self.assertEqual(p[1]["accent"], "BLOOD")

    def test_phrases_never_cross_clauses_and_edges_are_content_words(self):
        texts = [
            "On March third, 1922, the steamer left Boston for Halifax and never arrived.",
            "The keeper climbed the stairs, and the lamp went dark.",
            "Three men vanished from the lighthouse in nineteen hundred.",
            "Working at Spadina Military Hospital, you listen as Amelia hears stories of pilots.",
            "A text from Mara arrived at midnight: \"Don't open the door.\"",
        ]
        for t in texts:
            clauses = [c.upper() for c in explainer.clauses(t)]
            for p in explainer.key_phrases(t):
                self.assertTrue(any(p["text"] in c.upper().replace("’", "'") for c in clauses), (t, p))
                first, last = p["text"].split()[0].lower(), p["text"].split()[-1].lower()
                self.assertNotIn(last, explainer.FUNCTION, p)
                self.assertTrue(first not in explainer.FUNCTION or first.endswith("n't"), p)
                self.assertIn(p["accent"], p["text"].split())  # the accent is inside its own phrase

    def test_generic_words_are_never_the_accent_and_weak_beats_get_no_card(self):
        weak = "The mysterious woman wearing a long coat appears at the station every winter."
        self.assertEqual(explainer.key_phrases(weak), [])
        self.assertEqual(explainer._meaningful_accent("mysterious", ["A MYSTERIOUS FIGURE"]), "")
        self.assertEqual(explainer._meaningful_accent("wearing", ["WEARING A RED CLOAK"]), "")
        self.assertEqual(explainer._meaningful_accent("blood", ["COVERED IN BLOOD"]), "blood")
        self.assertEqual(explainer._meaningful_accent("blood", ["CHOOSE RED"]), "")  # not on the graphic

    def test_impact_fallback_is_coherent_or_absent(self):
        story = {"scenes": [{"narration": "Choose red, and the legend says you'll be covered in blood."},
                            {"narration": "The mysterious woman wearing a long coat appears every winter."}]}
        g = explainer._impact_fallback(story, 0)
        self.assertEqual(g["fields"]["lines"], ["CHOOSE RED", "COVERED IN BLOOD"])
        self.assertEqual(g["fields"]["accent"], "BLOOD")
        self.assertIsNone(explainer.graphic_problem(story, 0, g))
        self.assertIsNone(explainer._impact_fallback(story, 1))  # a clean picture beats random words

    def test_choice_detection_is_grounded(self):
        self.assertEqual(explainer.choice_options("Imagine someone whispers from the next stall, \"Red or blue?\""),
                         ("RED", "BLUE"))
        self.assertEqual(explainer.choice_options("Open the door, or don't?"), ("OPEN THE DOOR", "DON'T"))
        self.assertEqual(explainer.choice_options("Which do you trust: the map or the voice?"), ("MAP", "VOICE"))
        self.assertIsNone(explainer.choice_options("He could turn left or right, but the road was flooded."))
        self.assertIsNone(explainer.choice_options("The ship sailed from Boston or nearby, records disagree."))

    def test_viewer_beats(self):
        self.assertEqual(explainer.viewer_beat("Red or blue?"), ("choice", "thinking"))
        self.assertEqual(explainer.viewer_beat("Don't pick a color."), ("warning", "worried"))
        self.assertEqual(explainer.viewer_beat("Refuse both choices and walk away."), ("decision", "serious"))
        self.assertIsNone(explainer.viewer_beat("The steamer left Boston in 1922."))
        for kind, mood in [explainer.viewer_beat(t) for t in ("Red or blue?", "Don't pick a color.",
                                                              "Refuse both and walk away.", "Imagine the silence.")]:
            self.assertIn(mood, sprites.FACES)  # every mood is an approved expression


class Transitions(unittest.TestCase):
    def _segs(self, kinds):
        segs, t = [], 0.0
        for k, (kind, tpl, scene) in enumerate(kinds):
            shot = {"type": kind, "scene": scene}
            if tpl:
                shot["template"] = tpl
            segs.append({"start": t, "end": t + 2.5, "shot": shot, "scene": scene})
            t += 2.5
        return segs

    def test_context_choices(self):
        segs = self._segs([("image", None, 0), ("graphic", "date_stamp", 0), ("image", None, 1),
                           ("graphic", "map_route", 1), ("graphic", "impact", 1), ("image", None, 2)])
        words = (_words("It was a quiet night.", 0, 0) + _words("Years later the ship crossed toward the reef.", 1, 5)
                 + _words("The mask came off.", 2, 12.5))
        tr = explainer.plan_transitions(segs, words)
        self.assertEqual(tr[0], "cut")
        self.assertEqual(tr[1], "pop")  # small date stamp
        self.assertEqual(tr[2], "dissolve")  # time cue at a scene change
        self.assertEqual(tr[3], "slide")  # a route: real progression
        self.assertEqual(tr[4], "cut")  # impact lands hard
        self.assertEqual([s["transition"] for s in segs], tr)

    def test_no_accent_effect_twice_in_a_row_and_rare_swooshes(self):
        segs = self._segs([("image", None, 0)] + [("graphic", "evidence", k) for k in range(1, 12)])
        words = []
        for k in range(1, 12):
            words += _words("Suddenly the door burst open.", k, segs[k]["start"])
        tr = explainer.plan_transitions(segs, words)
        for a, b in zip(tr, tr[1:]):
            self.assertFalse(a == b and a != "cut", tr)
        self.assertLessEqual(tr.count("swoosh"), 2)
        self.assertGreater(tr.count("cut"), 0)

    def test_motion_allows_stillness_but_not_repeats(self):
        segs = self._segs([("image", None, k) for k in range(8)])
        words = []
        for k in range(8):
            words += _words("The mask lifted and revealed a face." if k in (2, 3) else "The road went on.", k,
                            segs[k]["start"])
        m = explainer.plan_motion(segs, words)
        self.assertIn("still", m)
        for a, b in zip(m, m[1:]):
            self.assertNotEqual(a, b)


class ViewerSurrogate(unittest.TestCase):
    def test_p08_is_checksum_verified_and_unchanged(self):
        p = sprites.pose_path("P08")
        want = json.loads((ROOT / "assets" / "poses" / "asset_checksums.json").read_text())["P08_shrugging.png"]
        self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(), want)
        self.assertEqual(sprites.POSE_FOR["choice"], "P08")
        with self.assertRaises(sprites.MissingAsset):
            sprites.pose_path("P07")  # not approved for automatic use

    def test_choice_graphic_planned_and_rendered_with_p08(self):
        story = {"scenes": [{"narration": "Someone whispers from the next stall, \"Red or blue?\""}],
                 "true_story": False}
        g = explainer._auto_graphics(story, 0, explainer._scene_ctx(story, 0, {"cast": {}, "dates": 0}))
        self.assertEqual(g[0]["template"], "choice")
        self.assertEqual((g[0]["fields"]["left"], g[0]["fields"]["right"]), ("RED", "BLUE"))
        self.assertIsNone(explainer.graphic_problem(story, 0, g[0]))
        used = set()
        ctx = {"accent": (240, 23, 103), "words": [{"word": "Red", "start": 0.2}, {"word": "blue?", "start": 0.6}],
               "bg": None, "used_assets": used, "tone": "midnight", "seed": 1}
        frame = noir.render("choice", g[0]["fields"], 1.5, 2.5, ctx)
        self.assertEqual(frame.size, (1080, 1920))
        self.assertIn("P08", used)
        # red and blue orbs sit on the open palms
        px = frame.convert("RGB").load()
        reds = sum(1 for x in range(0, 1080, 6) for y in range(300, 1000, 6) if px[x, y][0] > 170 and px[x, y][2] < 90)
        blues = sum(1 for x in range(0, 1080, 6) for y in range(300, 1000, 6) if px[x, y][2] > 170 and px[x, y][0] < 90)
        self.assertGreater(reds, 20)
        self.assertGreater(blues, 20)

    def test_missing_pose_falls_back_to_options_without_substitute_art(self):
        used = set()
        ctx = {"accent": (240, 23, 103), "words": [], "bg": None, "used_assets": used, "tone": "midnight", "seed": 1}
        with mock.patch.object(sprites, "pose", side_effect=sprites.MissingAsset("P08", "is missing")):
            frame = noir.render("choice", {"left": "MAP", "right": "VOICE"}, 2.0, 2.5, ctx)
        self.assertEqual(frame.size, (1080, 1920))
        self.assertEqual(used, set())

    def test_visual_qa_accepts_p08_as_approved(self):
        self.assertIn("P08", sprites.POSES)


class ContextGraphicsAndSound(unittest.TestCase):
    def test_phone_message_is_a_phone_insert_with_its_own_cue(self):
        story = {"scenes": [{"narration": "At midnight a text from Mara arrived: \"Don't open the door.\""}]}
        g = explainer._auto_graphics(story, 0, explainer._scene_ctx(story, 0, {"cast": {}, "dates": 0}))
        phone = next(x for x in g if x["template"] == "phone")
        self.assertEqual(phone["fields"]["text"], "Don't open the door.")
        self.assertEqual(phone["fields"]["from"], "Mara")
        self.assertFalse(any(x["template"] == "quote" for x in g))  # not shown twice
        segs = [{"start": 0.0, "end": 2.0, "shot": {"type": "image", "scene": 0}, "scene": 0, "transition": "cut"},
                {"start": 2.0, "end": 4.5, "shot": dict(phone, scene=0), "scene": 0, "transition": "pop"}]
        narr = {"words": _words(story["scenes"][0]["narration"]), "duration": 5.0}
        ev = explainer.sound_plan({"scenes": story["scenes"]}, narr, segs)
        self.assertIn("phone_notification", [e[1] for e in ev])
        self.assertNotIn("whoosh", [e[1] for e in ev])  # a pop is not a swoosh

    def test_ui_clicks_are_rationed(self):
        segs = [{"start": 4.0 * k, "end": 4.0 * k + 4, "scene": k, "transition": "pop",
                 "shot": {"type": "graphic", "template": "date_stamp", "scene": k}} for k in range(1, 12)]
        ev = explainer.sound_plan({"scenes": []}, {"words": []}, segs)
        clicks = [e for e in ev if e[1] == "ui_click"]
        self.assertLessEqual(len(clicks), 3)
        self.assertTrue(all(b[0] - a[0] >= 10.0 for a, b in zip(clicks, clicks[1:])))

    def test_weak_one_word_and_name_only_cards_are_dropped(self):
        for t in ("He's making you choose how your story ends.", "The sheriff found Nora's phone in the yard."):
            self.assertIsNone(explainer._impact_fallback({"scenes": [{"narration": t}]}, 0), t)

    def test_event_sfx_only_for_described_events(self):
        narr = {"words": _words("The night was quiet and long. She ran across the gravel yard. "
                                "If you hear knocking, never answer. The door slammed shut behind her.", step=0.5)}
        ev = explainer.event_sfx(narr)
        names = [e[1] for e in ev]
        self.assertIn("footsteps_gravel", names)  # surface chosen from the words
        self.assertIn("door_slam", names)
        self.assertNotIn("knocking", names)  # hypothetical: "if you hear"
        self.assertLessEqual(len(ev), 4)
        self.assertTrue(all(e[0] >= 1.5 for e in ev))  # never on the hook
        mood = {"words": _words("A dark and eerie silence filled the old house.", step=0.5)}
        self.assertEqual(explainer.event_sfx(mood), [])  # a mood is not a sound: silence

    def test_clap_unverified_recordings_are_never_used(self):
        with mock.patch.object(explainer, "sfx_index", return_value={"files": {"thunder": {"verified": False}}}):
            ev = explainer.event_sfx({"words": _words("It was late. Then thunder rolled over the hills.", step=0.5)})
        self.assertNotIn("thunder", [e[1] for e in ev])

    def test_committed_clap_index_covers_the_library(self):
        idx = explainer.sfx_index()
        self.assertEqual(idx.get("model"), "laion/clap-htsat-unfused")
        for name in ("footsteps_gravel", "door_slam", "phone_notification", "thunder"):
            self.assertTrue(idx["files"][name]["verified"], name)

    def test_caption_accents_are_few_and_meaningful(self):
        story = {"scenes": [{"narration": "Choose red, and the legend says you'll be covered in blood."},
                            {"narration": "The mysterious woman appears every winter."}]}
        words = _words(story["scenes"][0]["narration"], 0) + _words(story["scenes"][1]["narration"], 1, 6)
        acc = explainer.caption_accents(story, {"words": words})
        self.assertEqual(len(acc), 1)
        self.assertIn(words[min(acc)]["word"].strip(".,").lower(), ("red", "blood"))

    def test_remotion_gets_accents_and_transitions_only(self):
        from remotion_post import manifest
        segs = [{"start": 0, "end": 1, "shot": {"type": "image"}, "transition": "cut"},
                {"start": 1, "end": 2, "shot": {"type": "graphic", "template": "evidence"}, "transition": "swoosh"}]
        m = manifest(Path("/tmp/a.mp4"), Path("/tmp/b.mp4"), segs,
                     {"words": [{"word": "a", "start": 0.1, "end": 0.3}, {"word": "blood", "start": 0.4, "end": 0.7}]},
                     24, 48, accents={1})
        self.assertEqual([s["transition"] for s in m["shots"]], ["cut", "swoosh"])
        self.assertEqual([w["accent"] for w in m["words"]], [False, True])
        jsx = (ROOT / "remotion" / "src" / "polish.jsx").read_text()
        self.assertIn('x.transition==="swoosh"', jsx)  # the sweep only on a planned swoosh
        self.assertIn("hit&&w.accent", jsx)  # underline only accented words
        self.assertIn('x.kind==="host"', jsx)  # captions move up while a host bust is on screen


if __name__ == "__main__":
    unittest.main()
