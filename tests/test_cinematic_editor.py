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
import render as classic_render  # noqa: E402
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
        self.assertEqual(tr[1], "cut")  # graphic alone is not a transition
        self.assertEqual(tr[2], "dissolve")  # time cue at a scene change
        self.assertEqual(tr[3], "cut")  # location/map changes can hard cut
        self.assertEqual(tr[4], "cut")  # impact lands hard
        self.assertEqual([s["transition"] for s in segs], tr)

    def test_no_decorative_effects_on_graphics(self):
        segs = self._segs([("image", None, 0)] + [("graphic", "evidence", k) for k in range(1, 12)])
        words = []
        for k in range(1, 12):
            words += _words("Suddenly the door burst open.", k, segs[k]["start"])
        tr = explainer.plan_transitions(segs, words)
        for a, b in zip(tr, tr[1:]):
            self.assertFalse(a == b and a != "cut", tr)
        self.assertEqual(tr.count("swoosh"), 0)
        self.assertEqual(set(tr), {"cut"})
        self.assertGreater(tr.count("cut"), 0)

    def test_mood_and_place_are_not_time_passage(self):
        segs = self._segs([("image", None, 0), ("image", None, 1), ("image", None, 2)])
        words = (_words("The fog hid the empty road.", 1, 2.5)
                 + _words("They arrived at the station.", 2, 5.0))
        self.assertEqual(explainer.plan_transitions(segs, words), ["cut", "cut", "cut"])

    def test_explicit_time_passage_dissolves_once_not_repeated(self):
        segs = self._segs([("image", None, 0), ("image", None, 1),
                           ("image", None, 2), ("image", None, 3)])
        words = (_words("Years later the house reopened.", 1, 2.5)
                 + _words("The next morning they returned.", 2, 5.0)
                 + _words("At midnight someone called.", 3, 7.5))
        self.assertEqual(explainer.plan_transitions(segs, words), ["cut", "dissolve", "cut", "cut"])

    def test_legacy_modes_only_produce_real_hard_cuts(self):
        for mode in classic_render.VISUAL_MODES:
            self.assertEqual(classic_render._transitions([True, False, True], mode),
                             [("cut", 0.0)] * 3)

    def test_legacy_ffmpeg_join_uses_concat_not_one_frame_fade(self):
        with mock.patch.object(classic_render, "_frame_count", side_effect=[60, 60]), \
             mock.patch.object(classic_render, "media_duration", return_value=4.0), \
             mock.patch.object(classic_render, "run") as runner:
            classic_render._join([Path("a.mp4"), Path("b.mp4")],
                                 [2.0, 2.0], [True, True], Path("out.mp4"))
        cmd = runner.call_args.args[0]
        filters = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("concat=n=2:v=1:a=0", filters)
        self.assertNotIn("xfade=", filters)

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
        p = sprites.asset_path("P08")
        want = json.loads((ROOT / "assets" / "poses" / "asset_checksums.json").read_text())["P08_shrugging.png"]
        self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(), want)
        self.assertEqual(sprites.POSE_FOR["choice"], "P08")
        with self.assertRaises(sprites.MissingAsset):
            sprites.asset_path("P07")  # not in the approved manifest: never picked

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

    def test_choice_pose_only_on_a_real_choice(self):
        seen = {}

        def fake(intent, ids, fallback):
            seen["ids"] = ids
            return fallback
        import library
        with mock.patch.object(library, "best_approved_asset", side_effect=fake):
            sprites.select_for_beat("And running away isn't always an option.", "serious", allow_poses=False)
            self.assertFalse(any(i.startswith("P") for i in seen["ids"]), seen["ids"])
            sprites.select_for_beat("Red or blue?", "thinking", allow_poses=True)
            self.assertIn("P08", seen["ids"])

    def test_visual_qa_accepts_p08_as_approved(self):
        self.assertIn("P08", {r["id"] for r in sprites.approved_registry()["approved"]})


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
        self.assertEqual([s["transition"] for s in m["shots"]], ["cut", "cut"])
        self.assertEqual([w["accent"] for w in m["words"]], [False, True])
        jsx = (ROOT / "remotion" / "src" / "polish.jsx").read_text()
        self.assertNotIn('x.transition==="swoosh"', jsx)  # no decorative sweep layer
        self.assertIn("hit&&w.accent", jsx)  # underline only accented words
        self.assertIn('x.kind==="host"', jsx)  # captions move up while a host bust is on screen


if __name__ == "__main__":
    unittest.main()



class WhisperNarrationDiagnostics(unittest.TestCase):
    """Mock model/renderer only: exercise real shared-editor routing for folklore, fiction and true mystery."""

    @staticmethod
    def _story_and_words(text: str):
        return {"scenes": [{"narration": text}]}, {"words": _words(text), "duration": 3.5}

    def _build_without_rendering(self, text: str, *, whisper_error: bool):
        from contextlib import ExitStack
        story, narration = self._story_and_words(text)
        image_dir = ROOT / "test-whisper-offline-no-files"
        video = image_dir / "mocked.mp4"
        base_report = {
            "shots": {"image": 1, "graphic": 0, "host": 0},
            "runtime_share": {"image": 1.0, "graphic": 0.0, "host": 0.0},
            "media_used": {"stock": 0, "ai_reconstruction": 1},
            "ai_images": {"successful": 0}, "exceptions": [], "failures": []
        }
        result = {"model": "openai/whisper-base", "coverage": 0.93,
                  "median_offset_s": 0.04, "not_heard": []}
        with ExitStack() as patches:
            patches.enter_context(mock.patch.dict(explainer.CONFIG, {"whisper_narration_check": True}))
            patches.enter_context(mock.patch.object(sprites, "require_all"))
            patches.enter_context(mock.patch.object(explainer, "story_images", return_value=[[]]))
            patches.enter_context(mock.patch.object(explainer, "plan_graphics", return_value=[]))
            patches.enter_context(mock.patch("checkpoint.write_atomic"))
            patches.enter_context(mock.patch("checkpoint.register_image"))
            patches.enter_context(mock.patch.object(explainer, "_total", return_value=3.5))
            patches.enter_context(mock.patch.object(explainer, "sequence", return_value=[]))
            patches.enter_context(mock.patch.object(explainer, "render", return_value=(video, object())))
            patches.enter_context(mock.patch.object(explainer, "visual_qa", return_value=base_report))
            written = patches.enter_context(mock.patch.object(explainer, "write_reports"))
            if whisper_error:
                verify = patches.enter_context(mock.patch.object(
                    explainer, "verify_narration", side_effect=OSError("local model unavailable")))
            else:
                verify = patches.enter_context(mock.patch.object(
                    explainer, "verify_narration", return_value=result))
            built = explainer.build(story, narration, image_dir, image_dir)
        self.assertEqual(built, video)
        verify.assert_called_once_with(video, narration)
        written.assert_called_once()
        return story, base_report

    def test_whisper_report_only_on_three_unrelated_story_types(self):
        cases = {
            "legend": "A spirit whispered red or blue through the bathroom stall.",
            "fiction": "At midnight the locked house gained another room.",
            "true_mystery": "In 1937 the pilot disappeared during a flight across the Pacific.",
        }
        for genre, text in cases.items():
            with self.subTest(genre=genre):
                story, rep = self._build_without_rendering(text, whisper_error=False)
                self.assertEqual(story["narration_check"]["status"], "checked")
                self.assertAlmostEqual(rep["narration_check"]["coverage"], 0.93)
                self.assertEqual(rep["failures"], [])

    def test_whisper_download_failure_never_blocks_completed_video(self):
        for text in ("A strange figure waited by the door.",
                     "The pilot never returned from the island."):
            story, rep = self._build_without_rendering(text, whisper_error=True)
            self.assertEqual(story["narration_check"]["status"], "unavailable")
            self.assertIn("OSError", rep["narration_check"]["reason"])
            self.assertEqual(rep["failures"], [])

    def test_local_whisper_report_matches_mocked_audio_timestamps(self):
        import numpy as np
        narration = {"words": _words("The door creaked open", start=0, step=0.4)}
        transcript = [
            {"text": "The", "timestamp": (0.0, 0.2)},
            {"text": "door", "timestamp": (0.4, 0.65)},
            {"text": "creaked", "timestamp": (0.8, 1.0)},
            {"text": "open", "timestamp": (1.2, 1.4)},
        ]
        dummy_audio = np.zeros(24000, dtype=np.float32).tobytes()
        # CI deliberately omits optional inference packages; mock the module itself without installing weights.
        fake_transformers = mock.Mock(
            pipeline=mock.Mock(return_value=lambda *args, **kwargs: {
                "chunks": transcript, "text": "The door creaked open"}))
        with mock.patch.object(explainer.subprocess, "run",
                               return_value=mock.Mock(stdout=dummy_audio)), \
             mock.patch.dict(sys.modules, {"transformers": fake_transformers}):
            report = explainer.verify_narration(Path("not-read.mp4"), narration)
        fake_transformers.pipeline.assert_called_once_with(
            "automatic-speech-recognition", model="openai/whisper-base", device="cpu")
        self.assertEqual(report["coverage"], 1.0)
        self.assertEqual(report["not_heard"], [])
        self.assertEqual(report["late_or_early_over_0_3s"], 0)

    def test_whisper_flag_is_enabled_but_never_blocks_video(self):
        self.assertTrue(explainer.CONFIG.get("whisper_narration_check", False))


class NarratedYearTimelineOnPhoto(unittest.TestCase):
    """The current Night Files renderer draws a progressing date overlay on a real frame."""

    def test_timeline_reveals_only_real_spoken_year_and_retains_image(self):
        from PIL import Image, ImageChops

        scene = {"scenes": [{"narration": "In March 1922, they investigated the farmhouse."}],
                 "true_story": True, "fact_ledger": ["Date: 1922"]}
        card = explainer._date_graphic(scene, 0, explainer._scene_ctx(scene, 0, {"cast": {}, "dates": 0}))
        self.assertEqual(card["fields"]["year"], "1922")
        self.assertEqual(card["fields"]["label"].lower(), "march")
        base = Image.new("RGBA", (1080, 1920), (30, 45, 67, 255))
        ctx = {"bg": base, "accent": (240, 23, 103)}
        before = noir.render("date_stamp", card["fields"], 0.0, 2.6, ctx)
        arrived = noir.render("date_stamp", card["fields"], 1.6, 2.6, ctx)
        self.assertEqual(arrived.size, (1080, 1920))
        self.assertIsNotNone(ImageChops.difference(before.convert("RGB"), arrived.convert("RGB")).getbbox())
        # The original full-frame photograph remains visible outside the minimal line.
        self.assertEqual(arrived.getpixel((30, 450)), base.getpixel((30, 450)))
        self.assertEqual(arrived.getpixel((30, 1300)), base.getpixel((30, 1300)))
        red = arrived.getpixel((865, 920))
        self.assertGreater(red[0], red[1] + 95)  # terminal marker is red
        self.assertGreater(red[0], red[2] + 80)


    def test_only_first_grounded_date_has_timeline(self):
        story = {"true_story": True,
                 "fact_ledger": ["Event date: March 31st", "Report: 1922", "Other event: 1930"],
                 "scenes": [
                     {"narration": "On March 31st, someone approached the farmhouse."},
                     {"narration": "In 1922 investigators arrived at the property."},
                     {"narration": "In 1930, nothing was left in the building."},
                 ]}
        n = {"words": [], "duration": 20.0}
        for i, scene in enumerate(story["scenes"]):
            n["words"] += _words(scene["narration"], scene=i, start=i * 6.0)
        with mock.patch.object(explainer, "_plan_call", return_value=None):
            graphics = explainer.plan_graphics(story, n)
        dates = [(i, g) for i, cards in enumerate(graphics) for g in cards
                 if g["template"] == "date_stamp"]
        self.assertEqual(len(dates), 1, dates)
        self.assertEqual(dates[0][0], 0)
        self.assertEqual(dates[0][1]["fields"]["day"], 31)
        self.assertEqual(dates[0][1]["fields"]["month"], "March")

    def test_spoken_first_year_wins_even_if_later_year_smaller(self):
        story = {"true_story": True, "fact_ledger": ["1930", "1922"],
                 "scenes": [{"narration": "In 1930, archivists discovered a record from 1922."}]}
        g = explainer._date_graphic(story, 0, explainer._scene_ctx(story, 0, {"cast": {}, "dates": 0}))
        self.assertEqual(g["fields"]["year"], "1930")

    def test_month_day_card_renders_over_story_image(self):
        from PIL import Image, ImageChops
        fields = {"month": "March", "day": 31, "label": "March 31st", "kicker": "WHEN"}
        img = Image.new("RGBA", (1080, 1920), (28, 61, 82, 255))
        first = noir.render("date_stamp", fields, 0.02, 2.4, {"bg": img, "accent": (240, 23, 103)})
        last = noir.render("date_stamp", fields, 1.8, 2.4, {"bg": img, "accent": (240, 23, 103)})
        self.assertTrue(ImageChops.difference(first.convert("RGB"), last.convert("RGB")).getbbox())
        self.assertEqual(last.getpixel((30, 1300)), img.getpixel((30, 1300)))
        self.assertGreater(last.getpixel((865, 921))[0], last.getpixel((865, 921))[1] + 95)
        sc = {"scenes": [{"narration": "On March 31st, the farmhouse was empty."}],
              "true_story": True, "fact_ledger": ["Report: March 31st"]}
        self.assertIsNone(explainer.graphic_problem(sc, 0, {"template": "date_stamp", "fields": fields}))
        sc["fact_ledger"] = ["Report: March 30th"]
        self.assertIn("ledger", explainer.graphic_problem(sc, 0, {"template": "date_stamp", "fields": fields}))

    def test_unsourced_year_cannot_trigger_true_story_date(self):
        sc = {"scenes": [{"narration": "In 1922, the family moved."}], "true_story": True,
              "fact_ledger": ["Date: 1931"]}
        self.assertIsNone(explainer._date_graphic(sc, 0, explainer._scene_ctx(sc, 0, {"cast": {}, "dates": 0})))

