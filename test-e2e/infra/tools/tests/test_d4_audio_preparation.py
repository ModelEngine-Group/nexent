"""Check case-local Chromium audio bindings without contacting providers."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

AUTOMATION = Path(__file__).resolve().parents[2] / "automation"
sys.path.insert(0, str(AUTOMATION))

import prepare_d4_shared_assets as preparation


class AudioPreparationTests(unittest.TestCase):
    def test_default_fixture_is_bound_to_both_existing_keys(self):
        with tempfile.TemporaryDirectory() as temporary:
            wav = Path(temporary) / "assets/audio/stt_zh_number.wav"
            wav.parent.mkdir(parents=True)
            wav.write_bytes(b"audio-fixture")
            with patch.dict(os.environ, {"NEXENT_TEST_HOME": temporary}, clear=True), \
                    patch.object(preparation, "_ensure_stt_config", new=AsyncMock()):
                values = asyncio.run(preparation.prepare_stt(None))
            self.assertEqual(values["NEXENT_TEST_STT_READY"], "1")
            self.assertEqual(values["NEXENT_TEST_STT_WAV"], wav.resolve().as_posix())
            self.assertEqual(values["NEXENT_TEST_BROWSER_FAKE_AUDIO"], values["NEXENT_TEST_STT_WAV"])

    def test_missing_fixture_fails_before_provider_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.dict(os.environ, {"NEXENT_TEST_HOME": temporary}, clear=True), \
                    patch.object(preparation, "_ensure_stt_config", new=AsyncMock()) as configure:
                with self.assertRaisesRegex(ValueError, "WAV fixture"):
                    asyncio.run(preparation.prepare_stt(None))
                configure.assert_not_awaited()

    def test_conflicting_capture_does_not_silently_replace_user_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            wav = Path(temporary) / "custom.wav"
            wav.write_bytes(b"audio-fixture")
            env = {"NEXENT_TEST_HOME": temporary, "NEXENT_TEST_STT_WAV": str(wav),
                   "NEXENT_TEST_BROWSER_FAKE_AUDIO": str(Path(temporary) / "different.wav")}
            with patch.dict(os.environ, env, clear=True), \
                    patch.object(preparation, "_ensure_stt_config", new=AsyncMock()) as configure:
                with self.assertRaisesRegex(ValueError, "must match"):
                    asyncio.run(preparation.prepare_stt(None))
                configure.assert_not_awaited()

    def test_provider_failure_keeps_audio_binding_and_dependency_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            wav = Path(temporary) / "custom.wav"
            wav.write_bytes(b"audio-fixture")
            env = {"NEXENT_TEST_HOME": temporary, "NEXENT_TEST_STT_WAV": str(wav)}
            with patch.dict(os.environ, env, clear=True), \
                    patch.object(preparation, "_ensure_stt_config", new=AsyncMock(side_effect=RuntimeError("unavailable"))):
                values = asyncio.run(preparation.prepare_stt(None))
            self.assertEqual(values["NEXENT_TEST_STT_READY"], "0")
            self.assertIn("RuntimeError", values["NEXENT_TEST_STT_FAILURE"])
            self.assertEqual(values["NEXENT_TEST_BROWSER_FAKE_AUDIO"], wav.resolve().as_posix())


if __name__ == "__main__":
    unittest.main()
