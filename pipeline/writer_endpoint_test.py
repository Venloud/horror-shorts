"""TEST-ONLY check of the writing room's extra endpoints (writer_endpoint_test.yml). Nothing is voiced, rendered,
buffered, posted or written to history / inbox / counter.

1. Ping: one tiny JSON call to the challenger (config writer_challenger_model, DeepSeek on NVIDIA) and to every
   configured independent judge (writer_judge_models, GPT-OSS 120B on Groq / OpenRouter).
2. Generation: one real story through story.write_story with writer_challenge_policy forced to "always", so the
   challenger draft and the comparison really run. If the comparison was settled by the objective checks (no judge
   call needed), each configured judge is also asked to compare the two real drafts with the production prompt.

  STORY_MODE=lore python writer_endpoint_test.py   (STORY_MODE skips the inbox)
Writes output/writer_endpoint_test/report.md + story.json. Exit 1 when the challenger or every judge failed.
"""
import json
import os
import sys
import time
import traceback

from common import CONFIG, ROOT, env, load_history, log

OUT = ROOT / "output" / "writer_endpoint_test"


def _ping(model: str) -> dict:
    import story
    t = time.time()
    try:
        v = story._call_model(model, 'Reply as JSON: {"ok": true, "word": "<one word for night>"}',
                              env("GEMINI_API_KEY", required=False) or "", temperature=0.1, as_json=True,
                              schema={"type": "OBJECT"})
        ok = isinstance(v, dict) and v.get("ok") is True
        return {"model": model, "ok": ok, "seconds": round(time.time() - t, 1), "answer": json.dumps(v)[:160]}
    except Exception as exc:  # noqa: BLE001
        return {"model": model, "ok": False, "seconds": round(time.time() - t, 1), "error": str(exc)[:300]}


def main() -> int:
    import story
    OUT.mkdir(parents=True, exist_ok=True)
    challenger = str(CONFIG.get("writer_challenger_model"))
    judges = [m for m in CONFIG.get("writer_judge_models", []) if isinstance(m, str)]
    report = ["# Writer endpoint test (nothing buffered / posted / saved to history)", "",
              f"Challenger: `{challenger}` (key present: {story._available(challenger)})",
              "Judges: " + ", ".join(f"`{j}` (key present: {story._available(j)})" for j in judges), "",
              "## 1. Direct pings"]
    pings = {m: _ping(m) for m in [challenger] + judges}
    for p in pings.values():
        report.append(f"- `{p['model']}`: {'OK' if p['ok'] else 'FAILED'} in {p['seconds']} s: "
                      f"{p.get('answer') or p.get('error')}")

    if challenger.startswith("nvidia:"):
        report += ["", "### NVIDIA catalogue check"]
        try:
            import requests
            from providers import nvidia
            r = requests.get("https://integrate.api.nvidia.com/v1/models",
                             headers={"Authorization": f"Bearer {nvidia.key()}"}, timeout=30)
            ids = [m.get("id", "") for m in (r.json().get("data") or [])] if r.status_code == 200 else []
            want = challenger[7:]
            report.append(f"- /v1/models HTTP {r.status_code}, {len(ids)} models; `{want}` listed: {want in ids}")
            report.append("- DeepSeek ids offered: " + (", ".join(f"`{i}`" for i in ids if "deepseek" in i.lower())
                                                       or "none"))
        except Exception as exc:  # noqa: BLE001
            report.append(f"- catalogue check failed: {str(exc)[:200]}")

    report += ["", "## 2. Real story generation (challenger forced on)"]
    CONFIG["writer_challenge_policy"] = "always"
    captured: list = []
    real_compare = story.compare_drafts

    def compare(a, b, context, api_key, kind, source=None):
        verdict = real_compare(a, b, context, api_key, kind, source)
        captured.append({"a": a, "b": b, "context": context, "kind": kind, "source": source, "verdict": verdict})
        return verdict
    story.compare_drafts = compare
    gen_ok, judged_live = False, set()
    try:
        made = story.write_story(load_history())
        w = made.get("writing") or {}
        (OUT / "story.json").write_text(json.dumps(made, indent=1, ensure_ascii=False, default=str))
        report += [f"- Story: '{made.get('title')}' (mode {made.get('mode')}, writer {made.get('writer')})",
                   f"- Primary: `{w.get('primary')}`", f"- Challenger: `{w.get('challenger')}`",
                   f"- Judge: `{w.get('judge')}`, selected draft {w.get('selected')}: {str(w.get('reason'))[:300]}",
                   f"- LLM calls in the writing room: {w.get('llm_calls')}"]
        gen_ok = bool(captured)
        for c in captured:
            j = str(c["verdict"].get("judge", ""))
            if j in judges:
                judged_live.add(j)
        if not captured:
            report.append(f"- No comparison ran (challenger: {w.get('challenger')})")
        narration = " ".join(s.get("narration", "") for s in made.get("scenes") or []) or made.get("script", "")
        report += ["", "### Selected narration", "", narration]
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        report.append(f"- Generation FAILED: {type(exc).__name__}: {str(exc)[:400]}")
    finally:
        story.compare_drafts = real_compare

    if not captured:  # the judge path still gets a real test: two short drafts, production prompt
        captured.append({"kind": "lore", "source": None, "context": "Legend of a lantern seen over a marsh.",
                         "a": {"title": "The Marsh Lantern", "scenes": [{"narration": "A lantern drifts over the "
                               "marsh where no one walks. Villagers say it leads travelers into the water."}]},
                         "b": {"title": "The Marsh Lantern", "scenes": [{"narration": "The marsh lantern burns "
                               "where no road runs. Follow it, the old people said, and the water keeps you."}]},
                         "verdict": {}})
        report.append("- (no comparison ran in generation: the judges get two short sample drafts below)")
    if captured:
        c = captured[-1]
        report += ["", "## 3. Each judge on the two real drafts (production judge prompt)"]
        ca, cb = story.writing_checks(c["a"], c["kind"], c["source"]), story.writing_checks(c["b"], c["kind"],
                                                                                           c["source"])
        for j in judges:
            t = time.time()
            try:
                v = story._call_model(j, story.JUDGE_PROMPT.format(
                    kind=c["kind"], genre_rule=story.GENRE_RULES[c["kind"]], checks_a=story._brief(ca),
                    checks_b=story._brief(cb), title=c["a"].get("title") or c["b"].get("title") or "",
                    context=c["context"][-9000:],
                    a=json.dumps(story._draft_view(c["a"]), ensure_ascii=False)[:12000],
                    b=json.dumps(story._draft_view(c["b"]), ensure_ascii=False)[:12000]),
                    "", temperature=0.1, as_json=True, schema={"type": "OBJECT"})
                ok = isinstance(v, dict) and v.get("winner") in ("A", "B")
                if ok:
                    judged_live.add(j)
                report.append(f"- `{j}`: {'valid verdict' if ok else 'INVALID verdict'} in "
                              f"{time.time() - t:.1f} s: winner {v.get('winner') if isinstance(v, dict) else '?'}; "
                              f"{str(v.get('reason', '') if isinstance(v, dict) else v)[:300]}")
            except Exception as exc:  # noqa: BLE001
                report.append(f"- `{j}`: FAILED in {time.time() - t:.1f} s: {str(exc)[:300]}")

    challenger_ok = pings[challenger]["ok"] and any(str(c["b"].get("model")) == challenger for c in captured)
    judge_ok = bool(judged_live)
    report += ["", "## Result",
               f"- DeepSeek challenger: {'WORKS' if challenger_ok else 'NOT WORKING'} (ping + real draft)",
               f"- GPT-OSS judge: {'WORKS' if judge_ok else 'NOT WORKING'} "
               f"({', '.join(sorted(judged_live)) or 'no valid verdict'})",
               f"- Generation: {'completed' if gen_ok else 'did not reach the comparison'}"]
    (OUT / "report.md").write_text("\n".join(report) + "\n")
    log("\n" + "\n".join(report))
    return 0 if challenger_ok and judge_ok else 1


if __name__ == "__main__":
    os.environ.setdefault("STORY_MODE", "lore")
    sys.exit(main())
