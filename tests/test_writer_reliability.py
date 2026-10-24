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


if __name__ == "__main__":
    unittest.main()
