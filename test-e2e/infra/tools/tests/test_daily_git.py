# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Git transport regressions use subprocess fakes and never access a network."""
from pathlib import Path
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import subprocess

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import daily_git


def process(code=0, stdout=b"", stderr=b""):
    instance = Mock()
    instance.returncode = code
    instance.communicate.return_value = (stdout, stderr)
    return instance


class DailyGitTests(unittest.TestCase):
    def test_success_preserves_stdout_and_private_streams(self):
        with tempfile.TemporaryDirectory() as root, patch.object(daily_git.subprocess, "Popen", return_value=process(stdout=b"head\n", stderr=b"notice\n")):
            logs = Path(root) / "git"
            self.assertEqual(daily_git.run_git(Path(root), ["rev-parse", "HEAD"], log_dir=logs), "head")
            receipt = json.loads(next(logs.glob("*.json")).read_text())
            self.assertEqual(receipt["exit_code"], 0)
            self.assertEqual((logs / receipt["stderr"]).read_text(), "notice\n")

    def test_transient_fetch_error_is_retained_before_retry(self):
        with tempfile.TemporaryDirectory() as root, patch.object(daily_git.subprocess, "Popen", side_effect=[process(128, stderr=b"fatal: connection reset by peer\n"), process(stdout=b"updated\n")]) as popen, patch.object(daily_git.time, "sleep"):
            logs = Path(root) / "git"
            self.assertEqual(daily_git.run_git(Path(root), ["fetch", "origin", "refs/heads/develop"], log_dir=logs), "updated")
            self.assertEqual(popen.call_count, 2)
            receipts = [json.loads(p.read_text()) for p in logs.glob("*.json")]
            self.assertEqual(sorted(r["exit_code"] for r in receipts), [0, 128])
            self.assertTrue(any("connection reset" in p.read_text() for p in logs.glob("*.stderr.log")))

    def test_authentication_error_is_not_retried(self):
        with patch.object(daily_git.subprocess, "Popen", return_value=process(128, stderr=b"fatal: Authentication failed")) as popen:
            with self.assertRaisesRegex(RuntimeError, "Authentication failed"):
                daily_git.run_git(Path("repo"), ["fetch", "origin", "refs/heads/develop"])
            self.assertEqual(popen.call_count, 1)

    def test_merge_conflict_is_not_retried(self):
        with patch.object(daily_git.subprocess, "Popen", return_value=process(128, stderr=b"fatal: Not possible to fast-forward")) as popen:
            with self.assertRaisesRegex(RuntimeError, "fast-forward"):
                daily_git.run_git(Path("repo"), ["merge", "--ff-only", "head"])
            self.assertEqual(popen.call_count, 1)

    def test_retries_are_bounded(self):
        with patch.object(daily_git.subprocess, "Popen", side_effect=lambda *a, **k: process(128, stderr=b"fatal: early EOF")) as popen, patch.object(daily_git.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "early EOF"):
                daily_git.run_git(Path("repo"), ["fetch", "origin", "refs/heads/develop"])
            self.assertEqual(popen.call_count, 3)

    def test_timeout_kills_children_and_retains_partial_stderr(self):
        child = process()
        child.pid = 1234
        child.communicate.side_effect = [subprocess.TimeoutExpired("git", 30), (b"", b"partial transport output")]
        with tempfile.TemporaryDirectory() as root, patch.object(daily_git.subprocess, "Popen", return_value=child), patch.object(daily_git.subprocess, "run") as taskkill, patch.object(daily_git.os, "killpg", create=True) as kill:
            logs = Path(root) / "git"
            with self.assertRaisesRegex(RuntimeError, "exit 124"):
                daily_git.run_git(Path(root), ["fetch", "origin"], log_dir=logs, attempts=1)
            if os.name == "nt":
                taskkill.assert_called_once()
            else:
                kill.assert_called_once()
            receipt = json.loads(next(logs.glob("*.json")).read_text())
            self.assertTrue(receipt["timed_out"])
            self.assertEqual((logs / receipt["stderr"]).read_text(), "partial transport output")

    def test_credentials_are_redacted_in_error_and_evidence(self):
        stderr = b"fatal: https://user:secret@example.test/repo?token=hidden\nAuthorization: Bearer sensitive\n"
        with tempfile.TemporaryDirectory() as root, patch.object(daily_git.subprocess, "Popen", return_value=process(128, stderr=stderr)):
            logs = Path(root) / "git"
            with self.assertRaises(RuntimeError) as result:
                daily_git.run_git(Path(root), ["fetch", "origin"], log_dir=logs)
            evidence = str(result.exception) + "".join(p.read_text() for p in logs.iterdir())
            for secret in ["user:secret", "hidden", "sensitive"]:
                self.assertNotIn(secret, evidence)


if __name__ == "__main__":
    unittest.main()
