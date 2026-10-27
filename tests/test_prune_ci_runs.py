import importlib.util
import unittest
from pathlib import Path

p = Path(__file__).resolve().parents[1] / 'tools' / 'prune_ci_runs.py'
s = importlib.util.spec_from_file_location('ci_pruner', p)
m = importlib.util.module_from_spec(s)
s.loader.exec_module(m)


def row(i, status='completed', conclusion='success'):
    return {'id': i, 'status': status, 'conclusion': conclusion, 'created_at': str(i).zfill(5)}


class RetentionTests(unittest.TestCase):
    def test_keeps_ten_completed(self):
        self.assertEqual(len(m.select_for_pruning([row(i) for i in range(15)])), 5)

    def test_protects_latest_failure(self):
        x = [row(i) for i in range(15)]
        x[2]['conclusion'] = 'failure'
        self.assertNotIn(2, [r['id'] for r in m.select_for_pruning(x)])

    def test_protects_in_progress(self):
        x = [row(i) for i in range(15)]
        x[0]['status'] = 'in_progress'
        self.assertNotIn(0, [r['id'] for r in m.select_for_pruning(x)])


if __name__ == '__main__':
    unittest.main()
