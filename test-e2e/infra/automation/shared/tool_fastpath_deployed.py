# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Owned HTTP fixtures and assertions for deployed TFP D3/D4 acceptance."""

import asyncio
import json
import os
import re
import uuid
from pathlib import Path
from urllib.parse import quote

import httpx
from jsonschema import Draft202012Validator, FormatChecker

from shared.asset_registry import AssetDependencyError, mark_asset_state, register_asset
from shared.auth import sign_in
from shared.config import controlled_asset_url
from shared.factories.conversation import delete_owned_conversation
from shared.http import MODEL_TIMEOUT, assert_status, client
from shared.tool_fastpath_observation import verify_deployment, verify_trace_access


def fixture_config():
    path = os.environ.get("NEXENT_TFP_FIXTURE")
    if not path or not Path(path).is_file():
        raise AssetDependencyError(
            "deployment", "tfp_fixture", detail="NEXENT_TFP_FIXTURE must name a private deployed fixture"
        )
    schema = json.loads(Path(__file__).with_name("tool_fastpath_fixture.schema.json").read_text())
    cfg = json.loads(Path(path).read_text())
    if not Draft202012Validator(schema, format_checker=FormatChecker()).is_valid(cfg):
        raise ValueError("Private TFP fixture does not match its maintained schema")
    return cfg


async def control(nonce, operation, *, responses=None):
    local = os.environ.get("NEXENT_TEST_ASSETS_LOCAL_URL", "").rstrip("/")
    if not local:
        raise AssetDependencyError(
            "services", "tfp_provider", detail="Runner-owned controlled HTTP service is required"
        )
    if not re.fullmatch(r"[a-f0-9]{32}", nonce):
        raise ValueError("Invalid TFP nonce")
    async with httpx.AsyncClient(base_url=local, timeout=10, trust_env=False) as api:
        path = "/tfp/" + nonce
        if operation == "reset":
            response = await api.post(path + "/reset", json={"responses": responses})
        elif operation == "delete":
            response = await api.delete(path)
        elif operation == "state":
            response = await api.get(path + "/state")
        else:
            raise ValueError("Unknown TFP operation")
    assert_status(response, (200, 404) if operation == "delete" else 200)
    return response.json()


def responses_for(cfg, nonce, promoted):
    skill = json.dumps(cfg["skill_name"])
    action = (
        f"raw = read_skill_config(skill_name={skill})\nimport json as j\nsaved = j.loads(raw)\nprint(j.dumps(saved))"
    )
    responses = ["<code>" + action + "</code>"]
    if promoted:
        action = (
            "import pathlib\n"
            f"assert saved == {cfg['config']!r}\n"
            f"assert j.loads(j.dumps(saved)) == {cfg['config']!r}\n"
            f"print('TFP_MIGRATED_{nonce}')\n"
            f"print('TFP_DOCKER_{nonce}_' + str(pathlib.Path('/.dockerenv').exists()))\n"
            f"script_result = run_skill_script(skill_name={skill}, script_path='scripts/report.py', "
            f"params='--nonce {nonce} --value ' + str(saved['value']))\nprint(script_result)\n"
            f"uploaded = upload_to_s3(file_path='tfp-{nonce}.txt')\nprint(uploaded)"
        )
        responses.append("<code>" + action + "</code>")
        responses.append(f"<code>after = read_skill_config(skill_name={skill})\nprint(after)</code>")
    mode = "PROMOTED" if promoted else "FAST"
    artifact_link = f"\n[tfp-{nonce}.txt]({{{{TFP_ARTIFACT_URL}}}})" if promoted else ""
    responses.append(f"<final_answer>TFP_{mode}_{nonce}{artifact_link}</final_answer>")
    return responses


async def setup(case_id):
    cfg = fixture_config()
    # Preflight must precede every product mutation.
    fingerprints = verify_deployment(cfg)
    await verify_trace_access(cfg)
    controlled_asset_url()
    identity = await sign_in("tenant_a_admin")
    nonce = uuid.uuid4().hex
    fixture = {
        "nonce": nonce,
        "display": "tfp_" + nonce,
        "agent_id": None,
        "model_created": False,
        "fingerprints": fingerprints,
    }
    try:
        await control(nonce, "reset", responses=["<final_answer>TFP_READY</final_answer>"])
        async with client("config", token=identity.access_token) as api:
            skill = await api.get("/skills/" + cfg["skill_name"])
            assert_status(skill, 200)
            assert int(skill.json()["skill_id"]) == cfg["skill_id"], (
                "Configured skill identity differs from deployment"
            )
            created = await api.post(
                "/model/create",
                json={
                    "model_factory": "OpenAI-API-Compatible",
                    "model_name": "tfp-controlled",
                    "model_type": "llm",
                    "api_key": nonce,
                    "base_url": controlled_asset_url(f"/tfp/{nonce}/v1"),
                    "display_name": fixture["display"],
                    "max_tokens": 4096,
                },
            )
            assert_status(created, 200)
            fixture["model_created"] = True
            register_asset(
                "owned_models",
                fixture["display"],
                fixture["display"],
                owner_case_id=case_id,
                cleanup={
                    "service": "config",
                    "identity": identity.id,
                    "method": "POST",
                    "path": "/model/delete",
                    "params": {"display_name": fixture["display"]},
                    "allowed_statuses": [200, 404],
                },
            )
            catalog = await api.get("/model/list")
            assert_status(catalog, 200)
            rows = catalog.json()
            if isinstance(rows, dict):
                rows = rows.get("data") or rows.get("models") or []
            matches = [row for row in rows if row.get("display_name") == fixture["display"]]
            assert len(matches) == 1
            model_id = int(matches[0].get("model_id") or matches[0]["id"])
            health = await api.post(
                "/model/healthcheck", params={"display_name": fixture["display"], "model_type": "llm"}
            )
            assert_status(health, 200)
            health_body = health.json()
            assert health_body.get("data", health_body).get("connectivity") is True
            agent = await api.post(
                "/agent/update",
                json={
                    "name": fixture["display"],
                    "display_name": fixture["display"],
                    "description": "Owned TFP fixture",
                    "business_description": "Deferred executor acceptance",
                    "max_steps": 5,
                    "requested_output_tokens": 4096,
                    "prompt": "TFP_AGENT_SCENARIO_" + nonce,
                    "provide_run_summary": False,
                    "model_ids": [model_id],
                    "enabled_tool_ids": [],
                    "enabled_skill_ids": [cfg["skill_id"]],
                    "skill_instances": [
                        {"skill_id": cfg["skill_id"], "enabled": True, "config_values": cfg["config"]}
                    ],
                    "enabled": True,
                    "version_no": 0,
                    "enable_protocol_repair_retry": True,
                },
            )
            assert_status(agent, 200)
            fixture["agent_id"] = int(agent.json()["agent_id"])
            register_asset(
                "owned_agents",
                str(fixture["agent_id"]),
                fixture["agent_id"],
                owner_case_id=case_id,
                cleanup={
                    "service": "config",
                    "identity": identity.id,
                    "method": "DELETE",
                    "path": "/agent",
                    "json": {"agent_id": fixture["agent_id"]},
                    "allowed_statuses": [200, 404],
                },
            )
            assert_status(await api.put(f"/agent/clear_new/{fixture['agent_id']}"), 200)
            assert_status(
                await api.post(
                    f"/agent/{fixture['agent_id']}/publish",
                    json={"version_name": "tfp-test", "release_note": "Owned TFP fixture"},
                ),
                200,
            )
        return fixture
    except BaseException as primary:
        try:
            await cleanup_fixture(fixture, identity=identity)
        except Exception:
            primary.add_note("Owned TFP setup cleanup failed; inspect asset journal")
        raise


async def cleanup_fixture(fixture, *, identity=None):
    errors = []
    try:
        identity = identity or await sign_in("tenant_a_admin")
        async with client("config", token=identity.access_token) as api:
            if fixture.get("agent_id"):
                try:
                    response = await api.request("DELETE", "/agent", json={"agent_id": fixture["agent_id"]})
                    assert_status(response, (200, 404))
                    mark_asset_state("owned_agents", str(fixture["agent_id"]), "DELETED")
                except Exception as error:
                    errors.append(type(error).__name__)
            if fixture.get("model_created"):
                try:
                    response = await api.post("/model/delete", params={"display_name": fixture["display"]})
                    assert_status(response, (200, 404))
                    mark_asset_state("owned_models", fixture["display"], "DELETED")
                except Exception as error:
                    errors.append(type(error).__name__)
    except Exception as error:
        errors.append(type(error).__name__)
    try:
        await control(fixture["nonce"], "delete")
    except Exception as error:
        errors.append(type(error).__name__)
    if errors:
        raise RuntimeError("Owned TFP fixture cleanup failed: " + ", ".join(errors))


def history_units(body):
    assert body.get("code") == 0 and len(body.get("data", [])) == 1, "Owned history is unavailable"
    assistants = [
        message
        for row in body.get("data", [])
        for message in row.get("message", [])
        if message.get("role") == "assistant"
    ]
    assert len(assistants) == 1 and assistants[0].get("status") == "completed", "Owned run did not complete"
    return [unit for message in assistants for unit in message.get("message", []) if isinstance(unit, dict)]


def verify_result(units, cfg, nonce, promoted):
    final = f"TFP_{'PROMOTED' if promoted else 'FAST'}_{nonce}"
    answers = [unit.get("content") for unit in units if unit.get("type") == "final_answer"]
    assert len(answers) == 1
    if promoted:
        pattern = rf"{final}\n\[tfp-{nonce}\.txt\]\(s3://[^\s)]+/outputs/tfp-{nonce}\.txt\)"
        assert re.fullmatch(pattern, answers[0]), "Final answer must link the actual uploaded report"
    else:
        assert answers == [final]
    assert not any(unit.get("type") == "error" for unit in units), "The real Agent run failed"
    tools = [unit.get("tool_name") for unit in units if unit.get("type") in {"tool", "tool-call"}]
    assert tools.count("read_skill_config") == (2 if promoted else 1), "Tool invocation was omitted or replayed"
    assert tools.count("run_skill_script") == int(promoted)
    assert tools.count("upload_to_s3") == int(promoted)
    assert tools == (
        ["read_skill_config", "run_skill_script", "upload_to_s3", "read_skill_config"]
        if promoted
        else ["read_skill_config"]
    ), "Unexpected or reordered tool call"
    assert sum(unit.get("type") == "parse" for unit in units) == (3 if promoted else 1)
    logs = "\n".join(str(unit.get("content", "")) for unit in units if unit.get("type") == "execution_logs")
    printed = []
    for line in logs.splitlines():
        try:
            printed.append(json.loads(line))
        except ValueError:
            continue
    assert cfg["config"] in printed, "The real official configuration differs from the fixture"
    if not promoted:
        assert not any(unit.get("type") in {"file_artifact", "skill_artifact"} for unit in units)
    if promoted:
        assert "TFP_MIGRATED_" + nonce in logs, "Saved values or JSON aliases did not survive promotion"
        assert "TFP_DOCKER_" + nonce + "_True" in logs, "Local fallback cannot satisfy real Docker acceptance"
    return {"final": answers[0], "tool_names": tools, "action_count": 3 if promoted else 1}


def artifact_objects(units, identity, nonce):
    found = {}
    expected = "tfp-" + nonce + ".txt"
    for unit in units:
        if unit.get("type") != "file_artifact":
            continue
        content = unit.get("content")
        if isinstance(content, str):
            content = json.loads(content)
        for artifact in (content or {}).get("artifacts", []):
            key = artifact.get("object_name", "")
            pattern = rf"workspace/{re.escape(identity.user_id)}/[a-f0-9]{{32}}/outputs/{re.escape(expected)}"
            if re.fullmatch(pattern, key):
                found[key] = artifact
    return found


async def download_artifact(identity, object_name):
    async with client("config", token=identity.access_token) as api:
        response = await api.get("/file/download/" + quote(object_name, safe="/"), params={"download": "stream"})
    assert_status(response, 200)
    return response.content


async def verify_artifact(identity, units, cfg, nonce, case_id):
    objects = artifact_objects(units, identity, nonce)
    assert len(objects) == 1, "The run must publish exactly one owned report object"
    key, artifact = next(iter(objects.items()))
    final = next(unit["content"] for unit in units if unit.get("type") == "final_answer")
    assert artifact["s3_url"] in final, "The final download link differs from the published artifact"
    register_asset(
        "owned_tfp_objects",
        key,
        key,
        owner_case_id=case_id,
        cleanup={
            "service": "config",
            "identity": identity.id,
            "method": "DELETE",
            "path": "/file/storage/" + quote(key, safe="/"),
            "allowed_statuses": [200, 404],
        },
    )
    expected = f"TFP_REPORT_{nonce}:{cfg['config']['value']}\n"
    assert await download_artifact(identity, key) == expected.encode(), "Report bytes do not match the migrated value"
    outsider = await sign_in("tenant_b_user")
    assert outsider.tenant_id != identity.tenant_id, "The denial check requires a different tenant"
    async with client("config", token=outsider.access_token) as api:
        denied = await api.get("/file/download/" + quote(key, safe="/"), params={"download": "stream"})
    assert_status(denied, (403, 404))
    return {"object_name": key, "filename": artifact["filename"], "expected_text": expected}


async def wait_history(identity, conversation_id, *, successful=True, timeout=60):
    """Observe terminal persistence before reading artifacts or deleting a run."""
    async with asyncio.timeout(timeout):
        async with client("runtime", token=identity.access_token) as api:
            while True:
                response = await api.get(f"/conversation/{conversation_id}")
                if not successful and response.status_code == 404:
                    return {"data": []}
                assert_status(response, 200)
                body = response.json()
                if not successful and body.get("code") == 0 and body.get("data") == []:
                    return body
                assert body.get("code") == 0 and len(body.get("data", [])) == 1
                row = body["data"][0]
                assert str(row["conversation_id"]) == str(conversation_id)
                assistants = [message for message in row.get("message", []) if message.get("role") == "assistant"]
                streaming = row.get("streaming_message", {}).get("status") == "streaming"
                terminal = not assistants or assistants[-1].get("status") in {"completed", "stopped", "failed"}
                if not streaming and terminal:
                    if successful:
                        history_units(body)
                    return body
                await asyncio.sleep(0.5)


async def cleanup_conversation(identity, conversation_id, nonce):
    errors = []
    objects = {}
    try:
        async with client("runtime", token=identity.access_token) as api:
            # Stop this conversation only; do not affect sibling runs.
            stopped = await api.get(f"/agent/stop/{conversation_id}")
            assert_status(stopped, 200)
    except Exception as error:
        errors.append(type(error).__name__)
    try:
        history = await wait_history(identity, conversation_id, successful=False)
        units = [
            unit
            for row in history["data"]
            for message in row.get("message", [])
            if message.get("role") == "assistant"
            for unit in message.get("message", [])
            if isinstance(unit, dict)
        ]
        objects = artifact_objects(units, identity, nonce)
    except Exception as error:
        errors.append(type(error).__name__)
    try:
        async with client("config", token=identity.access_token) as api:
            for key in objects:
                try:
                    path = quote(key, safe="/")
                    response = await api.delete("/file/storage/" + path)
                    assert_status(response, (200, 404))
                    absent = await api.get("/file/download/" + path, params={"download": "stream"})
                    assert_status(absent, 404)
                    mark_asset_state("owned_tfp_objects", key, "DELETED")
                except Exception as error:
                    errors.append(type(error).__name__)
    except Exception as error:
        errors.append(type(error).__name__)
    try:
        await delete_owned_conversation(identity, conversation_id)
        async with client("runtime", token=identity.access_token) as api:
            absent = await api.get(f"/conversation/{conversation_id}")
        assert absent.status_code == 404 or (absent.status_code == 200 and absent.json().get("data") == [])
        mark_asset_state("owned_conversations", str(conversation_id), "DELETED")
    except Exception as error:
        errors.append(type(error).__name__)
    if errors:
        raise RuntimeError("Owned TFP run cleanup failed: " + ", ".join(errors))


async def run_agent(identity, fixture, conversation_id):
    events = []
    async with client("runtime", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
        async with api.stream(
            "POST",
            "/agent/run",
            json={
                "query": "Execute the controlled TFP verification and finish.",
                "agent_id": fixture["agent_id"],
                "conversation_id": conversation_id,
                "history": [],
                "is_debug": False,
            },
        ) as response:
            assert_status(response, 200)
            async for line in response.aiter_lines():
                if line.startswith("data:") and line[5:].strip() != "[DONE]":
                    events.append(json.loads(line[5:]))
    return events
