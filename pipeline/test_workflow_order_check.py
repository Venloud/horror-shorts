import tempfile
import unittest
from pathlib import Path

import workflow_order_check as check


def write(text):
    path = Path(tempfile.mkdtemp()) / "wf.yml"
    path.write_text(text)
    return path


class WorkflowOrderTests(unittest.TestCase):
    def test_reference_to_later_step_is_reported(self):
        path = write("jobs:\n  a:\n    steps:\n"
                     "      - name: uses later\n        if: steps.up.outcome == 'success'\n        run: echo\n"
                     "      - id: up\n        run: echo\n")
        self.assertEqual(len(check.problems(path)), 1)

    def test_reference_to_earlier_step_is_fine(self):
        path = write("jobs:\n  a:\n    steps:\n"
                     "      - id: up\n        run: echo\n"
                     "      - if: steps.up.outcome == 'success'\n        run: echo\n")
        self.assertEqual(check.problems(path), [])

    def test_duplicate_yaml_key_is_rejected_before_actions(self):
        path = write("on:\\n  workflow_dispatch:\\n"
                     "jobs:\\n  fill:\\n    steps:\\n"
                     "      - uses: actions/cache@v4\\n"
                     "        with:\\n"
                     "          key: model-cache\\n"
                     "          restore-keys: older-cache\\n"
                     "          restore-keys: other-cache\\n")
        problems = check.problems(path)
        self.assertEqual(len(problems), 1)
        self.assertIn("duplicate YAML key", problems[0])

    def test_repository_workflows_are_ordered(self):
        root = Path(__file__).resolve().parents[1] / ".github" / "workflows"
        errors = [e for p in sorted(root.glob("*.yml")) for e in check.problems(p)]
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
