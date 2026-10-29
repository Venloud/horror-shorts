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
        path = write("on:\n  workflow_dispatch:\n"
                     "jobs:\n  fill:\n    steps:\n"
                     "      - uses: actions/cache@v4\n"
                     "        with:\n"
                     "          key: model-cache\n"
                     "          restore-keys: older-cache\n"
                     "          restore-keys: other-cache\n")
        problems = check.problems(path)
        self.assertEqual(len(problems), 1)
        self.assertIn("duplicate YAML key", problems[0])

    def test_mrbeast_clipper_workflows_checkout_main_after_branch_cleanup(self):
        """The clipper lives on main: merged feature branches may be deleted.

        This must run in standard CI so an old checkout ref cannot silently
        break the next scheduled MrBeast TikTok inbox draft.
        """
        root = Path(__file__).resolve().parents[1]
        for name in ("tiktok_clipper_scheduled.yml", "tiktok_clipper_preview.yml"):
            path = root / ".github" / "workflows" / name
            source = path.read_text(encoding="utf-8")
            self.assertIn("ref: main", source, name)
            self.assertNotIn("ref: feature/mrbeast-split-tiktok", source, name)
            self.assertIn("clipper/", source, name)

    def test_mrbeast_posting_remains_drafts_only(self):
        root = Path(__file__).resolve().parents[1]
        scheduled = (root / ".github" / "workflows" / "tiktok_clipper_scheduled.yml").read_text()
        preview = (root / ".github" / "workflows" / "tiktok_clipper_preview.yml").read_text()
        poster = (root / "clipper" / "post.py").read_text()
        # Since d21f012 the scheduled workflow calls tiktok.send_to_drafts inline (after reserving the clip in the
        # durable ledger) instead of clipper/post.py: either route is the drafts-only inbox upload, never direct post.
        self.assertTrue("clipper/post.py --video clipper/output/tiktok.mp4 --mode draft" in scheduled
                        or "send_to_drafts(" in scheduled, "scheduled clipper must use the drafts-only upload")
        for source in (scheduled, preview):
            self.assertNotIn("post_direct", source)
            self.assertNotIn("--mode direct", source)
        self.assertNotIn("clipper/post.py", preview)
        self.assertNotIn("send_to_drafts(", preview)
        self.assertIn('choices=["draft"]', poster)

    def test_repository_workflows_are_ordered(self):
        root = Path(__file__).resolve().parents[1] / ".github" / "workflows"
        errors = [e for p in sorted(root.glob("*.yml")) for e in check.problems(p)]
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
