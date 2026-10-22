"""Fail if a workflow step reads steps.<id> before the step with that id has run.

A step that references a later step always sees an empty outcome, so its condition silently never matches
(daily.yml's "Mark checkpoint complete" step did this until 2026-10-22).
Usage: python pipeline/workflow_order_check.py [workflow.yml ...]  (default: every .github/workflows/*.yml)
"""
import re
import sys
from pathlib import Path

import yaml

REF = re.compile(r"steps\.([A-Za-z_][\w-]*)\.")


def problems(path: Path) -> list[str]:
    found = []
    jobs = (yaml.safe_load(path.read_text()) or {}).get("jobs") or {}
    for job_name, job in jobs.items():
        ids = [step.get("id") for step in job.get("steps") or []]
        for index, step in enumerate(job.get("steps") or []):
            text = yaml.safe_dump(step)
            for ref in set(REF.findall(text)):
                if ref in ids and ids.index(ref) >= index:
                    found.append(f"{path}: job {job_name}, step {index + 1} "
                                 f"({step.get('name') or step.get('uses')}) reads steps.{ref} before it runs")
    return found


def main(argv: list[str]) -> int:
    paths = [Path(p) for p in argv] or sorted(Path(".github/workflows").glob("*.yml"))
    errors = [p for path in paths for p in problems(path)]
    for error in errors:
        print(error)
    print(f"Workflow step order: {len(paths)} files, {len(errors)} problems")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
