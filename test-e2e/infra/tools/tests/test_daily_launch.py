# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Exercise clean synchronization without network or deployment."""
from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import subprocess
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/daily-launch.py"
spec = importlib.util.spec_from_file_location("daily_launch", SCRIPT)
launcher = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = launcher
spec.loader.exec_module(launcher)


class DailyLaunchTests(unittest.TestCase):
    def test_real_local_fetch_outside_checkout_retains_streams(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root).resolve()
            origin, checkout, logs = root / "origin", root / "checkout", root / "logs"
            subprocess.run(["git", "init", "-b", "develop", str(origin)], check=True, capture_output=True)
            commit = ["git", "-C", str(origin), "-c", "user.name=Test Runner",
                      "-c", "user.email=runner@example.invalid", "commit", "--allow-empty", "-m"]
            subprocess.run([*commit, "initial"], check=True, capture_output=True)
            subprocess.run(["git", "clone", str(origin), str(checkout)], check=True, capture_output=True)
            subprocess.run([*commit, "next"], check=True, capture_output=True)
            expected = subprocess.check_output(["git", "-C", str(origin), "rev-parse", "HEAD"], text=True).strip()
            previous = Path.cwd()
            try:
                os.chdir(root)
                self.assertEqual(launcher.sync_checkout(checkout, "develop", log_dir=logs), expected)
            finally:
                os.chdir(previous)
            receipts = [json.loads(path.read_text()) for path in logs.glob("*.json")]
            self.assertTrue(any(row["operation"] == "fetch" and row["exit_code"] == 0 for row in receipts))
            self.assertTrue(any(row["operation"] == "merge" and row["exit_code"] == 0 for row in receipts))
            self.assertTrue(all((logs / row["stderr"]).is_file() for row in receipts))

    def test_publication_is_explicit_and_dry_run_has_no_outputs(self):
        with tempfile.TemporaryDirectory() as root:
            for extra, expected in (([], False), (["--publish-latest"], True)):
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(launcher.main(["--test-home", root, "--branch", "develop", *extra]), 0)
                self.assertEqual(json.loads(output.getvalue())["publish_latest"], expected)
                self.assertFalse((Path(root) / "runs-ubuntu").exists())

    def test_dirty_checkout_never_fetches(self):
        with patch.object(launcher, "git", return_value=" M file") as git:
            with self.assertRaisesRegex(RuntimeError, "clean checkout"):
                launcher.sync_checkout(Path("repo"), "develop")
            self.assertEqual(git.call_count, 1)

    def test_wrong_branch_never_fetches(self):
        with patch.object(launcher, "git", side_effect=["", "other"]) as git:
            with self.assertRaisesRegex(RuntimeError, "branch differs"):
                launcher.sync_checkout(Path("repo"), "develop")
            self.assertEqual(git.call_count, 2)

    def test_fast_forward_is_pinned(self):
        with patch.object(launcher, "git", side_effect=["", "develop", "", "", "sha", "", "sha"]) as git:
            self.assertEqual(launcher.sync_checkout(Path("repo"), "develop"), "sha")
            self.assertIn(unittest.mock.call(Path("repo"), "merge", "--ff-only", "sha"), git.call_args_list)

    def test_local_ahead_is_rejected(self):
        with patch.object(launcher, "git", side_effect=["", "develop", "", "", "remote", "", "local"]):
            with self.assertRaisesRegex(RuntimeError, "Local commits"):
                launcher.sync_checkout(Path("repo"), "develop")

    def test_divergence_never_resets(self):
        import subprocess
        with patch.object(launcher, "git", side_effect=["", "develop", "", "", "remote", subprocess.CalledProcessError(1, "merge")]) as git:
            with self.assertRaises(subprocess.CalledProcessError):
                launcher.sync_checkout(Path("repo"), "develop")
            self.assertFalse(any("reset" in call.args or "stash" in call.args for call in git.call_args_list))
