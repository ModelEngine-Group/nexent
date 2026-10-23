# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Negative checks for test oracles; these do not count as deployed E2E runs."""

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI


ROOT = Path(__file__).resolve().parents[4]
AUTOMATION = ROOT / "test-e2e/infra/automation"
SERVICE = ROOT / "test-e2e/infra/environment/services/test-assets"
sys.path.insert(0, str(AUTOMATION))
sys.path.insert(0, str(SERVICE))

bridge = importlib.import_module("d4.tool_fastpath_client")
deployed = importlib.import_module("shared.tool_fastpath_deployed")
observation = importlib.import_module("shared.tool_fastpath_observation")


spec = importlib.util.spec_from_file_location("tfp_provider_under_test", SERVICE / "tool_fastpath_provider.py")
provider = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = provider
spec.loader.exec_module(provider)

NONCE = "a" * 32
OTHER = "b" * 32
CFG = {"config": {"marker": "TFP_RULES", "value": 7}, "skill_name": "tfp-verification"}
IDENTITY = SimpleNamespace(id="tenant_a_admin", user_id="owned-user", tenant_id="tenant-a", access_token="private")
KEY = f"workspace/{IDENTITY.user_id}/{'c' * 32}/outputs/tfp-{NONCE}.txt"
URL = "s3://bucket/" + KEY


def units(promoted):
    names = (
        ["read_skill_config", "run_skill_script", "upload_to_s3", "read_skill_config"]
        if promoted
        else ["read_skill_config"]
    )
    logs = json.dumps(CFG["config"]) + "\n"
    if promoted:
        logs += f"TFP_MIGRATED_{NONCE}\nTFP_DOCKER_{NONCE}_True\n"
    result = [{"type": "tool", "tool_name": name} for name in names]
    result += [{"type": "parse", "content": "real action"} for _ in range(3 if promoted else 1)]
    result += [{"type": "execution_logs", "content": logs}]
    result += [
        {
            "type": "final_answer",
            "content": f"TFP_{'PROMOTED' if promoted else 'FAST'}_{NONCE}"
            + (f"\n[tfp-{NONCE}.txt]({URL})" if promoted else ""),
        }
    ]
    if promoted:
        result += [
            {
                "type": "file_artifact",
                "content": {"artifacts": [{"object_name": KEY, "s3_url": URL, "filename": f"tfp-{NONCE}.txt"}]},
            }
        ]
    return result


def history(parts, status="completed"):
    return {
        "code": 0,
        "data": [{"conversation_id": "12", "message": [{"role": "assistant", "status": status, "message": parts}]}],
    }


def response(code=200, body=None, content=None):
    kwargs = {"content": content} if content is not None else {"json": body or {}}
    return httpx.Response(code, request=httpx.Request("GET", "http://fixture.invalid"), **kwargs)


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        provider.scenarios.clear()
        app = FastAPI()
        app.include_router(provider.router)
        self.api = httpx.AsyncClient(base_url="http://fixture.invalid", transport=httpx.ASGITransport(app=app))
        self.addAsyncCleanup(self.api.aclose)

    async def reset(self, nonce=NONCE, responses=None):
        result = await self.api.post(
            f"/tfp/{nonce}/reset", json={"responses": responses or ["<final_answer>OK</final_answer>"]}
        )
        self.assertEqual(result.status_code, 200)

    async def call(self, nonce=NONCE, **kwargs):
        body = {
            "stream": True,
            "max_tokens": 4096,
            "messages": [{"role": "system", "content": "TFP_AGENT_SCENARIO_" + nonce}],
            **kwargs,
        }
        return await self.api.post(f"/tfp/{nonce}/v1/chat/completions", json=body)

    async def test_health_and_same_budget_streaming_titles_do_not_consume_agent_turns(self):
        await self.reset()
        self.assertEqual(
            (await self.call(stream=False)).json()["choices"][0]["message"]["content"], "TFP verification"
        )
        title = await self.call(messages=[{"role": "system", "content": "Generate a title"}])
        self.assertIn("[DONE]", title.text)
        self.assertEqual(provider.scenarios[NONCE].calls, 0)
        actual = await self.call()
        self.assertIn("[DONE]", actual.text)
        self.assertEqual(provider.scenarios[NONCE].calls, 1)
        self.assertEqual((await self.call()).status_code, 409)

    async def test_nonces_are_isolated_and_deleting_one_preserves_the_other(self):
        await self.reset()
        await self.reset(OTHER)
        await self.call()
        self.assertEqual(provider.scenarios[OTHER].calls, 0)
        self.assertEqual((await self.api.delete(f"/tfp/{NONCE}")).status_code, 200)
        self.assertEqual((await self.call()).status_code, 404)
        self.assertEqual((await self.call(OTHER)).status_code, 200)

    async def test_final_link_requires_one_actual_upload_observation(self):
        await self.reset(responses=["<final_answer>{{TFP_ARTIFACT_URL}}</final_answer>"])
        self.assertEqual((await self.call()).status_code, 409)
        self.assertEqual(provider.scenarios[NONCE].calls, 0)
        messages = [
            {"role": "system", "content": "TFP_AGENT_SCENARIO_" + NONCE},
            {"role": "user", "content": "Execution logs: " + json.dumps({"s3_url": URL})},
        ]
        actual = await self.call(messages=messages)
        text = "".join(
            json.loads(line[6:])["choices"][0]["delta"].get("content", "")
            for line in actual.text.splitlines()
            if line.startswith("data: {")
        )
        self.assertEqual(text, f"<final_answer>{URL}</final_answer>")
        self.assertNotIn("{{TFP_ARTIFACT_URL}}", text)

    async def test_wrong_nonce_and_ambiguous_uploads_do_not_advance_turn(self):
        for observed in (URL.replace(NONCE, OTHER), URL + " " + URL.replace("bucket", "other")):
            await self.reset(responses=["{{TFP_ARTIFACT_URL}}"])
            messages = [
                {"role": "system", "content": "TFP_AGENT_SCENARIO_" + NONCE},
                {"role": "user", "content": observed},
            ]
            self.assertEqual((await self.call(messages=messages)).status_code, 409)
            self.assertEqual(provider.scenarios[NONCE].calls, 0)

    async def test_nonlocal_controls_are_rejected(self):
        app = FastAPI()
        app.include_router(provider.router)
        async with httpx.AsyncClient(
            base_url="http://fixture.invalid", transport=httpx.ASGITransport(app=app, client=("192.0.2.1", 12))
        ) as api:
            result = await api.post(f"/tfp/{NONCE}/reset", json={"responses": ["OK"]})
        self.assertEqual(result.status_code, 403)
        self.assertFalse(provider.scenarios)


class OracleTests(unittest.TestCase):
    def test_persisted_attachments_use_structured_metadata_and_preserve_scope(self):
        body = history(units(True)[:-1])
        body['data'][0]['message'][0]['minio_files'] = [
            {'object_name': KEY, 'url': URL, 'name': f'tfp-{NONCE}.txt'}]
        parts = deployed.history_units(body)
        self.assertEqual(deployed.artifact_objects(parts, IDENTITY, NONCE)[KEY]['s3_url'], URL)
        self.assertFalse(deployed.artifact_objects(parts, IDENTITY, OTHER))
        self.assertFalse(deployed.artifact_objects(parts, SimpleNamespace(user_id='outsider'), NONCE))
        self.assertFalse(deployed.artifact_objects(units(True)[:-1], IDENTITY, NONCE))

    def test_multiline_trace_answer_and_flattened_otel_backend_are_preserved(self):
        marker = "FINAL\n[report](s3://bucket/report)"
        self.assertTrue(observation.output_contains(marker, marker))
        self.assertFalse(observation.output_contains("FINAL", marker))
        observation.verify_warmups([{"name": "agent.sandbox.warmup", "endTime": "ended",
            "level": "DEFAULT", "metadata": {"attributes.sandbox.backend": "docker"}}], True)
        with self.assertRaises(AssertionError):
            observation.verify_warmups([{"name": "agent.sandbox.warmup", "endTime": "ended",
                "level": "DEFAULT", "metadata": {"attributes.sandbox.backend": "local"}}], True)

    def test_streamed_answer_requires_one_completion_and_matches_persisted_result(self):
        parts = units(False)
        answer = parts.pop()["content"]
        streamed = [*parts, *({"type": "final_answer", "content": chunk, "answer_phase": "delta", "step_id": "s"}
                              for chunk in (answer[:4], answer[4:])),
                    {"type": "final_answer", "content": "", "answer_phase": "complete", "step_id": "s"}]
        self.assertEqual(deployed.verify_result(streamed, CFG, NONCE, False),
                         deployed.verify_result(units(False), CFG, NONCE, False))
        for broken in (streamed[:-1], [*streamed, streamed[-1]], [*streamed, streamed[-2]]):
            with self.assertRaises(AssertionError):
                deployed.verify_result(broken, CFG, NONCE, False)

    def test_success_requires_exact_results_but_allows_json_key_order(self):
        for promoted in (False, True):
            parts = units(promoted)
            logs = next(part for part in parts if part["type"] == "execution_logs")
            logs["content"] = logs["content"].replace(json.dumps(CFG["config"]), '{"value": 7, "marker": "TFP_RULES"}')
            self.assertEqual(deployed.verify_result(parts, CFG, NONCE, promoted)["action_count"], 3 if promoted else 1)

    def test_omitted_reordered_duplicate_and_unexpected_tools_are_rejected(self):
        mutations = [
            lambda parts: parts.pop(0),
            lambda parts: parts.insert(0, deepcopy(parts[0])),
            lambda parts: parts.reverse(),
            lambda parts: parts.append({"type": "tool", "tool_name": "unapproved"}),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                parts = units(True)
                mutate(parts)
                with self.assertRaises(AssertionError):
                    deployed.verify_result(parts, CFG, NONCE, True)

    def test_fake_final_error_missing_action_and_cold_artifact_are_rejected(self):
        for extra in (
            {"type": "final_answer", "content": f"TFP_FAST_{NONCE}"},
            {"type": "error", "content": "failed"},
            {"type": "parse"},
            {"type": "file_artifact", "content": {"artifacts": []}},
        ):
            with self.subTest(extra=extra), self.assertRaises(AssertionError):
                deployed.verify_result([*units(False), extra], CFG, NONCE, False)
        parts = units(False)
        next(part for part in parts if part["type"] == "final_answer")["content"] += " extra"
        with self.assertRaises(AssertionError):
            deployed.verify_result(parts, CFG, NONCE, False)

    def test_missing_migration_local_fallback_and_wrong_config_are_rejected(self):
        for before, after in (
            (f"TFP_MIGRATED_{NONCE}", ""),
            (f"TFP_DOCKER_{NONCE}_True", f"TFP_DOCKER_{NONCE}_False"),
            ('"value": 7', '"value": 8'),
        ):
            parts = units(True)
            logs = next(part for part in parts if part["type"] == "execution_logs")
            logs["content"] = logs["content"].replace(before, after)
            with self.subTest(before=before), self.assertRaises(AssertionError):
                deployed.verify_result(parts, CFG, NONCE, True)

    def test_user_text_and_failed_or_duplicate_assistants_cannot_prove_a_success(self):
        body = history(units(False))
        body["data"][0]["message"][0]["role"] = "user"
        with self.assertRaises(AssertionError):
            deployed.history_units(body)
        for status in ("streaming", "failed", "stopped"):
            with self.subTest(status=status), self.assertRaises(AssertionError):
                deployed.history_units(history(units(False), status))
        body = history(units(False))
        body["data"][0]["message"].append(deepcopy(body["data"][0]["message"][0]))
        with self.assertRaises(AssertionError):
            deployed.history_units(body)

    def test_artifact_discovery_is_scoped_to_authenticated_user_and_nonce(self):
        self.assertEqual(list(deployed.artifact_objects(units(True), IDENTITY, NONCE)), [KEY])
        self.assertFalse(deployed.artifact_objects(units(True), IDENTITY, OTHER))
        self.assertFalse(deployed.artifact_objects(units(True), SimpleNamespace(user_id="outsider"), NONCE))
        parts = units(True)
        artifact = parts[-1]
        artifact.update(type="files", content=json.dumps({"file_uploads": artifact["content"]["artifacts"]}))
        self.assertEqual(list(deployed.artifact_objects(parts, IDENTITY, NONCE)), [KEY])
        self.assertFalse(deployed.artifact_objects(parts, IDENTITY, OTHER))
        with self.assertRaises(AssertionError):
            deployed.verify_result([*units(False), artifact], CFG, NONCE, False)

    def test_sandbox_activation_counts_and_reclamation_detect_leaks(self):
        observation.verify_sandbox_events([], False)
        observation.verify_sandbox_events(
            [{"action": "create", "id": "owned"}, {"action": "destroy", "id": "owned"}], True
        )
        broken = [
            ([{"action": "create", "id": "owned"}], True),
            ([{"action": "create", "id": "owned"}, {"action": "destroy", "id": "sibling"}], True),
            ([{"action": "create", "id": "owned"}, {"action": "destroy", "id": "owned"}], False),
            ([{"action": "create", "id": "owned"}] * 2, True),
            ([{"action": "destroy", "id": "sibling"}], False),
        ]
        for records, promoted in broken:
            with self.subTest(records=records), self.assertRaises(AssertionError):
                observation.verify_sandbox_events(records, promoted)

    def test_warmup_requires_complete_real_docker_metadata_and_nonempty_telemetry(self):
        warm = {
            "name": "agent.sandbox.warmup",
            "endTime": "ended",
            "level": "DEFAULT",
            "metadata": {"attributes": {"sandbox.backend": "docker"}},
        }
        observation.verify_warmups([{"name": "agent.run"}], False)
        observation.verify_warmups([warm], True)
        broken = [
            [],
            [warm, warm],
            [{**warm, "endTime": None}],
            [{**warm, "level": "ERROR"}],
            [{**warm, "metadata": {"sandbox.backend": "local"}}],
            [{**warm, "metadata": {"untrusted_text": '"sandbox.backend": "docker"'}}],
        ]
        for items in broken:
            with self.subTest(items=items), self.assertRaises(AssertionError):
                observation.verify_warmups(items, True)
        with self.assertRaises(AssertionError):
            observation.verify_warmups([], False)
        with self.assertRaises(AssertionError):
            observation.verify_warmups([warm], False)


class AsyncOracleTests(unittest.IsolatedAsyncioTestCase):
    async def test_v2_waits_for_delayed_warmup_indexing(self):
        agent = {'id': 'agent', 'traceId': 't', 'sessionId': '12', 'name': 'agent.run',
                 'endTime': 'ended', 'output': 'FINAL', 'parentObservationId': 'root'}
        root = {'id': 'root', 'traceId': 't', 'endTime': 'ended'}
        warm = {'id': 'warm', 'traceId': 't', 'name': 'agent.sandbox.warmup', 'endTime': 'ended'}
        with (patch.object(observation, 'observation_pages', AsyncMock(side_effect=[
                [agent], [root, agent], [agent], [root, agent, warm]])),
              patch.object(observation.asyncio, 'sleep', AsyncMock()) as sleep):
            result = await observation.trace_observations_v2(
                {'url': 'http://trace.invalid'}, ('a', 'b'), 12, 'FINAL', expected_warmups=1)
        self.assertEqual(result, [root, agent, warm])
        sleep.assert_awaited_once()

    async def test_v2_reads_child_pages_and_requires_completed_root(self):
        agent = {"id": "agent", "traceId": "t", "sessionId": "12", "name": "agent.run",
                 "endTime": "ended", "output": "FINAL", "parentObservationId": "root"}
        root = {"id": "root", "traceId": "t", "endTime": "ended", "parentObservationId": None}
        warm = {"id": "warm", "traceId": "t", "name": "agent.sandbox.warmup", "parentObservationId": "agent"}
        api = AsyncMock()
        api.get.side_effect = [
            response(body={"data": [agent], "meta": {}}),
            response(body={"data": [agent], "meta": {}}),  # Root not exported yet.
            response(body={"data": [agent], "meta": {}}),
            response(body={"data": [root, agent], "meta": {"cursor": "next"}}),
            response(body={"data": [warm], "meta": {}}),
        ]
        with patch.object(observation.httpx, "AsyncClient") as make, patch.object(observation.asyncio, "sleep", AsyncMock()):
            make.return_value.__aenter__.return_value = api
            result = await observation.trace_observations_v2({"url": "http://trace.invalid"}, ("a", "b"), 12, "FINAL")
        self.assertEqual(result, [root, agent, warm])
        self.assertEqual(api.get.call_args_list[-1].kwargs["params"]["cursor"], "next")

    async def test_v2_repeated_cursor_and_duplicate_observation_fail_closed(self):
        for pages in (
            [{"data": [{"id": "a"}], "meta": {"cursor": "same"}},
             {"data": [{"id": "b"}], "meta": {"cursor": "same"}}],
            [{"data": [{"id": "a"}], "meta": {"cursor": "next"}},
             {"data": [{"id": "a"}], "meta": {}}],
        ):
            api = AsyncMock()
            api.get.side_effect = [response(body=page) for page in pages]
            with self.assertRaises(AssertionError):
                await observation.observation_pages(api, {})

    async def test_artifact_requires_matching_final_link_bytes_and_cross_tenant_denial(self):
        outsider = SimpleNamespace(access_token="other", tenant_id="tenant-b")
        api = AsyncMock()
        api.get.return_value = response(403)
        expected = f"TFP_REPORT_{NONCE}:7\n".encode()
        with (
            patch.object(deployed, "register_asset"),
            patch.object(deployed, "client") as make_client,
            patch.object(deployed, "sign_in", AsyncMock(return_value=outsider)),
            patch.object(deployed, "download_artifact", AsyncMock(return_value=expected)) as download,
        ):
            make_client.return_value.__aenter__.return_value = api
            result = await deployed.verify_artifact(IDENTITY, units(True), CFG, NONCE, "TFP-D3-001")
            self.assertEqual(result["object_name"], KEY)
            download.return_value = b"wrong bytes"
            with self.assertRaises(AssertionError):
                await deployed.verify_artifact(IDENTITY, units(True), CFG, NONCE, "TFP-D3-001")
            download.return_value = expected
            api.get.return_value = response(200)
            with self.assertRaises(AssertionError):
                await deployed.verify_artifact(IDENTITY, units(True), CFG, NONCE, "TFP-D3-001")
            parts = units(True)
            next(part for part in parts if part["type"] == "final_answer")["content"] = URL.replace("bucket", "wrong")
            with self.assertRaises(AssertionError):
                await deployed.verify_artifact(IDENTITY, parts, CFG, NONCE, "TFP-D3-001")

    async def test_trace_pagination_empty_observations_and_unrelated_rows_are_rejected(self):
        cfg = {"langfuse": {"url": "http://trace.invalid", "public_key_env": "PUBLIC", "secret_key_env": "PRIVATE"}}
        api = AsyncMock()
        valid_trace = {"data": [{"id": "t", "sessionId": "12", "output": "FINAL"}], "meta": {"totalItems": 1}}
        variants = [
            ({**valid_trace, "meta": {"totalItems": 101}}, None),
            (valid_trace, {"data": [], "meta": {"totalItems": 0}}),
            (valid_trace, {"data": [{"traceId": "t"}], "meta": {"totalItems": 101}}),
            (valid_trace, {"data": [{"traceId": "sibling"}], "meta": {"totalItems": 1}}),
            ({"data": [{"id": "t", "sessionId": "other", "output": "FINAL"}]}, None),
        ]
        with (
            patch.object(observation, "load_secret_env", return_value={"PUBLIC": "public", "PRIVATE": "private"}),
            patch.object(observation.httpx, "AsyncClient") as make_client,
        ):
            make_client.return_value.__aenter__.return_value = api
            for traces, observations in variants:
                api.get.side_effect = [response(body=traces), response(body=observations)]
                with self.subTest(traces=traces, observations=observations), self.assertRaises(AssertionError):
                    await observation.trace_observations(cfg, 12, "FINAL")
            api.get.side_effect = [
                response(body=valid_trace),
                response(body={"data": [{"traceId": "t", "name": "agent.run"}], "meta": {"totalItems": 1}}),
            ]
            self.assertEqual(
                await observation.trace_observations(cfg, 12, "FINAL"), [{"traceId": "t", "name": "agent.run"}]
            )

    async def test_deployment_preflight_rejects_wrong_mount_scope_before_mutation(self):
        cfg = {"runtime_container": "fixture", "workspace_mount_id": "d" * 64}
        record = [
            {
                "State": {"Running": True},
                "Config": {
                    "Env": [
                        "NEXENT_SANDBOX_DEFAULT_LEVEL=docker",
                        "NEXENT_SANDBOX_DEFAULT_SCOPE=session",
                        "NEXENT_SANDBOX_WORKSPACE_MODE=bind",
                        "NEXENT_TOOL_FASTPATH_ENABLED=true",
                    ]
                },
            }
        ]
        with (
            patch.object(
                observation,
                "docker_command",
                side_effect=[json.dumps(record), json.dumps({"sources": {}, "mount_id": "sibling"})],
            ),
            patch.object(observation, "SOURCES", ()),
        ):
            with self.assertRaisesRegex(AssertionError, "scope differs"):
                observation.verify_deployment(cfg)

    async def test_stop_waits_for_terminal_history_and_checks_the_owned_id(self):
        api = AsyncMock()
        active = history(units(True), "streaming")
        api.get.side_effect = [response(body=active), response(body=history(units(True)))]
        with (
            patch.object(deployed, "client") as make_client,
            patch.object(deployed.asyncio, "sleep", AsyncMock()) as sleep,
        ):
            make_client.return_value.__aenter__.return_value = api
            self.assertEqual(await deployed.wait_history(IDENTITY, 12), history(units(True)))
            sleep.assert_awaited_once()
            with self.assertRaises(AssertionError):
                api.get.side_effect = [response(body=history(units(True)))]
                await deployed.wait_history(IDENTITY, 99)

    async def test_fixture_cleanup_failure_does_not_prevent_model_or_provider_cleanup(self):
        api = AsyncMock()
        api.request.return_value = response(500)
        api.post.return_value = response()
        fixture = {"nonce": NONCE, "agent_id": 7, "model_created": True, "display": "owned"}
        with (
            patch.object(deployed, "client") as make_client,
            patch.object(deployed, "mark_asset_state"),
            patch.object(deployed, "control", AsyncMock()) as control,
        ):
            make_client.return_value.__aenter__.return_value = api
            with self.assertRaises(RuntimeError):
                await deployed.cleanup_fixture(fixture, identity=IDENTITY)
            api.post.assert_awaited_once()
            control.assert_awaited_once_with(NONCE, "delete")

    async def test_auth_failure_still_attempts_provider_cleanup(self):
        with (
            patch.object(deployed, "sign_in", AsyncMock(side_effect=RuntimeError("private-body"))),
            patch.object(deployed, "control", AsyncMock()) as control,
        ):
            with self.assertRaises(RuntimeError) as caught:
                await deployed.cleanup_fixture({"nonce": NONCE})
            control.assert_awaited_once_with(NONCE, "delete")
            self.assertNotIn("private-body", str(caught.exception))

    async def test_object_delete_failure_still_attempts_conversation_delete(self):
        api = AsyncMock()
        api.get.return_value = response()
        api.delete.return_value = response(500)
        with (
            patch.object(deployed, "client") as make_client,
            patch.object(deployed, "wait_history", AsyncMock(return_value=history(units(True)))),
            patch.object(deployed, "delete_owned_conversation", AsyncMock()) as delete,
        ):
            make_client.return_value.__aenter__.return_value = api
            with self.assertRaises(RuntimeError):
                await deployed.cleanup_conversation(IDENTITY, 12, NONCE)
            delete.assert_awaited_once_with(IDENTITY, 12)

    async def test_browser_cleanup_attempts_all_owned_ids_and_fixture_after_failure(self):
        receipt = {"fixture": {"nonce": NONCE}, "runs": [{"conversation_id": 12}, {"conversation_id": 13}]}
        with (
            patch.object(bridge, "sign_in", AsyncMock(return_value=IDENTITY)),
            patch.object(
                bridge, "cleanup_conversation", AsyncMock(side_effect=[RuntimeError("private"), None])
            ) as cleanup,
            patch.object(bridge, "cleanup_fixture", AsyncMock()) as fixture_cleanup,
            patch.object(bridge, "save_receipt"),
        ):
            with self.assertRaises(RuntimeError) as caught:
                await bridge.cleanup_receipt(receipt)
            self.assertEqual(cleanup.await_count, 2)
            fixture_cleanup.assert_awaited_once()
            self.assertNotIn("cleaned", receipt["runs"][0])
            self.assertTrue(receipt["runs"][1]["cleaned"])
            self.assertNotIn("private", str(caught.exception))

    async def test_receipt_permissions_and_owned_id_checks(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"RESULT_DIR": directory}):
            bridge.save_receipt({"fixture": {"nonce": NONCE}, "config": CFG, "runs": []})
            if os.name != "nt":
                self.assertEqual(bridge.receipt_path().stat().st_mode & 0o777, 0o600)
            with self.assertRaises(AssertionError):
                await bridge.operate("inspect", conversation=99)
            with self.assertRaises(ValueError):
                await bridge.operate("record", conversation=-1)
