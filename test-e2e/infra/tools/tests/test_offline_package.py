"""Offline package Case checks without building or pulling Docker images."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "automation"))
from d5 import assets as d5_assets
from d5.scenarios import scenario_security_reliability_deployment as scenario


class OfflinePackageTests(unittest.IsolatedAsyncioTestCase):
    async def test_long_command_streams_output_and_times_out(self):
        with tempfile.TemporaryDirectory() as root:
            log_path = Path(root) / "command.log"
            code, output = await d5_assets.run_command(
                sys.executable, "-c", "print('streamed')", cwd=Path(root), log_path=log_path, timeout=10)
            self.assertEqual(code, 0)
            self.assertIn("streamed", output)
            self.assertIn("streamed", log_path.read_text(encoding="utf-8"))
            with self.assertRaisesRegex(AssertionError, "timed out"):
                await d5_assets.run_command(
                    sys.executable, "-c", "import time; time.sleep(5)",
                    cwd=Path(root), log_path=log_path, timeout=0.1)

    async def test_uses_local_latest_and_verifies_generated_package(self):
        with tempfile.TemporaryDirectory() as root:
            result_dir = Path(root)
            commands = []

            async def command(*args, **kwargs):
                commands.append((args, kwargs))
                if "--dry-run" in args:
                    return 0, "Images to pull:\nnexent/nexent:latest\nredis:alpine\n"
                if args[0] == "docker":
                    return 0, ""
                kwargs["log_path"].parent.mkdir(parents=True, exist_ok=True)
                kwargs["log_path"].write_text("Using existing local images\n", encoding="utf-8")
                output = Path(args[args.index("--output-dir") + 1])
                images = output / "images"
                images.mkdir(parents=True)
                (output / "manifest.yaml").write_text(
                    "version: latest\nimageSource: local-latest\nimages:\n"
                    "  - nexent/nexent:latest\n  - redis:alpine\n", encoding="utf-8")
                (images / "nexent-latest.tar").write_bytes(b"image")
                (images / "redis-alpine.tar").write_bytes(b"redis")
                checksums = []
                for relative in ("manifest.yaml", "images/nexent-latest.tar", "images/redis-alpine.tar"):
                    checksums.append(f"{hashlib.sha256((output / relative).read_bytes()).hexdigest()}  ./{relative}")
                (output / "checksums.txt").write_text("\n".join(checksums) + "\n", encoding="utf-8")
                return 0, ""

            with patch.dict(os.environ, {"RESULT_DIR": str(result_dir)}), \
                    patch.object(scenario, "destructive_deployment_enabled"), \
                    patch.object(scenario, "require_command", side_effect=lambda name: name), \
                    patch.object(scenario, "run_command", side_effect=command):
                await scenario._offline_package()
            build = commands[-1]
            self.assertIn(("--version", "latest"), list(zip(build[0], build[0][1:])))
            self.assertIn(("--image-source", "local-latest"), list(zip(build[0], build[0][1:])))
            self.assertEqual(build[1]["log_path"], result_dir / "logs/offline-package.log")
            self.assertEqual([args[0][0] for args in commands].count("docker"), 2)

    async def test_missing_local_image_blocks_before_package_build(self):
        with tempfile.TemporaryDirectory() as root:
            commands = []

            async def command(*args, **kwargs):
                commands.append(args)
                if "--dry-run" in args:
                    return 0, "Images to pull:\nnexent/nexent:latest\n"
                return 1, "missing"

            with patch.dict(os.environ, {"RESULT_DIR": root}), \
                    patch.object(scenario, "destructive_deployment_enabled"), \
                    patch.object(scenario, "require_command", side_effect=lambda name: name), \
                    patch.object(scenario, "run_command", side_effect=command):
                with self.assertRaises(pytest.skip.Exception):
                    await scenario._offline_package()
            self.assertEqual(len(commands), 2)


if __name__ == "__main__":
    unittest.main()
