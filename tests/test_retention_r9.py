"""Zero-network R9 contract tests, no real video or posting."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import story
import story_bible


class RetentionR9Tests(unittest.TestCase):
    def test_all_writers_receive_trackable_question_rule(self):
        prompt = story.shared_style("Write an original suspense story.")
        self.assertIn("Rule R9: Give the viewer a question they can track", prompt)
        for term in ("Central question", "Changed understanding", "Payoff",
                     "Never invent", "scoreboard", "source"):
            self.assertIn(term.lower(), prompt.lower())

    def test_scene_planner_requests_three_supported_fields_not_scoreboard(self):
        instructions = (ROOT / "prompts" / "scene_plan.txt").read_text()
        self.assertIn("RULE R9: THE QUESTION THE VIEWER CAN TRACK", instructions)
        for field in ("central_question", "understanding_shift", "ending_payoff",
                      "recurring_visual_motif"):
            self.assertIn(field, instructions)
            self.assertIn(field, story.SCHEMA["properties"])
        self.assertIn('return "" (empty)', instructions)
        self.assertIn("Do not introduce countdowns", instructions)

    def test_existing_bible_stores_unverified_narrative_plan_without_new_art(self):
        s = {"title": "The Last Signal", "premise": "A radio repeats one warning",
             "central_question": "Who is speaking from the empty station?",
             "understanding_shift": "The warning contains tomorrow's time",
             "ending_payoff": "The receiver is the sender",
             "recurring_visual_motif": "The unchanged radio dial",
             "scenes": [{"narration": "The radio repeats its warning",
                         "location": "Control room"}],
             "characters": [{"name": "Mara", "look": "grey coat"}],
             "locations": [{"name": "Control room", "look": "two windows"}]}
        bible = story_bible.build(s)
        contract = bible["retention_contract"]
        self.assertEqual(contract["central_question"], s["central_question"])
        self.assertEqual(contract["understanding_shift"], s["understanding_shift"])
        self.assertEqual(contract["ending_payoff"], s["ending_payoff"])
        self.assertEqual(contract["optional_visual_motif"], s["recurring_visual_motif"])
        self.assertIn("writer-planned", contract["review_status"])
        self.assertEqual(len(bible["timeline"]), 1)
        self.assertEqual(len(bible["characters"]), 1)

    def test_missing_motif_does_not_force_graphic_or_false_number(self):
        s = {"title": "An Unsolved Case", "scenes": [{"narration": "The case remains open"}]}
        bible = story_bible.build(s)
        self.assertEqual(bible["retention_contract"]["optional_visual_motif"], "")
        self.assertEqual(bible["retention_contract"]["ending_payoff"], "")


if __name__ == "__main__":
    unittest.main()
