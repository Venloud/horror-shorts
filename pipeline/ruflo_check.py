"""Validate the Night Files Ruflo orchestration manifest without running Ruflo.

This is deliberately dependency-free and safe to run in GitHub Actions or locally.
It never starts a daemon, swarm, agent, MCP server, or production task.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "pipeline" / "ruflo_plan.json"

REQUIRED_STAGES = [
    "research", "story", "story_bible", "shot_rules", "visuals",
    "voice", "render", "qa", "buffer", "publish",
]


def main() -> int:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    stages = data.get("stages") or []
    ids = [s.get("id") for s in stages]
    missing = [x for x in REQUIRED_STAGES if x not in ids]
    if missing:
        raise SystemExit(f"RUFLO CHECK FAILED: missing stages: {', '.join(missing)}")

    stage_set = set(ids)
    for stage in stages:
        for dep in stage.get("depends_on", []):
            if dep not in stage_set:
                raise SystemExit(
                    f"RUFLO CHECK FAILED: {stage['id']} depends on unknown stage {dep}"
                )

    if data.get("execution_mode") != "declarative-only":
        raise SystemExit("RUFLO CHECK FAILED: execution_mode must remain declarative-only")
    if data.get("production_blocking") is not False:
        raise SystemExit("RUFLO CHECK FAILED: production_blocking must be false")
    if data.get("requires_ruflo_runtime") is not False:
        raise SystemExit("RUFLO CHECK FAILED: requires_ruflo_runtime must be false")

    print("RUFLO CHECK: PASS")
    print("Production execution: unchanged")
    print("Ruflo runtime required: no")
    print("Declared stage order:")
    for i, stage in enumerate(stages, 1):
        deps = ", ".join(stage.get("depends_on", [])) or "none"
        print(f"  {i:02d}. {stage['id']} [{stage.get('role', '?')}] <- {deps}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
