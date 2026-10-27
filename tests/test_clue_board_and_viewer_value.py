"""Regression tests: numbered evidence stays visible across shots and is never fabricated."""
import sys
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import clue_board
import story


SCRIPT = (
    "Investigators pointed to three specific clues. "
    "First, the ink had oxidized into rag paper long before anyone opened the book. "
    "Second, the Weather Bureau confirmed no barometric drop existed on those dates. "
    "Third, the handwriting matched no clerk who worked the harbor office. "
    "The story went on to the next case."
)


def narration(text: str, step: float = 0.33) -> dict:
    words = []
    for i, word in enumerate(text.split()):
        words.append({"word": word, "start": i * step + 1.0, "end": (i + 0.8) * step + 1.0, "scene": 0})
    return {"duration": len(words) * step + 2, "words": words}


class ClueBoardTests(unittest.TestCase):
    def test_three_items_appear_in_order_with_exact_narration_words(self):
        p = clue_board.plan(narration(SCRIPT))
        self.assertIsNotNone(p)
        self.assertEqual(p["count"], 3)
        self.assertEqual(p["noun"], "CLUES")
        self.assertEqual([x["label"] for x in p["cues"]],
                         ["INK HAD OXIDIZED INTO RAG PAPER", "NO BAROMETRIC DROP EXISTED ON THOSE DATES",
                          "HANDWRITING MATCHED NO CLERK"])
        self.assertLess(p["start"], p["cues"][0]["at"])
        self.assertLess(p["cues"][0]["at"], p["cues"][1]["at"])
        self.assertLess(p["cues"][1]["at"], p["cues"][2]["at"])
        self.assertGreater(p["end"], p["cues"][2]["at"])

    def test_no_overlay_without_full_explicit_enumeration(self):
        for text in (
            "There were three clues, but the rest of the archive was missing.",
            "First the ink faded, second came a knock, third was a scream.",
            "A ranger followed four tracks into the snow.",
            "The first ship sank, and the second ship never returned.",
            "Three witnesses gave completely different statements.",
        ):
            with self.subTest(text=text):
                self.assertIsNone(clue_board.plan(narration(text)))

    def test_staged_reveals_preserve_background_and_dont_show_future_labels(self):
        p = clue_board.plan(narration(SCRIPT))
        accent = (240, 23, 103)
        frame = Image.new("RGBA", (1080, 1920), (18, 32, 52, 255))
        before = clue_board.apply(frame.copy(), p, p["start"] - 0.01, accent)
        self.assertEqual(before.getpixel((400, 410)), frame.getpixel((400, 410)))
        midway = p["cues"][0]["at"] + 0.4
        after_one = clue_board.apply(frame.copy(), p, midway, accent)
        after_two = clue_board.apply(frame.copy(), p, p["cues"][1]["at"] + 0.4, accent)
        after_three = clue_board.apply(frame.copy(), p, p["cues"][2]["at"] + 0.4, accent)
        self.assertNotEqual(after_one.tobytes(), after_two.tobytes())
        self.assertNotEqual(after_two.tobytes(), after_three.tobytes())
        self.assertEqual(after_one.getpixel((30, 1100)), frame.getpixel((30, 1100)))
        self.assertEqual(clue_board.apply(frame.copy(), p, p["end"] + 0.1, accent).tobytes(),
                         frame.tobytes())
        states = [clue_board._state_image(tuple(x["label"] for x in p["cues"]), p["noun"], accent, n)
                  for n in range(4)]
        self.assertEqual(len(set(x.tobytes() for x in states)), 4)

    def test_nonbreaking_explainer_integration(self):
        from pathlib import Path
        source = (ROOT / "pipeline" / "explainer.py").read_text()
        self.assertIn("self.clue_board_plan = clue_board.plan(narration)", source)
        self.assertIn("clue_board.apply(frame, self.clue_board_plan, t, self.acc)", source)
        self.assertIn("CONFIG.get(\"explainer_clue_board\", True)", source)
        # This is an overlay. It must never touch the actual shot timeline or SFX/queue.
        self.assertNotIn("clue_board", (ROOT / "pipeline" / "publish.py").read_text())

    def test_all_provider_writers_receive_new_value_guidance(self):
        prompt = story.shared_style("Write a story.")
        self.assertIn("what does somebody get from this minute", prompt.lower())
        self.assertIn("No compulsory life lesson", prompt)
        self.assertIn("TASK:\nWrite a story.", prompt)


if __name__ == "__main__":
    unittest.main()
