"""Exercise clean synchronization without network or deployment."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/daily-launch.py"
spec = importlib.util.spec_from_file_location("daily_launch", SCRIPT)
launcher = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = launcher
spec.loader.exec_module(launcher)


class DailyLaunchTests(unittest.TestCase):
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
