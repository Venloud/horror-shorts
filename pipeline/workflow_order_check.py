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


class _UniqueKeyLoader(yaml.SafeLoader):
    """Reject duplicate YAML keys instead of silently dropping the first value."""

    def construct_mapping(self, node, deep=False):
        seen = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    None, None, f"duplicate YAML key {key!r}", key_node.start_mark
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def problems(path: Path) -> list[str]:
    found = []
    try:
        jobs = (yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader) or {}).get("jobs") or {}
    except yaml.YAMLError as exc:
        return [f"{path}: invalid workflow YAML: {exc}"]
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
