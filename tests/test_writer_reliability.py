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


if __name__ == "__main__":
    unittest.main()
