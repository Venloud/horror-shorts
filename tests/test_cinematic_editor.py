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


class MotionEffects(unittest.TestCase):
    """Owner, Oct 31: cover <= 1 s, title overlay (no title card), the first date scrolls in on a year reel and every
    later date is a timeline line from the previous one, one big effect per 3 s, typing / reel sounds in sync."""

    TRUE = {"title": "The Lighthouse Keepers", "true_story": True,
            "fact_ledger": ["Arrival: 1890", "Vanishing date: March 31, 1900", "Report: 1902", "Crew: three men"],
            "scenes": [
                {"narration": "The lamp was still burning when the relief boat finally reached the rock."},
                {"narration": "The keepers had arrived in eighteen ninety and kept the light for ten years."},
                {"narration": "On March thirty-first, nineteen hundred, all three men vanished from the island."},
                {"narration": "The board's report in nineteen oh two blamed a wave, but nobody saw it."},
                {"narration": "Their oilskins were still hanging by the door, untouched."}]}

    def _narr(self, story, step=0.42):
        words, t = [], 0.0
        for i, sc in enumerate(story["scenes"]):
            words += _words(sc["narration"], scene=i, start=t, step=step)
            t = words[-1]["end"] + 0.4
        return {"words": words, "duration": t, "scene_times": []}

    def _segs(self, story, narr, kinds=None):
        segs, t = [], 0.0
        per = narr["duration"] / len(story["scenes"])
        for i in range(len(story["scenes"])):
            kind = (kinds or {}).get(i, "image")
            shot = ({"type": "image", "file": f"/x/scene_{i:02d}a.png", "crop": "full"} if kind == "image"
                    else {"type": kind, "template": "evidence", "fields": {}})
            segs.append({"start": round(t, 3), "end": round(t + per, 3), "shot": dict(shot, scene=i), "scene": i,
                         "transition": "cut"})
            t += per
        return segs

    def test_title_duration_formula(self):
        self.assertEqual(noir.title_seconds("Bell"), 3.5)                      # never under 3.5 s
        self.assertEqual(noir.title_seconds("one two three four five six"), 3.6)  # 1.5 + 0.35 x 6
        self.assertEqual(noir.title_seconds(" ".join(["w"] * 20)), 6.0)       # never over 6 s

    def test_cover_is_at_most_one_second_and_title_starts_after_it(self):
        cover = float(explainer.CONFIG.get("cover_seconds"))
        self.assertLessEqual(cover, 1.0)
        story = json.loads(json.dumps(self.TRUE))
        n = self._narr(story)
        eff = explainer.plan_effects(story, n, self._segs(story, n))
        title = eff[0]
        self.assertEqual(title["kind"], "title")
        self.assertAlmostEqual(title["start"], cover)
        self.assertEqual(title["dur"], noir.title_seconds(story["title"]))
        self.assertEqual(title["fields"]["kicker"], "TRUE STORY")
        self.assertNotIn("true_story", noir.TEMPLATES)  # no title / TRUE STORY card in front of the story
        self.assertNotIn("title", noir.TEMPLATES)

    def test_year_reel_timing_lands_on_the_spoken_word(self):
        vals = noir.reel_values(1898)
        self.assertEqual(vals[0], 1890)
        self.assertEqual(vals[-1], 1898)
        land = noir.REEL_TRAVEL
        self.assertEqual(noir.reel_position(0.0, len(vals), land), 0.0)
        self.assertEqual(noir.reel_position(land, len(vals), land), len(vals) - 1)
        ticks = noir.reel_ticks(len(vals), land)
        self.assertEqual(len(ticks), len(vals) - 1)              # one tick per passing year
        self.assertEqual(ticks, sorted(ticks))
        self.assertAlmostEqual(ticks[-1], land, places=3)       # the last one is the landing
        for k, tt in enumerate(ticks, start=1):                 # the reel really is on that year at its tick
            self.assertAlmostEqual(noir.reel_position(tt, len(vals), land), k, places=2)
        story = json.loads(json.dumps(self.TRUE))
        n = self._narr(story)
        eff = explainer.plan_effects(story, n, self._segs(story, n))
        reel = next(e for e in eff if e["kind"] == "year_reel")
        spoken = next(w["start"] for w in n["words"] if w["word"] == "eighteen")
        self.assertAlmostEqual(reel["start"] + reel["fields"]["land"], spoken, places=3)
        self.assertEqual(reel["fields"]["values"][-1], 1890)
        land_sfx = [x for x in reel["sfx"] if x[1] == "reel_land"]
        self.assertAlmostEqual(land_sfx[0][0], spoken, places=3)
        pitches = [x[4]["pitch"] for x in reel["sfx"] if x[1] == "reel_tick"]
        self.assertEqual(pitches, sorted(pitches))  # rising

    def test_landed_year_is_red_and_heavier_before_it_is_not(self):
        f = {"values": noir.reel_values(1900), "land": noir.REEL_TRAVEL, "label": "MARCH 31", "kicker": "WHEN"}
        before = noir.overlay("year_reel", f, 0.3, 3.0, {})
        after = noir.overlay("year_reel", f, noir.REEL_TRAVEL + 0.5, 3.0, {})
        def reds(im):
            px = im.crop((300, 680, 780, 840)).getdata()
            return sum(1 for r, g, b, a in px if a > 200 and r > 200 and g < 80)
        self.assertEqual(reds(before), 0)
        self.assertGreater(reds(after), 500)

    def test_first_date_reel_later_dates_lines_from_the_previous_date(self):
        story = json.loads(json.dumps(self.TRUE))
        n = self._narr(story)
        eff = explainer.plan_effects(story, n, self._segs(story, n))
        dates = [e for e in eff if e["kind"] in ("year_reel", "year_line")]
        self.assertEqual(dates[0]["kind"], "year_reel")
        self.assertTrue(all(e["kind"] == "year_line" for e in dates[1:]), dates)
        line = dates[1]
        self.assertEqual(line["fields"]["from"], "1890")
        self.assertEqual(line["fields"]["to"], "1900")
        self.assertEqual(line["fields"]["bumps"], 9)
        self.assertEqual(line["fields"]["label"], "MARCH 31")
        self.assertEqual(noir.line_bumps(99), 12)                 # a century is not 99 bumps
        ticks = noir.line_ticks(3)
        self.assertEqual(ticks, sorted(ticks))
        self.assertLess(ticks[-1], noir.REEL_TRAVEL)

    def test_unsourced_year_never_animates_in_a_true_story(self):
        story = {"title": "x", "true_story": True, "fact_ledger": ["Date: 1931"],
                 "scenes": [{"narration": "In 1922, the family moved."}]}
        self.assertEqual(explainer.date_mentions(story, self._narr(story)), [])
        story["true_story"] = False  # fiction / legend: the narration itself is the source
        self.assertEqual([d["target"] for d in explainer.date_mentions(story, self._narr(story))], [1922])

    def test_effect_spacing_faces_and_cards(self):
        story = json.loads(json.dumps(self.TRUE))
        n = self._narr(story, step=0.3)
        segs = self._segs(story, n, kinds={4: "host"})
        eff = explainer.plan_effects(story, n, segs)
        big = [e for e in eff if e["big"]]
        for a, b in zip(big, big[1:]):
            self.assertGreaterEqual(b["anchor"] - a["anchor"], explainer.EFFECT_GAP - 1e-6, (a["kind"], b["kind"]))
            self.assertGreaterEqual(b["start"], a["start"] + a["dur"] - 1e-6)
        host = segs[4]
        for e in eff:  # never over the host's face
            self.assertFalse(e["start"] < host["end"] and host["start"] < e["start"] + e["dur"], e["kind"])

    def test_typing_clicks_match_the_typed_characters(self):
        c = {"kind": "typewriter", "start": 10.0, "dur": 3.0, "anchor": 10.0, "big": True,
             "fields": {"text": "Don't open it", "start": 0.15}}
        clicks = [x for x in explainer.effect_sfx(c) if x[1] == "typing_click"]
        self.assertEqual(len(clicks), len("Don'topenit"))
        self.assertTrue(all(x[2] <= 0.1 for x in clicks))          # quiet under the voice
        self.assertTrue(all(x[4].get("duck") for x in clicks))     # and ducked on a word peak

    def test_counter_only_for_a_clear_number_and_in_the_ledger_for_true_stories(self):
        words = _words("The crew landed on Runway two thirteen minutes later with ninety passengers aboard.")
        idx = list(range(len(words)))
        got = [(v, u) for _, v, u in explainer._counter_at(words, idx)]
        self.assertEqual(got, [(90, "passengers")])  # "two thirteen minutes" is ambiguous: no counter
        story = {"title": "x", "true_story": True, "fact_ledger": ["Passengers: 90"],
                 "scenes": [{"narration": "The engines were quiet when the plane finally stopped on the wet runway."},
                            {"narration": "It carried ninety passengers and twelve dogs that night."}]}
        n = self._narr(story)
        eff = explainer.plan_effects(story, n, self._segs(story, n))
        self.assertEqual([e["fields"]["value"] for e in eff if e["kind"] == "counter"], [90])

    def test_stamps_only_from_the_narration(self):
        story = {"title": "x", "scenes": [{"narration": "The boat came back to the harbour with its engine running."},
                                          {"narration": "The case was never solved and the files were sealed."},
                                          {"narration": "Nobody went missing that winter, if you believe them."}]}
        n = self._narr(story)
        eff = explainer.plan_effects(story, n, self._segs(story, n))
        stamps = [e["fields"]["text"] for e in eff if e["kind"] == "stamp"]
        self.assertIn("UNSOLVED", stamps)
        self.assertNotIn("CASE CLOSED", stamps)  # "never solved" is not a solved case



class Hollywood(unittest.TestCase):
    """The context library: sentence by sentence, data-driven (data/hollywood/library.json + assets/geo)."""

    def _narr(self, scenes):
        words, t = [], 0.0
        for i, sc in enumerate(scenes):
            for w in sc.split():
                words.append({"word": w, "start": round(t, 3), "end": round(t + 0.3, 3), "scene": i})
                t += 0.42
            t += 0.4
        return {"words": words, "duration": t}

    def _segs(self, n, k):
        per = n["duration"] / k
        return [{"start": i * per, "end": (i + 1) * per, "scene": i, "transition": "cut",
                 "shot": {"type": "image", "file": f"/x/scene_{i:02d}a.png", "scene": i}} for i in range(k)]

    def test_places_go_only_as_deep_as_the_narrator(self):
        import hollywood
        scenes = ["Nobody in the quiet harbour expected the call that came that night.",
                  "The ship had left Ireland two days before.",
                  "Weeks later the letters reached Fort Lauderdale, Florida, by mail."]
        story = {"title": "x", "scenes": [{"narration": s} for s in scenes]}
        places = hollywood.merge_places(hollywood.find_places(story, self._narr(scenes)))
        got = [(p["level"], p["iso2"]) for p in places]
        self.assertEqual(got[0], ("country", "IE"))          # a country: pin + flag, no deeper
        self.assertEqual(got[1], ("city_in_region", "US"))    # city + its state: outline + pin at the city
        f = hollywood.place_fields(places[1])
        self.assertTrue(f["region_rings"])
        self.assertEqual(f["region_name"], "Florida")
        self.assertNotIn("region_rings", hollywood.place_fields(places[0]))

    def test_a_character_name_or_common_word_is_not_a_place(self):
        import hollywood
        scenes = ["Jordan opened the door and Victoria screamed.", "They ran into the woods."]
        story = {"title": "x", "characters": [{"name": "Jordan Hale"}], "scenes": [{"narration": s} for s in scenes]}
        self.assertEqual(hollywood.find_places(story, self._narr(scenes)), [])

    def test_crossing_dark_signal_and_stamp_come_from_the_library(self):
        scenes = ["Nobody expected the radio to crackle like that over the water that afternoon.",
                  "Five Navy planes flew east over the Atlantic toward the islands.",
                  "Twenty minutes later the radio went silent over the open water.",
                  "By the time it was getting dark, the lead pilot's compass had failed.",
                  "The five planes vanished without a trace that evening."]
        story = {"title": "Flight", "scenes": [{"narration": s} for s in scenes]}
        n = self._narr(scenes)
        kinds = {e["kind"]: e for e in explainer.plan_effects(story, n, self._segs(n, 5))}
        self.assertEqual(kinds["ocean_crossing"]["fields"]["label"], "THE ATLANTIC")
        self.assertIn("signal_lost", kinds)
        self.assertIn("night_mode", kinds)
        self.assertEqual(kinds["stamp"]["fields"]["text"], "VANISHED")  # the narration's own word

    def test_counters_show_what_they_count(self):
        self.assertEqual(explainer.count_kind("passengers"), "people")
        self.assertEqual(explainer.count_kind("bullets"), "bullets")
        self.assertEqual(explainer.count_kind("shots"), "shots")
        self.assertEqual(explainer.count_kind("miles"), "plain")
        words = _words("Flight two forty-three left Hilo carrying ninety passengers and five crew members.")
        got = [(v, u) for _, v, u in explainer._counter_at(words, list(range(len(words))))]
        self.assertIn((90, "passengers"), got)
        self.assertNotIn(2, [v for v, _ in got])  # "Flight two forty-three" is not a count

    def test_the_old_count_card_is_gone(self):
        story = {"title": "x", "true_story": True, "fact_ledger": ["Flight 243"],
                 "scenes": [{"narration": "Flight two forty-three left Hilo carrying ninety passengers."}]}
        n = self._narr([story["scenes"][0]["narration"]])
        with mock.patch.object(explainer, "_plan_call", return_value=None):
            g = explainer.plan_graphics(story, n)
        self.assertFalse([x for gs in g for x in gs if (x.get("fields") or {}).get("kicker") == "THE COUNT"])

    def test_shot_twice_is_a_profile_with_two_hits(self):
        import hollywood
        self.assertEqual(hollywood.hits_of("twice"), 2)
        self.assertEqual(hollywood.hits_of("three times"), 3)
        scenes = ["Nobody heard a thing on that street until the very last moment.",
                  "The guard was shot twice before he reached the door."]
        story = {"title": "x", "scenes": [{"narration": s} for s in scenes]}
        n = self._narr(scenes)
        eff = [e for e in explainer.plan_effects(story, n, self._segs(n, 2)) if e["kind"] == "hit_profile"]
        self.assertEqual(eff[0]["fields"]["hits"], 2)
        self.assertEqual(len([x for x in eff[0]["sfx"] if x[1] == "gunshot"]), 2)  # one gunshot per hit

    def test_memory_learns_after_a_video(self):
        import hollywood
        import tempfile
        mem = Path(tempfile.mkdtemp()) / "memory.json"
        story = {"story_id": "s1", "scenes": [{"narration": "The lighthouse keeper locked the iron door."}],
                 "explainer_effects": [{"kind": "globe_pin", "source": "place", "scene": 1,
                                        "fields": {"label": "Ireland", "iso2": "IE", "level": "country"}}]}
        with mock.patch.object(hollywood, "MEMORY", mem):
            hollywood.learn(story, "2026-10-31_0000")
            hollywood.learn(story, "2026-10-31_0100")
        m = json.loads(mem.read_text())
        self.assertEqual(m["videos"], 2)
        self.assertEqual(m["entries"]["place"]["fired"], 2)
        self.assertEqual(m["places"]["Ireland"]["times"], 2)
        self.assertTrue(m["unmatched"])  # the scene no entry matched is queued for new library entries

    def test_crossing_runs_from_the_last_place_to_the_next(self):
        scenes = ["Nobody on board expected anything unusual from that short evening flight.",
                  "The plane left Shannon, Ireland, with a full cabin.",
                  "It flew west over the Atlantic toward Gander, Newfoundland, that night."]
        story = {"title": "x", "scenes": [{"narration": s} for s in scenes]}
        n = self._narr(scenes)
        c = next(e for e in explainer.plan_effects(story, n, self._segs(n, 3)) if e["kind"] == "ocean_crossing")
        self.assertLess(c["fields"]["from"][0], 0)           # Shannon, about -8.9
        self.assertGreater(c["fields"]["from"][0], -15)
        self.assertLess(c["fields"]["to"][0], -50)           # Gander, about -54.6

    def test_clue_objects_and_tracks_with_no_return(self):
        scenes = ["Nobody in the village could explain what happened on that winter night.",
                  "The newspaper said the family had simply moved away without a word.",
                  "But the key to the farmhouse was missing from its hook by the door.",
                  "Fresh footprints in the snow led into the barn, and none came back out."]
        story = {"title": "x", "scenes": [{"narration": s} for s in scenes]}
        n = self._narr(scenes)
        eff = explainer.plan_effects(story, n, self._segs(n, 4))
        clues = {e["fields"]["object"]: e["fields"] for e in eff if e["kind"] == "clue_object"}
        self.assertIn("newspaper", clues)
        self.assertTrue(clues["key"]["missing"])  # the sentence says it is missing: crossed out
        self.assertIn("footprint_route", [e["kind"] for e in eff])
        quiet = ["Nobody in the village could explain what happened on that winter night.",
                 "She left her footprints in the snow on the way to the barn."]
        story2 = {"title": "x", "scenes": [{"narration": s} for s in quiet]}
        n2 = self._narr(quiet)
        self.assertNotIn("footprint_route", [e["kind"] for e in explainer.plan_effects(story2, n2, self._segs(n2, 2))])
