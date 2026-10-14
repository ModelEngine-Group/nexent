"""Check case-local Chromium audio bindings without contacting providers."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import httpx

AUTOMATION = Path(__file__).resolve().parents[2] / "automation"
sys.path.insert(0, str(AUTOMATION))

import prepare_d4_shared_assets as preparation


class AudioPreparationTests(unittest.TestCase):
    def test_voice_bootstrap_creates_then_reuses_collision_safe_record(self):
        rows = [{'display_name': 'daily-text', 'model_type': 'tts', 'model_name': 'old-tts', 'id': 1}]
        posted = []
        configured = {'id': 'daily-text', 'model': 'new-tts'}
        payload = {'display_name': 'daily-text', 'model_name': 'new-tts', 'model_type': 'tts',
                   'model_factory': 'provider', 'api_key': 'fixture-only', 'base_url': 'wss://example.test'}

        def response(data):
            return httpx.Response(200, json=data, request=httpx.Request('POST', 'http://example.test'))

        class API:
            async def get(self, path):
                if path == '/model/list':
                    return response({'data': list(rows)})
                return response({'config': {'models': {}, 'app': {}}})

            async def post(self, path, json=None, params=None):
                posted.append((path, json))
                if path == '/model/create':
                    assert json['display_name'] != 'daily-text'
                    rows.append({**json, 'id': 2})
                return response({'data': {'connectivity': True}})

        @asynccontextmanager
        async def fake_client(*args, **kwargs):
            yield API()

        async def exercise():
            await preparation._ensure_voice_config(type('Identity', (), {'access_token': 'fixture'})(), 'tts')
            await preparation._ensure_voice_config(type('Identity', (), {'access_token': 'fixture'})(), 'tts')

        with patch.object(preparation, 'client', fake_client), \
                patch.object(preparation, 'configured_model', return_value=configured), \
                patch.object(preparation, 'model_request', side_effect=lambda *a, **k: dict(payload)):
            asyncio.run(exercise())
        self.assertEqual(sum(path == '/model/create' for path, _ in posted), 1)
        self.assertEqual(sum(path == '/model/temporary_healthcheck' for path, _ in posted), 2)
        updates = [body for path, body in posted if path == '/model/update']
        self.assertEqual(len(updates), 2)
        self.assertTrue(all(body['api_key'] == 'fixture-only' for body in updates))
        self.assertEqual(rows[0]['model_name'], 'old-tts')
        saved = [body for path, body in posted if path == '/config/save_config']
        self.assertEqual(len(saved), 2)
        self.assertEqual(saved[0]['models']['tts']['id'], 2)
        self.assertEqual(saved[0]['models']['tts']['displayName'], rows[1]['display_name'])
        self.assertEqual(saved[0]['models']['tts'], saved[1]['models']['tts'])

    def test_voice_namespace_reuses_exact_model(self):
        row = {'display_name': 'daily-text', 'model_type': 'tts', 'model_name': 'new-tts'}
        self.assertEqual(preparation._voice_display_name([row], 'daily-text', 'new-tts', 'tts', {}),
                         'daily-text')

    def test_voice_namespace_preserves_occupied_model_and_is_repeatable(self):
        row = {'display_name': 'daily-text', 'model_type': 'tts', 'model_name': 'old-tts'}
        payload = {'model_factory': 'provider', 'base_url': 'wss://example.test/realtime',
                   'api_key': 'secret-fixture'}
        name = preparation._voice_display_name([row], 'daily-text', 'new-tts', 'tts', payload)
        self.assertNotEqual(name, 'daily-text')
        matching = {'display_name': name, 'model_type': 'tts', 'model_name': 'new-tts'}
        self.assertEqual(preparation._voice_display_name([row, matching], 'daily-text', 'new-tts',
                                                        'tts', payload), name)
        self.assertEqual(row['model_name'], 'old-tts')
        self.assertNotIn('secret-fixture', name)
        self.assertEqual(preparation._voice_display_name([row], 'daily-text', 'new-tts', 'tts',
                                                        {**payload, 'api_key': 'rotated'}), name)

    def test_voice_namespace_refuses_conflicting_alternate(self):
        row = {'display_name': 'daily-text', 'model_type': 'tts', 'model_name': 'old-tts'}
        name = preparation._voice_display_name([row], 'daily-text', 'new-tts', 'tts', {})
        foreign = {'display_name': name, 'model_type': 'llm', 'model_name': 'unrelated'}
        with self.assertRaisesRegex(AssertionError, 'incompatible'):
            preparation._voice_display_name([row, foreign], 'daily-text', 'new-tts', 'tts', {})

    def test_voice_namespace_uses_original_when_available(self):
        self.assertEqual(preparation._voice_display_name([], 'daily-text', 'new-tts', 'tts', {}),
                         'daily-text')

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
