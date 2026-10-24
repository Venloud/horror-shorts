"""TEST-ONLY check of the writing room's extra endpoints (writer_endpoint_test.yml). Nothing is voiced, rendered,
buffered, posted or written to history / inbox / counter.

1. Ping: one tiny JSON call to the challenger (config writer_challenger_model, DeepSeek on NVIDIA) and to every
   configured independent judge (writer_judge_models, GPT-OSS 120B on Groq / OpenRouter).
2. Generation: one real story through story.write_story with writer_challenge_policy forced to "always", so the
   challenger draft (DeepSeek, else the configured fallbacks) and the comparison really run. Each configured judge is
   also asked to compare the two drafts with the production prompt (sample drafts if no comparison ran).
0. NVIDIA diagnosis: catalogue listing, tiny plain + streaming requests, a small control model and a verdict
   (wrong id / overloaded / model stalled / endpoint down / too slow for long generations).

  STORY_MODE=lore python writer_endpoint_test.py   (STORY_MODE skips the inbox)
Writes output/writer_endpoint_test/report.md + story.json. Exit 1 when the challenger or every judge failed.
"""
import json
import re
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


def _tiny(model: str, stream: bool = False, timeout: float = 45) -> dict:
    """One minimal chat (16 tokens) straight to NVIDIA: status, latency (to the first byte when streaming), body."""
    import requests
    from providers import nvidia
    body = {"model": model, "messages": [{"role": "user", "content": "Say OK."}], "max_tokens": 16,
            "temperature": 0.0, "stream": stream}
    t = time.time()
    try:
        r = requests.post("https://integrate.api.nvidia.com/v1/chat/completions", json=body, timeout=timeout,
                          stream=stream, headers={"Authorization": f"Bearer {nvidia.key()}",
                                                  "Accept": "text/event-stream" if stream else "application/json"})
        first = None
        if stream and r.status_code == 200:
            for chunk in r.iter_lines():
                if chunk:
                    first = round(time.time() - t, 1)
                    break
        text = "" if stream and r.status_code == 200 else r.text[:200]
        return {"status": r.status_code, "seconds": round(time.time() - t, 1), "first_byte": first, "body": text,
                "headers": {k: v for k, v in r.headers.items() if k.lower() in ("retry-after", "x-ratelimit-remaining",
                                                                               "nvcf-status", "nvcf-reqid")}}
    except Exception as exc:  # noqa: BLE001
        return {"status": None, "seconds": round(time.time() - t, 1), "error": f"{type(exc).__name__}: {exc}"[:200]}


def diagnose_nvidia(model: str) -> list[str]:
    """Is the model in NVIDIA's catalogue, does the endpoint answer for it at all (tiny request, streaming first
    byte), and does a small control model answer with the same key? Distinguishes: wrong / retired id (404 or not
    listed), overloaded (429 / 503 / 504), this model stalled (timeout while the control answers), endpoint or key
    down (control fails too)."""
    import requests
    from providers import nvidia
    out = []
    ids = []
    try:
        r = requests.get("https://integrate.api.nvidia.com/v1/models",
                         headers={"Authorization": f"Bearer {nvidia.key()}"}, timeout=30)
        ids = [m.get("id", "") for m in (r.json().get("data") or [])] if r.status_code == 200 else []
        out.append(f"- Catalogue /v1/models: HTTP {r.status_code}, {len(ids)} models; `{model}` listed: "
                   f"**{model in ids}**")
        out.append("- DeepSeek ids offered: " + (", ".join(f"`{i}`" for i in ids if "deepseek" in i.lower())
                                                 or "none"))
    except Exception as exc:  # noqa: BLE001
        out.append(f"- Catalogue check failed: {str(exc)[:200]}")
    tries = [_tiny(model), _tiny(model), _tiny(model, stream=True)]
    for k, res in enumerate(tries, 1):
        kind = "streaming" if k == 3 else "plain"
        out.append(f"- `{model}` tiny {kind} request {k}: HTTP {res.get('status')} in {res['seconds']} s"
                   + (f", first byte {res['first_byte']} s" if res.get("first_byte") else "")
                   + (f", headers {res['headers']}" if res.get("headers") else "")
                   + f": {res.get('error') or res.get('body') or 'answered'}")
    # control: a small model that answers 200 (a catalogue entry can still be "Not found for account": listed is not
    # the same as deployed). Any fast HTTP answer, even a 404, proves the endpoint and the key respond.
    control, control_id = None, None
    pool = [i for i in ("meta/llama-3.1-8b-instruct", "meta/llama-3.2-3b-instruct", "mistralai/mistral-7b-instruct-v0.3",
                        "google/gemma-2-9b-it", "microsoft/phi-3-mini-4k-instruct") if i in ids]
    pool += [i for i in ids if re.search(r"\b(?:[1-9]b)-instruct", i) and i not in pool]
    answered = None
    for cid in pool[:6]:
        res = _tiny(cid, timeout=30)
        out.append(f"- Control `{cid}`: HTTP {res.get('status')} in {res['seconds']} s: "
                   f"{res.get('error') or (res.get('body') or 'answered')[:120]}")
        if res.get("status") is not None and answered is None:
            answered = res
        if res.get("status") == 200:
            control, control_id = res, cid
            break
    codes = [t.get("status") for t in tries]
    if ids and model not in ids or 404 in codes:
        verdict = "MODEL ID NOT AVAILABLE (not in the catalogue / 404): the configured id is wrong or retired"
    elif any(c in (429, 503, 504) for c in codes):
        verdict = "OVERLOADED / RATE-LIMITED (429 / 503 / 504 from NVIDIA)"
    elif all(c == 200 for c in codes):
        verdict = ("ENDPOINT RESPONDS for tiny requests: the timeouts come from long generations (full story, "
                   "8000 max tokens) being too slow on this model")
    elif control:
        verdict = (f"THIS MODEL IS STALLED: listed, but no response (not even a first streamed byte) while "
                   f"`{control_id}` answers 200 with the same key")
    elif answered:
        verdict = ("THIS MODEL IS STALLED: listed, but no response, while the endpoint answers other requests at "
                   "once with the same key (no 200 control found)")
    else:
        verdict = "NVIDIA ENDPOINT / KEY NOT RESPONDING (no control model answered at all)"
    out.append(f"- **Verdict: {verdict}**")
    return out


def main() -> int:
    import story
    OUT.mkdir(parents=True, exist_ok=True)
    challenger = str(CONFIG.get("writer_challenger_model"))
    judges = [m for m in CONFIG.get("writer_judge_models", []) if isinstance(m, str)]
    report = ["# Writer endpoint test (nothing buffered / posted / saved to history)", "",
              f"Challenger: `{challenger}` (key present: {story._available(challenger)})",
              "Judges: " + ", ".join(f"`{j}` (key present: {story._available(j)})" for j in judges), "",
              "## 1. Direct pings"]
    fallbacks = [m for m in CONFIG.get("writer_challenger_fallbacks", []) if isinstance(m, str)]
    report.insert(3, "Challenger fallbacks: " + ", ".join(f"`{m}` (key present: {story._available(m)})"
                                                         for m in fallbacks))
    with story.request_limit(60):
        pings = {m: _ping(m) for m in dict.fromkeys([challenger] + fallbacks + judges)}
    for p in pings.values():
        report.append(f"- `{p['model']}`: {'OK' if p['ok'] else 'FAILED'} in {p['seconds']} s: "
                      f"{p.get('answer') or p.get('error')}")

    if challenger.startswith("nvidia:"):
        report += ["", "### NVIDIA diagnosis (independent of the pipeline code)"] + diagnose_nvidia(challenger[7:])

    report += ["", "## 2. Real story generation (challenger forced on)"]
    CONFIG["writer_challenge_policy"] = "always"
    captured: list = []
    real_compare = story.compare_drafts

    def compare(a, b, context, api_key, kind, source=None):
        verdict = real_compare(a, b, context, api_key, kind, source)
        captured.append({"a": a, "b": b, "context": context, "kind": kind, "source": source, "verdict": verdict})
        return verdict
    story.compare_drafts = compare
    judged_live = set()
    try:
        made = story.write_story(load_history())
        w = made.get("writing") or {}
        (OUT / "story.json").write_text(json.dumps(made, indent=1, ensure_ascii=False, default=str))
        report += [f"- Story: '{made.get('title')}' (mode {made.get('mode')}, writer {made.get('writer')})",
                   f"- Primary: `{w.get('primary')}`", f"- Challenger: `{w.get('challenger')}`",
                   f"- Judge: `{w.get('judge')}`, selected draft {w.get('selected')}: {str(w.get('reason'))[:300]}",
                   f"- LLM calls in the writing room: {w.get('llm_calls')}"]
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

    used = [str(c["b"].get("model")) for c in captured if c["b"].get("model")]
    deepseek_ok = pings[challenger]["ok"] and challenger in used
    challenger_ok = bool(used)
    judge_ok = bool(judged_live)
    report += ["", "## Result",
               f"- DeepSeek challenger (`{challenger}`): {'WORKS' if deepseek_ok else 'NOT WORKING'} (ping + real draft)",
               f"- Challenger used in generation: {', '.join(f'`{m}`' for m in used) or 'none (no draft compared)'}",
               f"- GPT-OSS judge: {'WORKS' if judge_ok else 'NOT WORKING'} "
               f"({', '.join(sorted(judged_live)) or 'no valid verdict'})",
               f"- Generation: {'completed with a comparison' if challenger_ok else 'no challenger draft compared'}"]
    (OUT / "report.md").write_text("\n".join(report) + "\n")
    log("\n" + "\n".join(report))
    return 0 if challenger_ok and judge_ok else 1  # DeepSeek itself is reported, the fallback keeps production going


if __name__ == "__main__":
    os.environ.setdefault("STORY_MODE", "lore")
    sys.exit(main())
