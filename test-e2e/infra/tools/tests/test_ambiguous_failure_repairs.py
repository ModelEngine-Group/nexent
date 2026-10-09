"""Regression checks for transport conversion, scoped faults and chain lookup."""
import importlib.util
import io
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import AsyncMock, patch
import wave

from fastapi import FastAPI
from fastapi.testclient import TestClient

INFRA = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(INFRA / 'automation'))
from shared.audio import stt_pcm16, stt_transport_audio
import tempfile


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fault = load('runtime_fault_provider_test', INFRA / 'environment/services/test-assets/runtime_fault_provider.py')
chain = load('delete_chain_test', INFRA.parent / 'cases/API-AUTO-2B3A078E3CD1B151/test.py')


def wav_bytes(rate, channels=1):
    output = io.BytesIO()
    with wave.open(output, 'wb') as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(struct.pack('<6h', 0, 1000, 2000, 3000, 4000, 5000))
    return output.getvalue()


class AudioTests(unittest.TestCase):
    def test_decode_and_resample_24k(self):
        result = stt_pcm16(wav_bytes(24000))
        self.assertEqual(struct.unpack('<4h', result), (0, 1500, 3000, 4500))

    def test_16k_retains_samples_without_container_header(self):
        result = stt_pcm16(wav_bytes(16000))
        self.assertEqual(result, struct.pack('<6h', 0, 1000, 2000, 3000, 4000, 5000))

    def test_reject_invalid_and_stereo(self):
        for data in (b'not audio', wav_bytes(16000, channels=2)):
            with self.assertRaises((ValueError, wave.Error, EOFError)):
                stt_pcm16(data)

    def test_declared_pcm_is_not_redecoded_or_resampled(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'voice.pcm'
            path.write_bytes(struct.pack('<3h', 1, -2, 3))
            self.assertEqual(stt_transport_audio(path), path.read_bytes())
            for invalid in (b'', b'1', wav_bytes(16000)):
                path.write_bytes(invalid)
                with self.assertRaises(ValueError):
                    stt_transport_audio(path)


class FaultTests(unittest.TestCase):
    def test_permanent_failure_is_scoped_and_observable(self):
        app = FastAPI()
        app.include_router(fault.router)
        a, b = 'a' * 32, 'b' * 32
        with TestClient(app) as api:
            for _ in range(4):
                response = api.post(f'/runtime-fault/{a}/v1/chat/completions', json={'stream': True})
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()['error']['code'], 'controlled_provider_unavailable')
            self.assertEqual(api.get(f'/runtime-fault/{a}/state').json()['calls'], 4)
            self.assertEqual(api.get(f'/runtime-fault/{b}/state').json()['calls'], 0)
            self.assertEqual(api.delete(f'/runtime-fault/{a}').status_code, 200)
            self.assertEqual(api.get(f'/runtime-fault/{a}/state').json()['calls'], 0)


class ChainTests(unittest.IsolatedAsyncioTestCase):
    async def test_tail_to_parent_resolution(self):
        meta = {'tail': {'status': 'SUCCESS', 'parent_id': 'forward', 'root_id': 'process'},
                'forward': {'status': 'SUCCESS', 'parent_id': 'process', 'root_id': 'process'},
                'process': {'status': 'SUCCESS', 'root_id': 'process'}}
        wait = AsyncMock(side_effect=lambda key: meta[key])
        with patch.object(chain, '_wait_terminal', wait):
            result = await chain._chain_stages('tail')
        self.assertEqual(result[0], 'process')
        self.assertEqual(result[2], 'forward')
        self.assertEqual([call.args[0] for call in wait.await_args_list], ['tail', 'forward', 'process'])

    async def test_reject_missing_parent_cycle_foreign_root_and_failure(self):
        for tail in ({'status': 'SUCCESS'}, {'status': 'SUCCESS', 'parent_id': 'tail'},
                     {'status': 'SUCCESS', 'parent_id': 'forward', 'root_id': 'foreign'},
                     {'status': 'FAILURE', 'parent_id': 'forward'}):
            meta = {'tail': tail, 'forward': {'status': 'SUCCESS', 'parent_id': 'process'},
                    'process': {'status': 'SUCCESS'}}
            with patch.object(chain, '_wait_terminal', AsyncMock(side_effect=lambda key: meta[key])):
                with self.assertRaises(AssertionError):
                    await chain._chain_stages('tail')
