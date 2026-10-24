"""Night Files writing system: bounded multi-model writing, objective checks, advisory critics (owner, Oct 24).

Offline: every model call is mocked. Fixtures: the Amelia Earhart script that exposed the problems (regression), an
original legend and an original fiction story.
  python -m unittest discover -s tests -p test_writing_room.py -v
"""
import copy
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import story  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
AMELIA = json.loads((FIX / "amelia_f8f477b53755.json").read_text())
LORE = json.loads((FIX / "writing" / "lore_lantern_man.json").read_text())
FICTION = json.loads((FIX / "writing" / "fiction_room14.json").read_text())
AMELIA_SOURCE = " ".join(AMELIA["fact_ledger"]) + " Amelia Earhart and Fred Noonan disappeared over the Pacific " \
    "Ocean on July 2, 1937 near Howland Island. Born 1897. Atlantic flight 1928. Solo 1932. Declared dead 1939."

GOOD_AMELIA = {
    "title": AMELIA["title"], "mode": "mystery", "true_story": True, "model": "nvidia:deepseek-ai/deepseek-v4.1-flash",
    "fact_ledger": AMELIA["fact_ledger"],
    "scenes": [
        {"narration": "Amelia Earhart and her navigator Fred Noonan disappeared over the Pacific on July second, "
                      "nineteen thirty-seven. This is a true story."},
        {"narration": "Their twin-engine Lockheed Electra was supposed to find a speck of land in the middle of "
                      "the ocean."},
        {"narration": "Earhart was already famous: in nineteen thirty-two she made the first nonstop solo "
                      "transatlantic flight by a woman."},
        {"narration": "On this last leg, the radio calls grew urgent, and then they stopped."},
        {"narration": "An extensive search found no plane, no wreckage, and no trace of either of them."},
        {"narration": "She was declared dead in nineteen thirty-nine, but the evidence never settled what happened."},
        {"narration": "One theory says they ran out of fuel and sank. Others believe they landed somewhere and "
                      "waited for a rescue that never came."},
        {"narration": "The ocean kept the answer. Which explanation fits the last radio calls best?"}]}


def _with(narr: list[str], base: dict) -> dict:
    d = copy.deepcopy(base)
    d["scenes"] = [{"narration": t} for t in narr]
    return d


class ObjectiveChecks(unittest.TestCase):
    def test_amelia_regression_problems_are_measured(self):
        adapted = AMELIA  # the narration that was rendered on Oct 23 (critic had scored it 90/100)
        codes = {c["code"] for c in story.writing_checks(adapted, "true")}
        self.assertIn("late_event", codes)  # the disappearance first appears ~2/3 in
        self.assertIn("setup_first", codes)  # "Born in eighteen ninety-seven" before the disappearance
        self.assertIn("unnatural_voice", codes)  # "you watch", "you follow", "you witness", "you listen as"
        voices = [c["detail"] for c in story.writing_checks(adapted, "true") if c["code"] == "unnatural_voice"]
        self.assertGreaterEqual(len(voices), 4)
        before = _with(AMELIA["explainer_before"], AMELIA)  # the classic draft: biography first too
        self.assertIn("late_event", {c["code"] for c in story.writing_checks(before, "true")})

    def test_a_good_script_passes_clean(self):
        checks = story.writing_checks(GOOD_AMELIA, "true", AMELIA_SOURCE)
        self.assertEqual([c for c in checks if c["severity"] != "advisory"], [], checks)
        self.assertGreater(story.check_score(checks), story.check_score(story.writing_checks(AMELIA, "true")))

    def test_wrong_title_story_is_serious(self):
        bio = _with(["She was born in a small town and loved climbing trees.",
                     "She later worked as a nurse aide during the war.",
                     "Then she became a pilot and won an award."] * 3, AMELIA)
        bio["title"] = "The Mysterious Disappearance Of Amelia Earhart"
        bio["case"] = ""
        sev = {c["code"]: c["severity"] for c in story.writing_checks(bio, "true")}
        self.assertEqual(sev.get("off_title"), "serious")

    def test_unsupported_historical_fact_detected(self):
        bad = copy.deepcopy(GOOD_AMELIA)
        bad["scenes"][5]["narration"] = "She was declared dead in nineteen thirty-six after a search of four " \
                                        "hundred thousand square miles."
        found = [c for c in story.writing_checks(bad, "true", AMELIA_SOURCE) if c["code"] == "unsupported_fact"]
        self.assertTrue(found)
        self.assertIn("1,936", found[0]["detail"])

    def test_fiction_versus_fact(self):
        fake = copy.deepcopy(FICTION)
        fake["scenes"][0]["narration"] += " This is a true story."
        self.assertEqual({c["code"]: c["severity"] for c in story.writing_checks(fake, "fiction")}.get(
            "fiction_as_fact"), "serious")
        self.assertNotIn("fiction_as_fact", {c["code"] for c in story.writing_checks(GOOD_AMELIA, "true")})
        for fixture, kind in ((LORE, "lore"), (FICTION, "fiction")):  # original genre examples pass cleanly
            self.assertEqual([c for c in story.writing_checks(fixture, kind) if c["severity"] == "serious"], [])
        self.assertEqual(story.writing_kind({"mode": "coldcase"}), "fiction")
        self.assertEqual(story.writing_kind({"mode": "lore"}), "lore")
        self.assertEqual(story.writing_kind({"mode": "case"}), "true")


class Providers(unittest.TestCase):
    def test_gemini_unavailable_fallback_writer_succeeds(self):
        calls = []

        def call(model, prompt, api_key, temperature=1.0, as_json=True, schema=None):
            calls.append(model)
            if model.startswith("gemini"):
                raise story.DailyLimit(f"{model}: daily quota used up")
            return copy.deepcopy(GOOD_AMELIA)

        with mock.patch.object(story, "model_chain", return_value=["gemini-3.8-flash", "gemini-3.5-flash-lite",
                                                                   "groq:openai/gpt-oss-120b"]), \
                mock.patch.object(story, "_call_model", side_effect=call):
            out = story._run_models("write", "k", 0.6)
        self.assertEqual(out["model"], "groq:openai/gpt-oss-120b")
        self.assertEqual(calls, ["gemini-3.8-flash", "gemini-3.5-flash-lite", "groq:openai/gpt-oss-120b"])

    def test_deepseek_challenger_unavailable_keeps_primary(self):
        draft = copy.deepcopy(AMELIA)
        draft["model"] = "gemini-3.8-flash"
        with mock.patch.dict(os.environ, {"NVIDIA_API_KEY": ""}), \
                mock.patch.object(story, "_call_model") as call:
            out = story.challenge_draft(draft, "prompt", "k", "true")
        call.assert_not_called()
        self.assertEqual(out["model"], "gemini-3.8-flash")
        self.assertIn("unavailable", out["writing"]["challenger"])
        with mock.patch.dict(os.environ, {"NVIDIA_API_KEY": "x"}), \
                mock.patch.object(story, "_call_model", side_effect=RuntimeError("HTTP 503")):
            out = story.challenge_draft(copy.deepcopy(draft), "prompt", "k", "true")
        self.assertEqual(out["model"], "gemini-3.8-flash")
        self.assertIn("failed", out["writing"]["challenger"])

    def test_challenger_skipped_when_first_draft_is_clean(self):
        clean = copy.deepcopy(GOOD_AMELIA)
        clean["model"] = "gemini-3.8-flash"
        with mock.patch.dict(os.environ, {"NVIDIA_API_KEY": "x"}), mock.patch.object(story, "_call_model") as call:
            out = story.challenge_draft(clean, "prompt", "k", "true", AMELIA_SOURCE)
        call.assert_not_called()  # no extra API call when nothing measurable can improve
        self.assertIn("skipped", out["writing"]["challenger"])

    def test_independent_critic_unavailable_objective_checks_decide(self):
        weak = copy.deepcopy(AMELIA)
        weak["model"] = "gemini-3.8-flash"

        def call(model, prompt, api_key, temperature=1.0, as_json=True, schema=None):
            if model.startswith("nvidia:"):
                return copy.deepcopy(GOOD_AMELIA)
            raise RuntimeError("HTTP 503 judge down")

        with mock.patch.dict(os.environ, {"NVIDIA_API_KEY": "x", "GROQ_API_KEY": "x"}), \
                mock.patch.object(story, "_call_model", side_effect=call), \
                mock.patch.object(story, "model_chain", return_value=["gemini-3.8-flash", "groq:openai/gpt-oss-120b"]):
            out = story.challenge_draft(weak, "prompt", "k", "true")
        self.assertEqual(out["model"], "nvidia:deepseek-ai/deepseek-v4.1-flash")
        self.assertTrue(out["writing"]["judge"].startswith("objective checks"))

    def test_independent_judge_never_an_author_or_its_family(self):
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "x", "OPENROUTER_API_KEY": "x", "NVIDIA_API_KEY": "x"}), \
                mock.patch.object(story, "model_chain", return_value=[
                    "gemini-3.8-flash", "gemini-3.5-flash-lite", "groq:openai/gpt-oss-120b",
                    "nvidia:deepseek-ai/deepseek-v4.1-flash"]):
            judges = story.judge_models({"gemini-3.8-flash", "nvidia:deepseek-ai/deepseek-v4.1-flash"})
        self.assertEqual(judges[0], "groq:openai/gpt-oss-120b")
        self.assertFalse(any("gemini" in j or "deepseek" in j for j in judges))


class Comparison(unittest.TestCase):
    def test_competing_drafts_judged_with_evidence(self):
        a, b = copy.deepcopy(AMELIA), copy.deepcopy(GOOD_AMELIA)
        a["model"] = "gemini-3.8-flash"
        verdict = {"winner": "B", "reason": "B opens on the disappearance", "evidence": ["A: 'you watch as Amelia'"],
                   "scores": {"A": {"title_alignment": 3}, "B": {"title_alignment": 9}}}
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "x"}), \
                mock.patch.object(story, "_call_model", return_value=verdict) as call, \
                mock.patch.object(story, "model_chain", return_value=["groq:openai/gpt-oss-120b"]):
            out = story.compare_drafts(a, b, "facts", "k", "true")
        self.assertEqual((out["winner"], out["judge"]), ("B", "groq:openai/gpt-oss-120b"))
        self.assertTrue(out["evidence"])
        prompt = call.call_args[0][1]
        self.assertIn("unnatural_voice", prompt)  # the judge sees the measured problems

    def test_serious_problem_loses_without_asking_a_judge(self):
        bad = copy.deepcopy(GOOD_AMELIA)
        bad["scenes"][5]["narration"] = "She was declared dead in nineteen thirty-six."
        with mock.patch.object(story, "_call_model") as call:
            out = story.compare_drafts(bad, copy.deepcopy(GOOD_AMELIA), "facts", "k", "true", AMELIA_SOURCE)
        call.assert_not_called()
        self.assertEqual(out["winner"], "B")

    def test_fiction_challenger_competes_at_script_level(self):
        script = " ".join(sc["narration"] for sc in FICTION["scenes"])
        draft = {"title": "", "script": "You watch the motel. " + script, "script_model": "groq:openai/gpt-oss-120b",
                 "model": "groq:openai/gpt-oss-120b"}
        with mock.patch.dict(os.environ, {"NVIDIA_API_KEY": "x", "OPENROUTER_API_KEY": ""}), \
                mock.patch.object(story, "_call_model", side_effect=[script]), \
                mock.patch.object(story, "model_chain", return_value=["groq:openai/gpt-oss-120b"]):
            out = story.challenge_draft(draft, "write", "k", "fiction")
        self.assertEqual(out["script"], script)  # no judge available: the measured cleaner script wins
        self.assertEqual(out["writing"]["llm_calls"], 1)


class BoundedQuality(unittest.TestCase):
    def test_low_critic_score_never_discards_and_revises_once(self):
        s = copy.deepcopy(AMELIA)
        low = {"hook": 2, "clarity": 3, "pacing": 3, "name_early": 2, "payoff": 2, "integrity": 5,
               "what_happened": "a biography", "reasons": ["the disappearance comes too late"]}
        with mock.patch.object(story, "_json_call", return_value=low), \
                mock.patch.object(story, "_run_models", return_value=copy.deepcopy(GOOD_AMELIA)) as rewrite:
            out = story.critic_pass(s, "k", "true", "rules", AMELIA_SOURCE)
            out2 = story.critic_pass(out, "k", "true", "rules", AMELIA_SOURCE)  # again: no second revision
        self.assertEqual(rewrite.call_count, 1)
        self.assertEqual(out["critic_score"], 17)
        self.assertEqual(out2["writing"]["revisions"], 1)
        self.assertEqual(out["scenes"], GOOD_AMELIA["scenes"])

    def test_revision_that_measures_worse_is_dropped(self):
        s = copy.deepcopy(GOOD_AMELIA)
        s["scenes"][3]["narration"] = "You watch as the radio calls grew urgent, and then they stopped."
        with mock.patch.object(story, "_run_models", return_value=copy.deepcopy(AMELIA)):
            out = story.targeted_revision(s, "k", "true", "rules", source=AMELIA_SOURCE)
        self.assertEqual(out["scenes"], s["scenes"])
        self.assertIn("revision_rejected", out["writing"])

    def test_critic_unavailable_story_continues(self):
        with mock.patch.object(story, "_json_call", side_effect=RuntimeError("offline")), \
                mock.patch.object(story, "_run_models") as rewrite:
            out = story.critic_pass(copy.deepcopy(LORE), "k", "legend", "rules")
        rewrite.assert_not_called()  # nothing measurable to fix: no extra call
        self.assertFalse(out["writing"]["critic"]["available"])

    def test_final_gate_editor_unavailable_safe_script_continues(self):
        item = copy.deepcopy(GOOD_AMELIA)
        item["_fact_source"] = AMELIA_SOURCE
        with mock.patch.object(story, "_json_call", side_effect=RuntimeError("offline")):
            out = story.final_script_gate(item, "k")
        self.assertIsNone(out["final_script_approval"]["approved"])
        self.assertFalse(out["final_script_approval"]["blocked"])

    def test_final_gate_low_editor_rating_is_advisory(self):
        reply = {"approved": False, "reasons": ["I'd prefer more suspense"], "title_alignment": 4,
                 "narrative_logic": 4, "payoff": 4, "fact_integrity": 8, "natural_voice": 5}
        with mock.patch.object(story, "_json_call", return_value=reply):
            out = story.final_script_gate(copy.deepcopy(FICTION), "k")
        self.assertEqual(out["final_script_approval"]["ratings"]["title_alignment"], 4)

    def test_final_gate_blocks_demonstrable_problems_only(self):
        bad = copy.deepcopy(GOOD_AMELIA)
        bad["_fact_source"] = AMELIA_SOURCE
        bad["scenes"][5]["narration"] = "She was declared dead in nineteen thirty-six."
        with mock.patch.object(story, "_json_call", return_value={"approved": True, "title_alignment": 10}):
            with self.assertRaises(story.StoryDiscarded) as e:
                story.final_script_gate(bad, "k")
        self.assertIn("unsupported_fact", str(e.exception))

    def test_premise_check_never_discards(self):
        vague = {"premises": [{"premise": "Strange things happen in a house.", "question": "why?",
                               "visual": "a dark old house", "clarity": 3}]}
        with mock.patch.object(story, "_json_call", return_value=vague):
            p = story.pick_premise([], "k", "discovery", "haunted house", None)
        self.assertEqual(p["premise"], "Strange things happen in a house.")

    def test_no_infinite_rewrite_loop_in_fiction(self):
        script = " ".join(sc["narration"] for sc in FICTION["scenes"])
        with mock.patch.object(story, "_run_text", return_value=(script, "gemini-3.8-flash")) as write, \
                mock.patch.object(story, "score_script", return_value=(40, {"what_happened": "x", "fixes": "y"})), \
                mock.patch.object(story, "pick_shape", return_value="discovery"), \
                mock.patch.object(story, "pick_premise", return_value={}), \
                mock.patch.object(story, "pick_subgenre", return_value="motel"), \
                mock.patch.object(story, "plan_scenes", side_effect=lambda sc, k, sfx: copy.deepcopy(FICTION)), \
                mock.patch.dict(os.environ, {"NVIDIA_API_KEY": ""}):
            out = story._creator_story([], "k", "", None)
        self.assertEqual(write.call_count, 2)  # one draft + ONE rewrite, then the story is made (score advisory)
        self.assertEqual(out["score"], 40)
        self.assertEqual(out["writing"]["revisions"], 1)


class ExplainerRestyle(unittest.TestCase):
    def test_restyle_that_adds_stage_directions_is_reverted(self):
        import explainer
        base = copy.deepcopy(GOOD_AMELIA)
        worse = copy.deepcopy(GOOD_AMELIA)
        worse["scenes"][1]["narration"] = "You watch as their Lockheed Electra searched for a speck of land."
        worse["scenes"][3]["narration"] = "You follow the radio calls as they grow urgent, and then they stopped."
        with mock.patch.object(story, "_run_models", return_value=worse), \
                mock.patch.object(story, "fix_hook", side_effect=lambda s, *a, **k: s), \
                mock.patch.object(story, "fact_check", side_effect=lambda s, *a, **k: s), \
                mock.patch.object(story, "sfx_names", return_value=""):
            out = explainer.adapt(base)
        self.assertEqual(out["scenes"], GOOD_AMELIA["scenes"])
        self.assertTrue(out["explainer_adapted"])

    def test_restyle_rules_never_force_second_person(self):
        import explainer
        for kind in ("true", "lore", "fiction"):
            self.assertNotIn("You are the adult", explainer.WHO[kind])
        self.assertIn("third person", explainer.WHO["lore"])


class Compatibility(unittest.TestCase):
    def test_metadata_survives_checkpoint_json(self):
        s = copy.deepcopy(AMELIA)
        s["model"] = "gemini-3.8-flash"
        with mock.patch.dict(os.environ, {"NVIDIA_API_KEY": ""}):
            out = story.challenge_draft(s, "p", "k", "true")
        again = json.loads(json.dumps(out))
        self.assertEqual(again["writing"]["kind"], "true")
        self.assertEqual(again["writing"]["primary"], "gemini-3.8-flash")

    def test_every_story_path_uses_the_bounded_writer(self):
        src = (ROOT / "pipeline" / "story.py").read_text()
        self.assertGreaterEqual(src.count("challenge_draft(story, prompt"), 2)  # true + mystery/lore paths
        self.assertIn('challenge_draft(story, prompt + UPGRADE_LORE', src)  # inbox topic legends
        self.assertIn("challenge_draft(draft, prompt, api_key, kind)", src)  # fiction / cold case
        self.assertNotIn("raise StoryBelowBar", src)
        self.assertNotIn('raise StoryDiscarded(f"critic score', src)
        cfg = json.loads((ROOT / "config.json").read_text())
        self.assertEqual(cfg["writer_max_revisions"], 1)
        self.assertEqual(cfg["writer_judge_models"][0], "groq:openai/gpt-oss-120b")


class ChallengerFallback(unittest.TestCase):
    KEYS = {"NVIDIA_API_KEY": "x", "OPENROUTER_API_KEY": "x", "GROQ_API_KEY": "x", "MODELSCOPE_TOKEN": ""}

    def _weak(self):
        d = copy.deepcopy(AMELIA)
        d["model"] = "gemini-3.8-flash"
        return d

    def test_deepseek_timeout_falls_back_to_another_family(self):
        calls, limits = [], []

        def call(model, prompt, api_key, temperature=1.0, as_json=True, schema=None):
            calls.append(model)
            limits.append(story._timeout(180))
            if model.startswith("nvidia:"):
                raise TimeoutError("Read timed out. (read timeout=75)")
            if "INDEPENDENT" in prompt:
                return {"winner": "B", "reason": "subject first"}
            d = copy.deepcopy(GOOD_AMELIA)
            d["model"] = model
            return d

        with mock.patch.dict(os.environ, self.KEYS), mock.patch.object(story, "_call_model", side_effect=call):
            out = story.challenge_draft(self._weak(), "prompt", "k", "true", AMELIA_SOURCE)
        self.assertEqual(calls[:2], ["nvidia:deepseek-ai/deepseek-v4.1-flash", "openrouter:qwen/qwen3-32b"])
        self.assertEqual(out["writing"]["challenger"], "openrouter:qwen/qwen3-32b")
        self.assertIn("TimeoutError", out["writing"]["challenger_attempts"][0])
        self.assertEqual(limits[:2], [75.0, 75.0])  # every challenger request is capped
        self.assertEqual(story._REQUEST_LIMIT, [])  # the cap ends with the challenger

    def test_attempts_are_limited_and_first_draft_kept(self):
        calls = []

        def call(model, *a, **k):
            calls.append(model)
            raise story.Overloaded(f"{model} HTTP 503")

        with mock.patch.dict(os.environ, self.KEYS), mock.patch.object(story, "_call_model", side_effect=call):
            out = story.challenge_draft(self._weak(), "prompt", "k", "true")
        self.assertEqual(len(calls), story.CONFIG.get("writer_challenger_max_attempts", 2))
        self.assertEqual(out["model"], "gemini-3.8-flash")
        self.assertIn("failed", out["writing"]["challenger"])

    def test_time_budget_stops_further_attempts(self):
        calls = []
        clock = iter([0.0, 0.0, 200.0, 200.0, 200.0])

        def call(model, *a, **k):
            calls.append(model)
            raise TimeoutError("slow")

        with mock.patch.dict(os.environ, self.KEYS), mock.patch.object(story, "_call_model", side_effect=call), \
                mock.patch.object(story.time, "time", side_effect=lambda: next(clock, 200.0)):
            out = story.challenge_draft(self._weak(), "prompt", "k", "true")
        self.assertEqual(len(calls), 1)
        self.assertIn("time budget", " ".join(out["writing"]["challenger_attempts"]))

    def test_other_family_first_and_never_the_primary(self):
        with mock.patch.dict(os.environ, self.KEYS):
            self.assertEqual(story.challenger_models("groq:openai/gpt-oss-120b"),
                             ["nvidia:deepseek-ai/deepseek-v4.1-flash", "openrouter:qwen/qwen3-32b"])
            with mock.patch.dict(story.CONFIG, {"writer_challenger_model": "openrouter:openai/gpt-oss-120b"}):
                order = story.challenger_models("groq:openai/gpt-oss-120b")
            self.assertEqual(order[-1], "openrouter:openai/gpt-oss-120b")  # same family only as a last resort

    def test_rate_limit_does_not_wait_inside_the_cap(self):
        resp = mock.Mock(status_code=429, text="rate limit tokens per minute", headers={"retry-after": "60"})
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "x"}), \
                mock.patch.object(story.requests, "post", return_value=resp) as post, \
                mock.patch.object(story.time, "sleep") as sleep:
            with story.request_limit(30):
                with self.assertRaises(story.RateLimited):
                    story._call_groq("openai/gpt-oss-120b", "hi")
        sleep.assert_not_called()
        self.assertEqual(post.call_args.kwargs["timeout"], 30)


class Continuity(unittest.TestCase):
    def test_contradictions_are_found_and_quoted(self):
        for text in ("The creature slammed Mara against the wall and her spine snapped. Mara ran for the door.",
                     "The thing tore her throat open. She fled into the woods.",
                     "It broke Ana's legs. Ana climbed the ladder to the loft.",
                     "Tom passed out on the floor. Tom screamed for help."):
            found = story.continuity_findings(text)
            self.assertEqual(len(found), 1, text)
            self.assertEqual(found[0]["severity"], "revise")  # sent to the one targeted revision, never blocks
            self.assertIn("then '", found[0]["detail"])

    def test_no_false_alarm_when_the_story_explains_it(self):
        for text in ("He was knocked out cold. Hours later he woke and ran to the road.",
                     "They tied her to the chair. She broke free and ran.",
                     "She drowned in the lake. Her ghost walks the shore every winter.",
                     "The thing killed him. She ran.",
                     "She cut his throat. She ran from the barn.",
                     "Her husband died in the winter. She walked to the grave every night.",
                     "They were declared dead in 1939. One theory says they ran out of fuel and sank.",
                     "The traveler died that night. In other versions, he walked home at dawn."):
            self.assertEqual(story.continuity_findings(text), [], text)

    def test_fixtures_have_no_contradiction_and_check_is_in_writing_checks(self):
        for fixture in (AMELIA, GOOD_AMELIA, LORE, FICTION):
            self.assertNotIn("contradiction", {c["code"] for c in story.writing_checks(fixture)})
        bad = _with(["A lantern drifted over the marsh.", "The marsh thing broke Eli's legs.",
                     "Eli ran home before dawn."], LORE)
        codes = {c["code"]: c["severity"] for c in story.writing_checks(bad, "lore")}
        self.assertEqual(codes.get("contradiction"), "revise")


if __name__ == "__main__":
    unittest.main()
