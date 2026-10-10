"""Verify API-054's assertions and ownership without contacting a provider."""

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import httpx

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "test-e2e/infra/automation"))
spec = importlib.util.spec_from_file_location("voice_model_case", ROOT / "test-e2e/cases/API-054/test.py")
case = importlib.util.module_from_spec(spec)
spec.loader.exec_module(case)


def response(data, status=200):
    return httpx.Response(status, json=data, request=httpx.Request("POST", "http://fixture.test"))


class VoiceModelConnectivityTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, *, saved_connected=True, invalid_connected=False,
                       persisted_status="available", cleanup_status=200):
        rows, calls, marks = [], [], []
        payload = {"model_name": "fixture-voice", "model_type": "tts", "model_factory": "dashscope",
                   "api_key": "fixture-credential", "access_token": None,
                   "display_name": "owned-fixture", "base_url": "wss://fixture.test/realtime"}

        async def fake_request(identity, method, path, **kwargs):
            calls.append((method, path, kwargs))
            if path == "/model/list":
                return response({"data": [dict(row) for row in rows]})
            if path == "/config/load_config":
                return response({"config": {"models": {"tts": {"id": "original"}}}})
            if path == "/model/temporary_healthcheck":
                body = kwargs["json"]
                if "model_type" not in body:
                    self.assertNotIn("api_key", body)
                    self.assertNotIn("access_token", body)
                    return response({"detail": "missing required model_type"}, 422)
                connected = True if body["api_key"] == payload["api_key"] else invalid_connected
                return response({"data": {"model_name": payload["model_name"], "connectivity": connected,
                                          **({} if connected else {"error": "invalid fixture credential"})}})
            if path == "/model/create":
                self.assertTrue(kwargs["json"]["skip_default_backfill"])
                row = {key: value for key, value in payload.items() if key not in {"api_key", "access_token"}}
                rows.append({**row, "connect_status": "detecting"})
                return response({"data": {"model_id": 123}})
            if path == "/model/healthcheck":
                self.assertNotIn("json", kwargs)
                self.assertEqual(kwargs["params"], {"display_name": payload["display_name"], "model_type": "tts"})
                rows[0]["connect_status"] = persisted_status
                return response({"data": {"model_name": payload["model_name"], "connectivity": saved_connected}})
            if path == "/model/delete":
                if cleanup_status == 200:
                    rows.clear()
                return response({}, cleanup_status)
            self.fail(f"Unexpected endpoint: {path}")

        with patch.object(case, "model_request", return_value=payload), \
                patch.object(case, "request", side_effect=fake_request), \
                patch.object(case, "register_asset") as register, \
                patch.object(case, "mark_asset_state", side_effect=lambda *args, **kwargs: marks.append(args)):
            try:
                await case.exercise_voice_model(SimpleNamespace(id="fixture", access_token="fixture"), "tts")
            finally:
                self.calls, self.rows, self.marks = calls, rows, marks
                self.registered = register.called

    async def test_current_routes_negative_config_and_saved_health_with_cleanup(self):
        await self.exercise()
        self.assertTrue(self.registered)
        self.assertEqual(self.rows, [])
        self.assertEqual(self.marks[-1][-1], "DELETED")
        self.assertEqual(sum(path == "/model/temporary_healthcheck" for _, path, _ in self.calls), 3)
        self.assertFalse(any(path.startswith("/voice/") for _, path, _ in self.calls))

    async def test_failed_saved_health_is_not_hidden_by_successful_temporary_probe(self):
        with self.assertRaisesRegex(AssertionError, "Expected connectivity=True"):
            await self.exercise(saved_connected=False)
        self.assertEqual(self.rows, [])
        self.assertEqual(self.marks[-1][-1], "DELETED")

    async def test_wrong_persisted_status_cannot_pass(self):
        with self.assertRaisesRegex(AssertionError, "persist available status"):
            await self.exercise(persisted_status="unavailable")
        self.assertEqual(self.rows, [])

    async def test_invalid_credential_success_is_detected_before_creating_model(self):
        with self.assertRaisesRegex(AssertionError, "Expected connectivity=False"):
            await self.exercise(invalid_connected=True)
        self.assertFalse(any(path == "/model/create" for _, path, _ in self.calls))

    async def test_cleanup_failure_is_not_a_pass(self):
        with self.assertRaisesRegex(AssertionError, "cleanup failed"):
            await self.exercise(cleanup_status=500)
        self.assertEqual(self.marks[-1][-1], "ORPHANED")

    async def test_both_capabilities_are_attempted_without_erasing_first_failure(self):
        with patch.object(case, "exercise_voice_model", new=AsyncMock(side_effect=[AssertionError("failed"), None])) as exercise:
            with self.assertRaisesRegex(AssertionError, "stt: failed"):
                await case.test_configured_voice_model_connectivity("fixture")
        self.assertEqual([call.args[1] for call in exercise.call_args_list], ["stt", "tts"])

    def test_wrong_model_http_error_and_missing_diagnostics_cannot_pass(self):
        for body, status, connected in [
            ({"data": {"model_name": "other", "connectivity": True}}, 200, True),
            ({"data": {"model_name": "fixture", "connectivity": True}}, 503, True),
            ({"data": {"model_name": "fixture", "connectivity": False}}, 200, False),
        ]:
            with self.subTest(body=body), self.assertRaises(AssertionError):
                case.assert_probe(response(body, status), connected=connected, model_name="fixture")
