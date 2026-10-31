# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Own all live fixtures and retain sanitized Docker/A2A integration evidence."""

import hashlib
import json
import os
import secrets
import subprocess
import tarfile
from pathlib import Path

import pytest

from shared.auth import sign_in
from shared.config import model_by_type, repo_root
from shared.http import assert_status, client


def command(argv, **kwargs):
    result = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", timeout=120, **kwargs)
    assert result.returncode == 0, f"Infrastructure command failed: {argv[0:3]}; {result.stderr[:300]}"
    return result.stdout.strip()


def data(response):
    assert_status(response, 200)
    payload = response.json()
    return payload.get("data", payload)


@pytest.mark.case_id("AGENT-CALLABLE-D3-001")
@pytest.mark.stage("D3")
@pytest.mark.asyncio
async def test_current_source_real_docker_a2a_and_legacy_callable():
    repo = repo_root()
    evidence = Path(os.environ["RESULT_DIR"]) / "live-callable"
    evidence.mkdir(parents=True, exist_ok=True)
    nonce = secrets.token_hex(6)
    runtime = "nexent-runtime"
    staged = f"/tmp/nexent-callable-{nonce}"
    archive = evidence / "current-source.tar.gz"
    command(["docker", "inspect", "--format", "{{.State.Running}}", runtime])
    tracked = command(["git", "ls-files", "sdk/nexent", "backend"], cwd=repo).splitlines()
    tracked.append("sdk/nexent/core/agent_names.py")
    fingerprints = {}
    with tarfile.open(archive, "w:gz") as bundle:
        for relative in sorted(set(tracked)):
            source = repo / relative
            if source.is_file():
                bundle.add(source, arcname=relative, recursive=False)
        bundle.add(Path(__file__).with_name("runtime_probe.py"), arcname="case/runtime_probe.py")
        bundle.add(repo / "test-e2e/infra/automation/shared/final_answers.py", arcname="case/final_answers.py")
    for relative in ["sdk/nexent/core/agent_names.py", "sdk/nexent/core/agents/a2a_agent_proxy.py",
                     "sdk/nexent/core/agents/nexent_agent.py", "sdk/nexent/core/agents/sandbox.py"]:
        fingerprints[relative] = hashlib.sha256((repo / relative).read_bytes()).hexdigest()
    command(["docker", "cp", str(archive), f"{runtime}:{staged}.tar.gz"])
    command(["docker", "exec", runtime, "python", "-c",
             "import pathlib,sys,tarfile; p=pathlib.Path(sys.argv[1]); p.mkdir(); "
             "tarfile.open(str(p)+'.tar.gz').extractall(p,filter='data')", staged])

    owned_agents, owned_external, owned_key = [], [], None
    cleanup, result = [], None
    identity = await sign_in("tenant_a_admin")

    def journal():
        (evidence / "owned-resources.json").write_text(json.dumps({
            "agents": owned_agents, "external": owned_external, "key": owned_key, "staged": staged,
        }, indent=2), encoding="utf-8")

    journal()
    try:
        async with client("config", token=identity.access_token, timeout=120) as api:
            rows = data(await api.get("/model/list"))
            if isinstance(rows, dict):
                rows = rows.get("models") or rows.get("items") or []
            candidates = []
            for category in ("vlm", "llm"):
                candidates.extend(reversed(str(model_by_type(category)["model"]).split(",")))
            selected = next(row for name in candidates for row in rows
                            if row.get("model_type") == "llm"
                            and name.strip() in (row.get("display_name"), row.get("model_name")))
            keys = data(await api.get("/user/tokens", params={"user_id": identity.user_id}))
            if keys:
                assert keys[0].get("can_copy"), "Existing test key must be readable without rotation"
                access_key = keys[0]["access_key"]
            else:
                created = data(await api.post("/user/tokens"))
                owned_key, access_key = created["token_id"], created["access_key"]
                journal()
            peers = []
            for index, display in enumerate(["parallel_probe_a", f"probe-agent-{nonce}"]):
                marker = f"PEER_ONLY_{index}_{secrets.token_hex(8)}"
                created = data(await api.post("/agent/update", json={
                    "name": f"callable_peer_{index}_{nonce}", "display_name": f"Live callable peer {index} {nonce}",
                    "description": "Owned live A2A callable regression peer", "author": "Regression",
                    "model_ids": [selected["model_id"]], "max_steps": 3, "is_a2a": True,
                    "allow_chat_metadata": True,
                    "prompt": f"Only respond with <final_answer>{marker}| followed by the exact user task text, then </final_answer>. Do not use tools.",
                    "enable_protocol_repair_retry": True,
                }))
                agent_id = int(created["agent_id"])
                owned_agents.append(agent_id)
                journal()
                published = data(await api.post(f"/agent/{agent_id}/publish", json={
                    "version_name": f"live-{nonce}", "release_note": "Owned Docker/A2A regression",
                }))
                endpoint = published["a2a_agent"]["endpoint_id"]
                internal_base = f"http://nexent-northbound:5013/nb/a2a/{endpoint}"
                data(await api.put(f"/a2a/management/agents/{agent_id}/settings", json={
                    "is_enabled": True, "card_overrides": {
                        "name": display,
                        "supportedInterfaces": [
                            {"protocolBinding": "JSONRPC", "url": internal_base + "/v1", "protocolVersion": "1.0"},
                            {"protocolBinding": "HTTP+JSON", "url": internal_base, "protocolVersion": "1.0"},
                        ],
                    },
                }))
                source_url = f"http://nexent-northbound:5013/nb/a2a/{endpoint}/.well-known/agent-card.json"
                external = data(await api.post("/a2a/client/discover/url", json={"url": source_url}))
                external_id = int(external.get("id") or external["external_agent_id"])
                owned_external.append(external_id)
                journal()
                assert external["name"] == display, "Original Card name was not preserved by real discovery"
                peers.append({"agent_id": agent_id, "external_id": external_id, "name": display,
                              "agent_url": external["agent_url"], "protocol_type": external["protocol_type"],
                              "endpoint": endpoint, "version": published["version_no"], "marker": marker})
            (evidence / "peers.json").write_text(json.dumps(peers, indent=2), encoding="utf-8")
            payload = {"source_root": staged, "fingerprints": fingerprints, "tenant_id": identity.tenant_id,
                       "user_id": identity.user_id, "model_name": selected["display_name"],
                       "access_key": access_key, "peers": peers, "task": f"CHECK_{nonce}"}
            process = subprocess.run([
                "docker", "exec", "-i", "-e", f"PYTHONPATH={staged}/sdk:{staged}/backend",
                runtime, "python", f"{staged}/case/runtime_probe.py",
            ], input=json.dumps(payload), capture_output=True, text=True, encoding="utf-8", timeout=1200)
            output = [line[len("LIVE_RESULT:"):] for line in process.stdout.splitlines() if line.startswith("LIVE_RESULT:")]
            assert output, f"Runtime probe did not produce a receipt (exit={process.returncode})"
            result = json.loads(output[-1])
            (evidence / "runtime-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            assert process.returncode == 0 and result["status"] == "PASS", result
            assert [item["scenario"] for item in result["scenarios"]] == ["directory", "legacy", "alias"]
            assert result["aliases"]["parallel_probe_a"] == "parallel_probe_a"
            assert result["sandbox_cleanup"] == "PASS"
    finally:
        async with client("config", token=identity.access_token) as api:
            for external_id in reversed(owned_external):
                deleted = await api.delete(f"/a2a/client/agents/{external_id}")
                cleanup.append({"kind": "external", "id": external_id, "status": deleted.status_code})
                assert_status(deleted, (200, 404))
                assert_status(await api.get(f"/a2a/client/agents/{external_id}"), 404)
            for agent_id in reversed(owned_agents):
                disabled = await api.post(f"/a2a/management/agents/{agent_id}/disable")
                assert_status(disabled, (200, 404))
                registration = await api.get(f"/a2a/management/agents/{agent_id}/settings")
                assert_status(registration, (200, 404))
                assert registration.status_code == 404 or registration.json()["data"]["is_enabled"] is False
                cleanup.append({"kind": "peer_endpoint", "id": agent_id, "status": "disabled"})
                deleted = await api.request("DELETE", "/agent", json={"agent_id": agent_id})
                cleanup.append({"kind": "peer", "id": agent_id, "status": deleted.status_code})
                assert_status(deleted, (200, 404))
                assert_status(await api.post("/agent/search_info", json={"agent_id": agent_id, "version_no": 0}), 404)
            if owned_key is not None:
                deleted = await api.delete(f"/user/tokens/{owned_key}")
                cleanup.append({"kind": "key", "status": deleted.status_code})
                assert_status(deleted, (200, 404))
        command(["docker", "exec", runtime, "python", "-c",
                 "import pathlib,sys,shutil; p=pathlib.Path(sys.argv[1]).resolve(); "
                 "assert p.parent==pathlib.Path('/tmp') and p.name.startswith('nexent-callable-'); "
                 "shutil.rmtree(p); pathlib.Path(str(p)+'.tar.gz').unlink(); assert not p.exists()", staged])
        cleanup.append({"kind": "staged_sources", "status": "removed"})
        (evidence / "cleanup.json").write_text(json.dumps(cleanup, indent=2), encoding="utf-8")
