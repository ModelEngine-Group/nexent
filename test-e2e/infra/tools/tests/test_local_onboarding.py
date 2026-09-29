"""Offline tests for the machine-local developer entrypoint."""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from launch_runtime import selected_python
from bootstrap_runtime import main as bootstrap_main
from local_preflight import static_config_problems
from onboard_local import checked_home, create_missing, main


class LocalOnboardingTests(unittest.TestCase):
    def test_preview_does_not_create_files(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root) / "test-home"
            self.assertEqual(main(["--test-home", str(home)]), 0)
            self.assertFalse(home.exists())

    def test_creation_preserves_existing_config(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root) / "test-home"
            config = home / "config"
            config.mkdir(parents=True)
            existing = config / "secrets.env"
            existing.write_text("KEEP_ME=private\n", encoding="utf-8")
            args = argparse.Namespace(interactive=False, urls={}, container_host=None, mcp_container_host=None)
            result = create_missing(home, args)
            self.assertEqual(existing.read_text(encoding="utf-8"), "KEEP_ME=private\n")
            self.assertIn({"file": "secrets.env", "status": "KEPT"}, result)
            self.assertTrue((config / "pipeline.yaml").is_file())

    def test_preflight_accepts_optional_unset_profiles(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root) / "test-home"
            args = argparse.Namespace(interactive=False, urls={}, container_host="host.docker.internal",
                                      mcp_container_host=None)
            create_missing(home, args)
            online = [{"stage": "D2", "status": "active", "execution": {"preparation": {"anchors": []}}}]
            problems = static_config_problems(home, online)
            self.assertTrue(any("placeholder" in issue for issue in problems))
            self.assertFalse(any("unset secret key" in issue for issue in problems))

    def test_selects_existing_windows_or_linux_home_runtime(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root)
            suffix = Path("Scripts/python.exe") if sys.platform == "win32" else Path("bin/python")
            runtime = home / "runtime/test-venv" / suffix
            runtime.parent.mkdir(parents=True)
            runtime.touch()
            self.assertEqual(selected_python(["doctor", "--test-home", str(home)], Path(sys.executable)), runtime)
            self.assertIsNone(selected_python(["doctor", "--test-home", str(home)], runtime))

    def test_legacy_backend_venv_is_never_selected(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root)
            suffix = Path("Scripts/python.exe") if sys.platform == "win32" else Path("bin/python")
            legacy = home / "runtime/backend-venv" / suffix
            legacy.parent.mkdir(parents=True)
            legacy.touch()
            with self.assertRaisesRegex(FileNotFoundError, "bootstrap --execute"):
                selected_python(["doctor", "--test-home", str(home)], Path(sys.executable))
            preferred = home / "runtime/test-venv" / suffix
            preferred.parent.mkdir(parents=True)
            preferred.touch()
            self.assertEqual(selected_python(["resume", "--test-home", str(home)], legacy), preferred)

    def test_bootstrap_plans_one_test_venv_without_installing(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root) / "home"
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(bootstrap_main(["--test-home", str(home)]), 0)
            plan = json.loads(output.getvalue())
            sdk_install = next(row for row in plan if row["argv"][:3] == ["uv", "pip", "install"])
            self.assertIn("test-venv", " ".join(sdk_install["argv"]))
            self.assertNotIn("--no-deps", sdk_install["argv"])
            self.assertNotIn("backend-venv", output.getvalue())
            self.assertFalse(home.exists())

    def test_interactive_prompts_for_test_home_when_omitted(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root) / "my-test-home"
            with patch("builtins.input", side_effect=["relative-path", str(home)]) as ask, \
                    patch("onboard_local.create_missing", return_value=[]) as create, \
                    redirect_stdout(StringIO()):
                self.assertEqual(main(["--interactive", "--execute"]), 0)
            self.assertEqual(ask.call_count, 2)
            self.assertEqual(create.call_args.args[0], home)

    def test_interactive_keeps_explicit_test_home_without_prompting_again(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root) / "my-test-home"
            with patch("builtins.input", side_effect=AssertionError("unexpected prompt")), \
                    patch("onboard_local.create_missing", return_value=[]) as create, \
                    redirect_stdout(StringIO()):
                self.assertEqual(main(["--interactive", "--execute", "--test-home", str(home)]), 0)
            self.assertEqual(create.call_args.args[0], home)

    def test_test_home_must_be_absolute(self):
        with self.assertRaisesRegex(ValueError, "absolute path"):
            checked_home(Path("relative-test-home"))


if __name__ == "__main__":
    unittest.main()
