"""Regression cases for semantic visual method planning, no API calls."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
from visual_treatment import select


class VisualTreatmentTests(unittest.TestCase):
    def test_footprints_direction_is_graphic_over_existing_hook(self):
        v = select("Footprints led into the farmhouse, but none led back out.", first_scene=True)
        self.assertEqual(v["method"], "image")
        self.assertEqual(v["graphics"][0]["template"], "footprint_route")

    def test_newspaper_and_keys_are_separate_graphics(self):
        v = select("An unfamiliar newspaper appeared, and the house keys vanished.")
        self.assertEqual(v["method"], "graphic_first")
        self.assertEqual([g["fields"]["object"] for g in v["graphics"]], ["newspaper", "key"])

    def test_grounded_location_tag(self):
        v = select("In March 1922, a Bavarian farmer heard footsteps.", places=["Bavarian"])
        self.assertEqual(v["method"], "graphic_first")
        self.assertEqual(v["graphics"][0]["fields"]["place"], "Bavarian")

    def test_no_invented_location(self):
        v = select("A farmer heard noises in the attic.", places=["Bavaria"])
        self.assertEqual(v["graphics"], [])

    def test_weapon(self):
        v = select("They used a mattock as the weapon.")
        self.assertEqual(v["graphics"][0]["fields"]["object"], "weapon")

    def test_no_unjustified_return_arrow(self):
        self.assertFalse(select("Footprints in the snow caught their attention.")["graphics"])

    def test_empty(self):
        self.assertEqual(select("")["method"], "image")


if __name__ == "__main__":
    unittest.main()
