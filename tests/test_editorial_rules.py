"""Offline checks that Rule of Six priorities reach the active Night Files planning prompts.

Creative judgment remains a human/editorial review, NOT an automated numeric quality gate.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))


class EditorialPriorityContract(unittest.TestCase):
    def test_scene_planner_teaches_all_six_in_priority_order(self):
        prompt = (ROOT / "prompts" / "scene_plan.txt").read_text(encoding="utf-8")
        terms = ("Emotion (51%)", "Story (23%)", "Rhythm (10%)", "Eye trace (7%)",
                 "screen plane (5%)", "spatial continuity (4%)")
        offsets = [prompt.index(term) for term in terms]
        self.assertEqual(offsets, sorted(offsets))
        self.assertIn("NOT scores", prompt)
        self.assertIn("lower caption safe zone", prompt)

    def test_graphics_planner_respects_emotion_story_before_effects(self):
        import explainer
        prompt = explainer.GRAPHICS_PROMPT
        terms = ("EMOTION first", "STORY second", "RHYTHM", "EYE TRACE", "2D SCREEN PLANE", "3D SPACE")
        offsets = [prompt.index(term) for term in terms]
        self.assertEqual(offsets, sorted(offsets))
        self.assertIn("NOT a numeric grading formula", prompt)
        self.assertIn("only create a graphic", prompt.lower())
        self.assertIn("contiguous expression", prompt)

    def test_editorial_guide_preserves_sound_caption_and_fact_constraints(self):
        guide = (ROOT / "docs" / "WALTER_MURCH_RULE_OF_SIX.md").read_text(encoding="utf-8")
        for term in ("Always-on kinetic captions", "BGM and SFX", "Five composition techniques",
                     "factual integrity", "story", "eye trace", "NOT a deterministic grade"):
            self.assertIn(term.lower(), guide.lower())
        self.assertIn("No publishing", "No publishing" if "may not publish" in guide else "not found")


if __name__ == "__main__":
    unittest.main()
