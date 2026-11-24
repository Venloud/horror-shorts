"""No-network regression tests for bounded writer-challenger failover."""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import story  # noqa: E402
from providers import nvidia  # noqa: E402


class ChallengerReliability(unittest.TestCase):
    def setUp(self):
        self.draft = {"title": "The Unwanted Answer", "script": " ".join(["A shadow moves behind the closed door."] * 24),
                      "model": "gemini-3.8-flash", "script_model": "gemini-3.8-flash"}

    def test_deepseek_timeout_uses_independent_fallback(self):
        with mock.patch.dict(os.environ, {"NVIDIA_API_KEY": "test", "OPENROUTER_API_KEY": "test"}), \
             mock.patch.dict(story.CONFIG, {"writer_challenge_enabled": True,
                                            "writer_challenge_policy": "always",
                                            "writer_challenger_timeout_seconds": 25,
                                            "writer_challenger_model": "nvidia:deepseek-ai/deepseek-v4.1-flash",
                                            "writer_challenger_fallbacks": ["openrouter:qwen/qwen3-32b"]}), \
             mock.patch.object(story, "_call_model", side_effect=[TimeoutError("DeepSeek stalled"),
                 " ".join(["There is no one behind the locked door."] * 24)]) as call, \
             mock.patch.object(story, "compare_drafts", return_value={
                "winner": "B", "judge": "objective checks (no independent critic)",
                "reason": "cleaner", "objective": {"A": 75, "B": 90}}):
            out = story.challenge_draft(self.draft, "write fiction", "dummy", "fiction")
        self.assertEqual(out["model"], "openrouter:qwen/qwen3-32b")
        self.assertEqual(call.call_count, 2)
        self.assertEqual(call.call_args_list[0].kwargs["timeout_seconds"], 25)
        self.assertNotIn("timeout_seconds", call.call_args_list[1].kwargs)
        self.assertEqual(out["writing"]["llm_calls"], 2)

    def test_same_family_cannot_challenge(self):
        with mock.patch.dict(os.environ, {"NVIDIA_API_KEY": "test", "OPENROUTER_API_KEY": "test"}), \
             mock.patch.dict(story.CONFIG, {"writer_challenge_enabled": True,
                                            "writer_challenge_policy": "always",
                                            "writer_challenger_model": "nvidia:deepseek-ai/deepseek-v4.1-flash",
                                            "writer_challenger_fallbacks": ["openrouter:deepseek/deepseek-chat"]}), \
             mock.patch.object(story, "_call_model") as call:
            self.draft["model"] = "nvidia:deepseek-ai/deepseek-v4.1-flash"
            out = story.challenge_draft(self.draft, "prompt", "key", "fiction")
        call.assert_not_called()
        self.assertIn("unavailable", out["writing"]["challenger"])

    def test_nvidia_uses_short_timeout_when_requested(self):
        response = mock.Mock(status_code=200)
        response.json.return_value = {"choices": [{"message": {"content": "ready"}}]}
        with mock.patch.dict(os.environ, {"NVIDIA_API_KEY": "test"}), \
             mock.patch.object(nvidia.requests, "post", return_value=response) as post:
            self.assertEqual(nvidia.chat("demo", "hello", as_json=False, timeout_seconds=30), "ready")
        self.assertEqual(post.call_args.kwargs["timeout"], 30)


class StalledBackupsStaySkipped(unittest.TestCase):
    def test_overloaded_backup_is_not_retried_on_the_next_topic(self):
        # run 42904751972 (Nov 10): DeepSeek was "skipped for the rest of this run", then retried (2 x 180 s) on every
        # following topic, because only the Gemini models were filtered.
        backup = "nvidia:deepseek-ai/deepseek-v4.1-flash"
        with mock.patch.dict(os.environ, {"NVIDIA_API_KEY": "test"}, clear=False), \
             mock.patch.dict(story.CONFIG, {"nvidia_text_model": "deepseek-ai/deepseek-v4.1-flash"}), \
             mock.patch.object(story, "_OVERLOADED", set()):
            self.assertIn(backup, story.model_chain())
            story._OVERLOADED.add(backup)
            self.assertNotIn(backup, story.model_chain())


class LiteWriterIsTheLastResort(unittest.TestCase):
    def test_backups_are_tried_before_the_lite_gemini_for_stories(self):
        # Nov 24: strong Gemini overloaded -> lite wrote the Kappa story before NVIDIA/OpenRouter/ModelScope were tried.
        keys = {"NVIDIA_API_KEY": "t", "OPENROUTER_API_KEY": "t", "MODELSCOPE_API_KEY": "t", "GROQ_API_KEY": "t"}
        with mock.patch.dict(os.environ, keys, clear=False), \
             mock.patch.object(story, "_OVERLOADED", set()), \
             mock.patch.object(story, "gemini_model_out", return_value=False):
            chain = story.model_chain()
            light = story.model_chain(light=True)
        lite = [m for m in chain if "lite" in m]
        self.assertTrue(lite)
        self.assertEqual(chain[-len(lite):], lite)  # lite is last for story writing
        self.assertEqual(chain[0], story.CONFIG["llm_models"][0])  # strongest Gemini still first
        for backup in ("nvidia:", "openrouter:", "modelscope:"):
            self.assertLess(next(i for i, m in enumerate(chain) if m.startswith(backup)), chain.index(lite[0]))
        self.assertIn("lite", light[0])  # small JSON calls still save the strong model's quota


class ShotGenderMatchesNarration(unittest.TestCase):
    def test_she_scene_gets_a_female_subject_in_prompt_and_stock_query(self):
        # Hanako-san 2026-11-19: "she was a victim of bullying" over stock footage of a boy ("student sitting alone")
        import shot_rules
        st = {"scenes": [
            {"narration": "Different versions claim she was a victim of bullying.",
             "image_prompt": "a student sitting alone on school stairs", "image_query": "student sitting alone"},
            {"narration": "He opened the door and she screamed.", "image_prompt": "a person at a door"},
            {"narration": "She looked back.", "image_prompt": "a woman and a child on a porch"},
            {"narration": "He walked home.", "image_prompt": "An adult walking on a dark road"}]}
        shot_rules.match_gender(st)
        sc = st["scenes"]
        self.assertEqual(sc[0]["image_prompt"], "a female student sitting alone on school stairs")
        self.assertEqual(sc[0]["image_query"], "female student sitting alone")
        self.assertEqual(sc[1]["image_prompt"], "a person at a door")             # both pronouns: untouched
        self.assertEqual(sc[2]["image_prompt"], "a woman and a child on a porch")  # already gendered: untouched
        self.assertEqual(sc[3]["image_prompt"], "a man walking on a dark road")


class StrongWriterTimeout(unittest.TestCase):
    def test_strong_gemini_gets_time_to_write_lite_stays_fast(self):
        # Nov 2-19: gemini-3.8-flash hit the 60 s read timeout, was marked overloaded and skipped, so 28 of 30
        # videos were written by the last-resort lite model.
        ok = mock.Mock(status_code=200, text="")
        ok.json.return_value = {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}
        for model, want in (("gemini-3.8-flash", 180), ("gemini-3.5-flash-lite", 60)):
            with mock.patch.object(story.requests, "post", return_value=ok) as post,                  mock.patch.object(story, "_gemini_pace", lambda: None),                  mock.patch.object(story, "gemini_model_out", return_value=False):
                try:
                    story._call_gemini(model, "prompt", "key")
                except Exception:  # noqa: BLE001  (parsing the stub answer is not under test)
                    pass
                self.assertEqual(post.call_args.kwargs["timeout"], want, model)


class SpokenNumberFactCheck(unittest.TestCase):
    """Runs 44827959383 (Dover Demon) and the Nov 16 Hessdalen run parked true stories as 'unsupported_fact: 20 / 19':
    the checker read 'April twenty-first' as 20 and 'the nineteen thirties' as 19 and 30."""

    def test_ordinals_and_decades_read_as_their_value(self):
        import spoken_numbers as nums
        self.assertEqual(nums.values("On April twenty-first, nineteen seventy-seven"), {21, 1977})
        self.assertEqual(nums.values("since at least the nineteen thirties"), {1930})
        self.assertEqual(nums.values("his forty-second birthday"), {42})
        self.assertEqual(nums.values("the one hundredth victim"), {100})

    def test_spoken_date_matching_source_is_not_unsupported(self):
        story_ = {"mode": "mystery", "scenes": [
            {"narration": "On April twenty-first, nineteen seventy-seven, seventeen-year-old William Bartlett drove."},
            {"narration": "Lights have been reported since at least the nineteen thirties."}]}
        source = "The Dover Demon was sighted on April 21-22, 1977. Lights were reported since the 1930s; he was 17."
        found = story.writing_checks(story_, "true", source)
        self.assertFalse([f for f in found if f["code"] == "unsupported_fact"], found)


class StoryBank(unittest.TestCase):
    """Owner-approved 2026-11-24: stories written ahead by strong writers only (story_bank.yml)."""

    def setUp(self):
        import tempfile
        import checkpoint
        import story_bank
        self.sb, self.ck = story_bank, checkpoint
        self.tmp = Path(tempfile.mkdtemp())
        self.p = [mock.patch.object(story_bank, "BANK", self.tmp / "bank"),
                  mock.patch.object(checkpoint, "FAILED", self.tmp / "failed")]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()

    def bank(self, title, score, model="gemini-3.8-flash", age_days=0):
        from datetime import datetime, timedelta, timezone
        s = {"title": title, "mode": "lore", "critic_score": score, "model": model, "scenes": [],
             "banked_at": (datetime.now(timezone.utc) - timedelta(days=age_days)).isoformat(timespec="seconds")}
        s["story_id"] = self.ck.story_id(s)
        self.sb.BANK.mkdir(parents=True, exist_ok=True)
        (self.sb.BANK / f"{s['story_id']}.json").write_text(json.dumps(s), encoding="utf-8")
        return s

    def test_strong_only_chain_never_has_lite_and_may_be_empty(self):
        with mock.patch.dict(os.environ, {"NF_STRONG_WRITERS_ONLY": "1"}),              mock.patch.object(story, "_OVERLOADED", set()),              mock.patch.object(story, "gemini_model_out", return_value=False):
            self.assertFalse([m for m in story.model_chain() if "lite" in m])
            self.assertTrue(any("lite" in m for m in story.model_chain(light=True)))  # small calls unchanged
            with mock.patch.object(story, "_OVERLOADED", {m for m in story.CONFIG["llm_models"] if "lite" not in m}),                  mock.patch.dict(os.environ, {"NVIDIA_API_KEY": "", "OPENROUTER_API_KEY": "", "GROQ_API_KEY": "",
                                              "MODELSCOPE_API_KEY": "", "MODELSCOPE_TOKEN": "",
                                              "NVIDIA_NIM_API_KEY": ""}):
                self.assertEqual(story.model_chain(), [])  # no lite fallback: nothing is banked

    def test_take_picks_the_best_usable_story(self):
        used = self.bank("Used One", 99)
        self.bank("Lite One", 98, model="gemini-3.5-flash-lite")
        self.bank("Old One", 97, age_days=40)
        parked = self.bank("Parked One", 96)
        (self.ck.FAILED / parked["story_id"]).mkdir(parents=True)
        self.bank("Good But Lower", 70)
        best = self.bank("Best Usable", 90)
        history = [{"story_id": used["story_id"], "title": "Used One", "mode": "lore"}]
        with mock.patch("story._final_problem", return_value=""):
            got = self.sb.take(history, set())
        self.assertEqual(got["story_id"], best["story_id"])
        self.assertTrue(got["from_story_bank"])
        with mock.patch("story._final_problem", return_value=""):
            self.assertEqual(self.sb.take(history, {best["story_id"]})["title"], "Good But Lower")  # buffered: skip

    def test_fill_banks_one_strong_story_and_prunes_used_ones(self):
        used = self.bank("Used One", 80)
        written = {"title": "New Legend", "mode": "lore", "model": "nvidia:z-ai/glm-5.3-flash", "scenes": []}
        hist = [{"story_id": used["story_id"], "title": "Used One", "mode": "lore"}]
        with mock.patch("common.load_history", return_value=hist),              mock.patch("story.write_story", return_value=dict(written)) as ws,              mock.patch("explainer.style_for", return_value="classic"):
            self.assertEqual(self.sb.fill(), 0)
        files = [json.loads(f.read_text(encoding="utf-8")) for f in self.sb.BANK.glob("*.json")]
        self.assertEqual([f["title"] for f in files], ["New Legend"])  # used one pruned, new one banked
        self.assertTrue(files[0]["banked_at"])
        self.assertEqual(os.environ.get("NF_STRONG_WRITERS_ONLY"), "1")
        os.environ.pop("NF_STRONG_WRITERS_ONLY", None)
        self.assertEqual(ws.call_count, 1)

    def test_fill_does_not_bank_lite_or_write_when_full(self):
        with mock.patch("common.load_history", return_value=[]),              mock.patch("story.write_story", return_value={"title": "L", "mode": "lore",
                                                         "model": "gemini-3.5-flash-lite", "scenes": []}):
            self.sb.fill()
        os.environ.pop("NF_STRONG_WRITERS_ONLY", None)
        self.assertEqual(list(self.sb.BANK.glob("*.json")) if self.sb.BANK.exists() else [], [])
        for i in range(3):
            self.bank(f"Stock {i}", 80)
        with mock.patch("common.load_history", return_value=[]), mock.patch("story.write_story") as ws:
            self.sb.fill()
        os.environ.pop("NF_STRONG_WRITERS_ONLY", None)
        ws.assert_not_called()

    def test_fill_fits_a_long_script_to_the_cut_while_strong_writers_answer(self):
        import common
        common.apply_length({"mode": "lore"})
        long = {"title": "Long", "mode": "lore", "model": "openrouter:openai/gpt-oss-120b",
                "scenes": [{"narration": " ".join(["word"] * 34)} for _ in range(4)]}  # 136 words (MV Joyita)

        def resize(st, key, want):
            return {**st, "scenes": [{"narration": " ".join(["word"] * (want // 4))} for _ in st["scenes"]]}
        with mock.patch("common.load_history", return_value=[]),              mock.patch("story.write_story", return_value=long),              mock.patch("story.resize_story", side_effect=resize) as rs,              mock.patch("explainer.style_for", return_value="classic"):
            self.sb.fill()
        os.environ.pop("NF_STRONG_WRITERS_ONLY", None)
        banked = json.loads(next(self.sb.BANK.glob("*.json")).read_text(encoding="utf-8"))
        lo, hi = common.CONFIG["story_words"]
        self.assertTrue(lo <= sum(len(s["narration"].split()) for s in banked["scenes"]) <= hi)
        self.assertEqual(rs.call_args.args[2], round((lo + hi) / 2))

    def test_rejected_backup_key_is_skipped_for_the_run(self):
        calls = []

        def call(model):
            calls.append(model)
            if model.startswith("modelscope:"):
                raise RuntimeError("ModelScope chat HTTP 401: Authentication failed")
            return {"ok": model}
        with mock.patch.object(story, "model_chain", side_effect=lambda light=False: [
                m for m in ["modelscope:Qwen/Qwen3.5-27B", "openrouter:openai/gpt-oss-120b"]
                if m not in story._OVERLOADED]),              mock.patch.object(story, "_OVERLOADED", set()), mock.patch.object(story.time, "sleep"):
            self.assertEqual(story._with_models(call), {"ok": "openrouter:openai/gpt-oss-120b"})
            self.assertEqual(calls.count("modelscope:Qwen/Qwen3.5-27B"), 1)
            self.assertIn("modelscope:Qwen/Qwen3.5-27B", story._OVERLOADED)

    def test_daily_run_takes_from_the_bank_before_writing(self):
        src = (ROOT / "pipeline" / "main.py").read_text(encoding="utf-8")
        self.assertLess(src.index("select_approved_story(history, CONFIG)"), src.index("story_bank.take("))
        self.assertLess(src.index("story_bank.take("), src.index("story = write_story(history)"))
        wf = (ROOT / ".github" / "workflows" / "daily.yml").read_text(encoding="utf-8")
        self.assertIn("secrets.MODELSCOPE_API_KEY", wf)
        self.assertIn("OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}", wf)


if __name__ == "__main__":
    unittest.main()


class HookStyles(unittest.TestCase):
    """Owner experiment 2026-11-24: rotate the opener style, tag every video, never invent a fact."""

    def _story(self, mode="mystery"):
        return {"title": "Joyita", "mode": mode, "scenes": [
            {"narration": "Twenty-five people vanished from a ship that could not sink. Nobody saw them leave."},
            {"narration": "The Joyita sailed on October 3, 1955 and was found five weeks later."}]}

    def test_rotation_picks_least_used_and_skips_true_only_styles_on_fiction(self):
        import hook_style
        hist = [{"hook_style": "control"}, {"hook_style": "true_story"}]
        self.assertEqual(hook_style.pick(self._story(), hist), "did_you_know")
        fiction = hook_style.eligible(self._story("fiction"))
        self.assertNotIn("true_story", fiction)
        self.assertNotIn("date", fiction)
        self.assertIn("ending_first", fiction)

    def test_rewrite_is_applied_tagged_and_survives_a_resize(self):
        import hook_style
        s = self._story()
        out = {"scene1": "Did you know twenty-five people once vanished from a ship that could not sink? "
                         "Nobody saw them leave.", "hook_overlay": "25 people. Gone."}
        with mock.patch.object(story, "_json_call", return_value=out):
            s = hook_style.apply(s, [{"hook_style": "control"}, {"hook_style": "true_story"}])
        self.assertEqual(s["hook_style"], "did_you_know")
        self.assertTrue(s["scenes"][0]["narration"].startswith("Did you know"))
        s["scenes"][0]["narration"] = "Twenty-five people vanished. Nobody saw them leave."  # a resize rewrote it
        hook_style.keep(s)
        self.assertTrue(s["scenes"][0]["narration"].startswith("Did you know twenty-five"))
        self.assertTrue(s["scenes"][0]["narration"].endswith("Nobody saw them leave."))

    def test_invented_number_or_failure_keeps_the_original_as_control(self):
        import hook_style
        s = self._story()
        orig = s["scenes"][0]["narration"]
        bad = {"scene1": "On May 9, 1961 twenty-five people vanished from a ship. Nobody saw them leave."}
        with mock.patch.object(hook_style, "pick", return_value="date"), \
             mock.patch.object(story, "_json_call", return_value=bad):
            s = hook_style.apply(s, [])
        self.assertEqual((s["hook_style"], s["scenes"][0]["narration"]), ("control", orig))
        s2 = self._story()
        with mock.patch.object(hook_style, "pick", return_value="description"), \
             mock.patch.object(story, "_json_call", side_effect=story.ApiBusy("all busy")):
            s2 = hook_style.apply(s2, [])
        self.assertEqual(s2["hook_style"], "control")

    def test_owner_scripts_are_never_restyled_and_history_records_the_style(self):
        import hook_style
        s = {"mode": "inbox-script", "scenes": [{"narration": "Owner words."}]}
        self.assertEqual(hook_style.apply(s, [])["hook_style"], "owner")
        self.assertEqual(s["scenes"][0]["narration"], "Owner words.")
        main_src = (ROOT / "pipeline" / "main.py").read_text(encoding="utf-8")
        self.assertIn('"hook_style": story.get("hook_style")', main_src)


class SetBuilder(unittest.TestCase):
    """Owner request 2026-11-24: layered sets (no fixed count) + a focal point per shot, used by the image prompt."""

    def _story(self):
        return {"title": "Kappa", "mode": "lore", "setting": "rural Japan, Edo period",
                "characters": [{"name": "kappa", "look": "green river creature with a water dish on its head"}],
                "locations": [{"name": "river", "look": "a river"}],
                "scenes": [{"narration": "A horse was dragged into the river.", "image_prompt": "kappa pulls a horse into the river",
                            "image_prompt_2": "close-up of a cucumber offering"},
                           {"narration": "The village shrine kept the arm.", "image_prompt": "a mummified arm in a shrine box"}]}

    def _answer(self):
        return {"sets": [{"name": "Night river", "background": "pale misty mountains", "midground": "black river water",
                          "foreground": "tall reeds", "light": "cold moonlight", "detail": "a broken torii in the water",
                          "leading_line": "the curving riverbank"},
                         {"name": "Village shrine", "background": "dim wooden walls", "midground": "an altar",
                          "foreground": "paper lanterns", "light": "one candle", "detail": "rope with paper charms",
                          "leading_line": "the stone path"}],
                "shots": [{"id": "1a", "set": "Night river", "focal": "the horse's terrified eye"},
                          {"id": "1b", "set": "none", "focal": "the cucumber"},
                          {"id": "2a", "set": "Village shrine", "focal": "the mummified arm"}]}

    def test_sets_are_assigned_and_reach_the_image_prompt(self):
        import images
        import set_builder
        with mock.patch.object(story, "_json_call", return_value=self._answer()):
            s = set_builder.build(self._story())
        self.assertEqual(s["set_builder"], "2 sets")
        self.assertEqual(s["scenes"][0]["image_location"], "Night river")
        self.assertEqual(s["scenes"][0]["image_location_2"], "none")
        self.assertEqual(s["scenes"][1]["image_location"], "Village shrine")
        p = images.build_prompt(s, 0, s["scenes"][0]["image_prompt"], style="STYLE", letter="a")
        for bit in ("pale misty mountains", "tall reeds in the dark foreground", "the curving riverbank leading the eye",
                    "the eye drawn first to the horse's terrified eye", "rim-lit"):
            self.assertIn(bit, p)
        self.assertLess(p.index("kappa pulls"), p.index("rim-lit"))

    def test_cast_keeps_one_look_in_every_shot_that_shows_the_character(self):
        import images
        import set_builder
        s = {"title": "Joyita", "characters": [{"name": "Captain Miller", "look": "man in his 50s, grizzled beard"}],
             "scenes": [{"narration": "The captain vanished.", "image_prompt": "the captain stares at the dark sea",
                         "image_prompt_2": "a lone figure on the tilted deck"},
                        {"narration": "Investigators found the log.", "image_prompt": "men in suits read a logbook"}]}
        answer = {"sets": [{"name": "Deck", "background": "grey sea", "midground": "tilted deck"}],
                  "cast": [{"name": "Captain Miller", "look": "SHOULD NOT REPLACE", "aliases": ["the captain", "he"]},
                           {"name": "Investigators", "look": "two men in 1950s grey suits and fedoras",
                            "aliases": ["men in suits"]}],
                  "shots": [{"id": "1a", "set": "Deck", "cast": ["Captain Miller"]},
                            {"id": "1b", "set": "Deck", "cast": ["the captain"]},
                            {"id": "2a", "set": "none", "cast": ["Investigators", "nobody"]}]}
        with mock.patch.object(story, "_json_call", return_value=answer):
            s = set_builder.build(s)
        self.assertEqual(s["cast_builder"], "2 cast")
        miller = s["characters"][0]
        self.assertEqual(miller["look"], "man in his 50s, grizzled beard")  # the writer's locked look wins
        self.assertEqual(miller["aliases"], ["the captain"])                 # pronouns are never aliases
        self.assertEqual(s["scenes"][0]["image_cast_2"], ["Captain Miller"])
        for i, letter, shot in ((0, "a", "the captain stares"), (0, "b", "a lone figure")):
            p = images.build_prompt(s, i, s["scenes"][i][images.PROMPT_KEYS[letter]], style="S", letter=letter)
            self.assertIn("Captain Miller, man in his 50s, grizzled beard", p)
            self.assertLess(p.index(shot), p.index("grizzled"))
        p = images.build_prompt(s, 1, s["scenes"][1]["image_prompt"], style="S", letter="a")
        self.assertIn("two men in 1950s grey suits and fedoras", p)
        self.assertNotIn("grizzled", p)
        self.assertIn("grizzled", images.build_short_prompt(s, 0, s["scenes"][0]["image_prompt_2"], letter="b"))
        self.assertIn('"cast_builder": story.get("cast_builder")', (ROOT / "pipeline" / "main.py").read_text(encoding="utf-8"))

    def test_failure_or_disabled_leaves_the_story_unchanged(self):
        import images
        import set_builder
        s = self._story()
        before = json.dumps(s)
        with mock.patch.object(story, "_json_call", side_effect=story.ApiBusy("busy")):
            s = set_builder.build(s)
        self.assertEqual(s.pop("set_builder"), "off")
        self.assertEqual(json.dumps(s), before)
        s["set_builder"] = "off"
        self.assertNotIn("rim-lit", images.build_prompt(s, 0, s["scenes"][0]["image_prompt"], style="S", letter="a"))
        self.assertIn('"set_builder": story.get("set_builder")', (ROOT / "pipeline" / "main.py").read_text(encoding="utf-8"))


class LibraryReuse(unittest.TestCase):
    """Owner request 2026-11-24 (scene step 3): reuse matching scenery, never people, never a forced mismatch."""

    def test_fresh_mode_still_checks_the_library(self):
        src = (ROOT / "pipeline" / "explainer.py").read_text(encoding="utf-8")
        self.assertIn('if not fresh or (not checkbox and CONFIG.get("library_reuse_on_fresh", True)):', src)
        self.assertNotIn("FRESH_IMAGES", (ROOT / ".github" / "workflows" / "daily.yml").read_text(encoding="utf-8"))
        self.assertTrue(json.loads((ROOT / "config.json").read_text(encoding="utf-8"))["library_reuse_on_fresh"])

    def test_cast_shots_are_never_reused_and_reasons_are_logged(self):
        import library
        import numpy as np
        vec = np.ones(4, dtype="float32") / 2
        asset = {"id": "x", "style": "painted", "setting": "exterior", "era": "any", "times_used": 0,
                 "embedding": "e", "uses": []}
        s = {"mode": "lore", "scenes": [
            {"narration": "n", "image_prompt": "hook shot of the river"},
            {"narration": "n", "image_prompt": "a dark river at night", "image_prompt_2": "a lone figure on the bank",
             "image_cast_2": ["Ghost"]}]}
        calls, logs = [], []
        with mock.patch.object(library, "load_index", return_value={"assets": [asset], "seq": 50}), \
                mock.patch.object(library, "_setting", return_value=("exterior", "")), \
                mock.patch.object(library, "embed_text", return_value=vec), \
                mock.patch.object(library, "_unpack", return_value=vec * 0.6), \
                mock.patch.object(library, "_try_reuse", side_effect=lambda *a: calls.append(a[1:3]) or True), \
                mock.patch.object(library, "log", side_effect=logs.append):
            n = library._fill(s, ROOT / "cache" / "test_library_out")
        self.assertEqual(n, 1)
        self.assertEqual(calls, [(1, "a")])  # the hook and the cast shot are never library pictures
        self.assertIn("person 1", logs[-1])
