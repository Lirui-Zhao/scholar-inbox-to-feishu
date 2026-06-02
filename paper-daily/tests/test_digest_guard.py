"""Exit-code tests for digest_guard.py (stale-digest guard), run as a subprocess.

Subprocess keeps it honest: STATE_DIR is read at module import, so we point
PAPER_DAILY_STATE_DIR at a fresh temp dir per test via the child's env.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

GUARD = os.path.join(os.path.dirname(__file__), "..", "scripts", "digest_guard.py")

PROCEED, SKIP = 0, 10


class DigestGuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pd-guard-")
        self.env = dict(os.environ, PAPER_DAILY_STATE_DIR=self.tmp)
        self.fp_path = os.path.join(self.tmp, "fp.json")
        self._write_fp("abc123", ["1", "2", "3"])

    def _write_fp(self, fingerprint, ids):
        with open(self.fp_path, "w") as f:
            json.dump({"fingerprint": fingerprint, "paper_ids": ids, "n": len(ids)}, f)

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, GUARD, *args],
            env=self.env, capture_output=True, text=True,
        ).returncode

    def test_first_run_proceeds(self):
        self.assertEqual(self._run("check", "--fp", self.fp_path,
                                   "--date", "2026-06-01", "--auto-skip"), PROCEED)

    def test_same_day_retry_proceeds(self):
        self._run("record", "--fp", self.fp_path, "--date", "2026-06-01")
        # same fingerprint, same date = a retry of today's run → proceed
        self.assertEqual(self._run("check", "--fp", self.fp_path,
                                   "--date", "2026-06-01", "--auto-skip"), PROCEED)

    def test_stale_different_day_with_auto_skip(self):
        self._run("record", "--fp", self.fp_path, "--date", "2026-06-01")
        # same fingerprint, later date (server re-served last digest) → skip
        self.assertEqual(self._run("check", "--fp", self.fp_path,
                                   "--date", "2026-06-02", "--auto-skip"), SKIP)

    def test_stale_without_auto_skip_proceeds(self):
        self._run("record", "--fp", self.fp_path, "--date", "2026-06-01")
        # explicit --date (no --auto-skip) → process anyway
        self.assertEqual(self._run("check", "--fp", self.fp_path,
                                   "--date", "2026-06-02"), PROCEED)

    def test_new_digest_proceeds(self):
        self._run("record", "--fp", self.fp_path, "--date", "2026-06-01")
        self._write_fp("def456", ["4", "5"])   # genuinely new set
        self.assertEqual(self._run("check", "--fp", self.fp_path,
                                   "--date", "2026-06-02", "--auto-skip"), PROCEED)


if __name__ == "__main__":
    unittest.main()
