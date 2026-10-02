"""Validate the Night Files Ruflo task contracts against the orchestration manifest.

This validator is intentionally dependency-free. It checks documentation contracts only.
It never starts Ruflo, agents, swarms, MCP servers, daemons, or production tasks.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "pipeline" / "ruflo_plan.json"
TASK_DIR = ROOT / "docs" / "ruflo_tasks"

REQUIRED_TASKS = {
    "planner": "planner.md",
    "researcher": "researcher.md",
    "writer": "story_writer.md",
    "visual_planner": "visual_planner.md",
    "qa_reviewer": "qa_reviewer.md",
    "packaging_reviewer": "packaging_reviewer.md",
}

REQUIRED_SECTIONS = [
    "## Purpose",
    "## Inputs",
    "## Outputs",
    "## Responsibilities",
    "## Constraints",
]


def main() -> int:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    roles = data.get("roles") or {}

    missing = []
    invalid = []

    for role, filename in REQUIRED_TASKS.items():
        path = TASK_DIR / filename
        if not path.is_file():
            missing.append(filename)
            continue

        text = path.read_text(encoding="utf-8")
        for section in REQUIRED_SECTIONS:
            if section not in text:
                invalid.append(f"{filename}: missing {section}")

        if role not in roles:
            invalid.append(f"{filename}: role missing from manifest roles")

    if missing:
        raise SystemExit(
            "RUFLO TASK CHECK FAILED: missing task contracts: " + ", ".join(missing)
        )
    if invalid:
        raise SystemExit(
            "RUFLO TASK CHECK FAILED:\n- " + "\n- ".join(invalid)
        )

    print("RUFLO TASK CHECK: PASS")
    print("Task contracts:")
    for role, filename in REQUIRED_TASKS.items():
        print(f"  - {role}: docs/ruflo_tasks/{filename}")

    print("Production execution: unchanged")
    print("Ruflo runtime required: no")
    print("Agent/swarm execution: disabled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
