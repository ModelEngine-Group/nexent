# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""FAF-D3-001: exercise the deployed Agent with its configured real model."""

import argparse
import json
import os
import time
from pathlib import Path

import requests
import pytest

from shared.final_answers import final_answer_text


def session(base):
    client = requests.Session()
    response = client.post(base + "/api/user/signin", json={
        "email": os.environ["NEXENT_TEST_EMAIL"], "password": os.environ["NEXENT_TEST_PASSWORD"]}, timeout=30)
    response.raise_for_status()
    data = response.json().get("data", {})
    token = (data.get("session") or {}).get("access_token")
    if token:
        client.headers["Authorization"] = "Bearer " + token
    return client


def api(client, base, method, path, **kwargs):
    response = client.request(method, base + "/api" + path, timeout=60, **kwargs)
    response.raise_for_status()
    return response.json()


def assert_evidence(scenario, events, detail):
    """Assert exact stream roles and their durable history projection."""
    answers = [event for event in events if event.get("type") == "final_answer"]
    assert not any(event.get("type") == "error" for event in events)
    expected = {"pure": "FAF-PURE-OK", "mixed": "FAF-MIXED-OK", "subagent": "FAF-PARENT-OK"}[scenario]
    assert final_answer_text(events) == expected
    units = []
    for message in detail["data"][0]["message"]:
        if message["role"] != "assistant":
            continue
        assert message["status"] == "completed"
        content = message["message"]
        units.extend(json.loads(content) if isinstance(content, str) else content)
    assert [unit["content"] for unit in units if unit["type"] == "final_answer" and not unit.get("invocation_id")] == [expected]
    if scenario == "pure":
        if any(unit['type'] == 'model_output_deep_thinking' and str(unit.get('content') or '').strip() for unit in units):
            from shared.asset_registry import AssetDependencyError
            raise AssetDependencyError('models', 'llm', consumer_case_id='FAF-D3-001',
                detail='Configured real provider emitted genuine deep reasoning; pure-answer fixture was not obtained. '
                       'Preserve deep reasoning and rerun with a provider supporting the requested non-reasoning mode.')
        assert not any(unit["type"] in {"step_count", "model_output_thinking", "model_output_deep_thinking"} for unit in units)
    elif scenario == "mixed":
        assert any(unit["type"] == "step_count" for unit in units)
        assert "".join(unit["content"] for unit in units if unit["type"] == "model_output_thinking") == "检查已完成。\n"
    else:
        children = [event["invocation_id"] for event in events if event.get("type") == "subagent_start"]
        assert len(children) == 1, "A real child invocation is required"
        child = children[0]
        assert any(event.get("type") == "subagent_end" and event.get("invocation_id") == child for event in events)
        assert final_answer_text(events, invocation_id=child) == "FAF-CHILD-OK"
        assert [unit["content"] for unit in units if unit["type"] == "final_answer" and unit.get("invocation_id") == child] == ["FAF-CHILD-OK"]
    return {"scenario": scenario, "answer": expected, "result": "PASS", "persisted_answers": len([u for u in units if u["type"] == "final_answer"])}


@pytest.mark.case_id('FAF-D3-001')
@pytest.mark.stage('D3')
@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['mixed', 'pure', 'subagent'])
async def test_final_answer_runtime(tenant_a_admin, kind):
    from shared.case_evidence import write_case_evidence, read_sse_with_evidence
    from shared.faf import prepare_faf_agents, cleanup_faf_agents
    from shared.factories.conversation import owned_conversation
    from shared.http import MODEL_TIMEOUT, assert_status, client

    fixtures = await prepare_faf_agents(tenant_a_admin, 'FAF-D3-001')
    try:
        fixture = fixtures[kind]
        async with owned_conversation(tenant_a_admin, 'FAF ' + kind) as conversation_id:
            async with client('runtime', token=tenant_a_admin.access_token, timeout=MODEL_TIMEOUT) as api:
                async with api.stream('POST', '/agent/run', json={
                    'query': 'Execute the final-answer acceptance task.', 'agent_id': fixture['agent_id'],
                    'version_no': fixture['version_no'], 'conversation_id': conversation_id,
                    'history': [], 'is_debug': False, 'generation_config': {'deep_thinking': False},
                }) as response:
                    assert_status(response, 200)
                    frames = await read_sse_with_evidence(response, 'faf-' + kind)
                history = await api.get(f'/conversation/{conversation_id}')
                assert_status(history, 200)
            events = [frame['data'] for frame in frames if isinstance(frame.get('data'), dict)]
            result = assert_evidence(kind, events, history.json())
            write_case_evidence('faf-' + kind + '-assertions', result)
    finally:
        await cleanup_faf_agents(tenant_a_admin, fixtures)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:3000")
    parser.add_argument("--inspect", action="store_true")
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--model-id", type=int)
    parser.add_argument("--verify-recorded", action="store_true")
    parser.add_argument("--run", choices=["mixed", "pure", "subagent"])
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    if args.verify_recorded:
        results = []
        for kind in ("pure", "mixed", "subagent"):
            stream = json.loads((args.evidence / (kind + "-stream.json")).read_text(encoding="utf-8"))
            history = json.loads((args.evidence / (kind + "-history.json")).read_text(encoding="utf-8"))
            results.append(assert_evidence(kind, stream["events"], history))
        (args.evidence / "api-checks.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(json.dumps(results))
        return
    client = session(args.base)
    if args.prepare:
        fixture_path = args.evidence / "fixtures.json"
        if fixture_path.exists():
            fixtures = json.loads(fixture_path.read_text(encoding="utf-8"))
            parent = fixtures["subagent"]["agent_id"]
            child = fixtures["child"]["agent_id"]
            api(client, args.base, "POST", "/agent/update", json={"agent_id": parent,
                "related_agent_ids": [child], "related_agents": [{"agent_id": child, "version_no": 1}]})
            published = api(client, args.base, "POST", f"/agent/{parent}/publish", json={"version_name": "FAF linked child"})
            fixtures["subagent"]["version_no"] = published["version_no"]
            fixture_path.write_text(json.dumps(fixtures, indent=2), encoding="utf-8")
            print("Linked parent", parent, "child", child, "version", published["version_no"])
            return
        suffix = str(int(time.time()))
        if not args.model_id:
            parser.error("--model-id is required for new real-model fixtures")
        fixtures = {}
        def create(kind, duty, related=None):
            body = {"name": "faf_" + kind + "_" + suffix, "display_name": "FAF " + kind + " " + suffix,
                    "description": "Disposable final answer acceptance agent", "model_ids": [args.model_id],
                    "max_steps": 3, "requested_output_tokens": 2048, "is_main_agent": kind != "child",
                    "provide_run_summary": False, "prompt": duty + "\n\n按职责规定的测试输出格式完成任务。",
                    "enabled": True, "enable_protocol_repair_retry": False,
                    "verification_config": {"enabled": False}, "enabled_tool_ids": [], "enabled_skill_ids": []}
            if related:
                body["related_agent_ids"] = [related]
                body["related_agents"] = [{"agent_id": related, "version_no": 1}]
            result = api(client, args.base, "POST", "/agent/update", json=body)
            ident = result["agent_id"]
            publish = api(client, args.base, "POST", f"/agent/{ident}/publish", json={"version_name": "FAF acceptance", "release_note": "Local final-answer display verification"})
            fixtures[kind] = {"agent_id": ident, "name": body["name"], "version_no": publish.get("version_no", 1)}
            print("Created", kind, ident)
            return ident
        create("pure", "你是输出格式验收助手。任何输入都只输出 <final_answer>FAF-PURE-OK</final_answer>。直接返回这段文本，不要使用代码、工具、思考前缀或任何解释。")
        create("mixed", "你是输出格式验收助手。任何输入都精确输出以下两行原始文本，禁止使用代码和工具。第一行是 检查已完成。 第二行是 <final_answer>FAF-MIXED-OK</final_answer>。第一行必须保留在标签之前。")
        child = create("child", "你是子智能体验收助手。任何任务都只输出 <final_answer>FAF-CHILD-OK</final_answer>。直接返回文本，禁止使用代码或工具。")
        child_name = fixtures["child"]["name"]
        create("subagent", f"你是父智能体验收助手。必须先调用子智能体 {child_name} 一次，请它返回验收结果。使用 Python 代码调用 {child_name}(task='返回子智能体验收结果')，收到结果后在下一轮输出 <final_answer>FAF-PARENT-OK</final_answer>。不要自行模拟子智能体结果。", child)
        (args.evidence / "fixtures.json").write_text(json.dumps(fixtures, indent=2), encoding="utf-8")
        return
    if args.run:
        fixture = json.loads((args.evidence / "fixtures.json").read_text(encoding="utf-8"))[args.run]
        body = {"query": "请按职责执行本次最终回答展示验收。", "agent_id": fixture["agent_id"],
                "version_no": fixture["version_no"], "history": [], "model_parameter_preferences": {}, "is_debug": False}
        response = client.post(args.base + "/api/agent/run", json=body, stream=True, timeout=(30, 240))
        response.raise_for_status()
        conversation = response.headers.get("conversation_id")
        events = []
        for line in response.iter_lines(decode_unicode=True):
            if line.startswith("data: "):
                event = json.loads(line[6:])
                events.append(event)
        path = args.evidence / (args.run + "-stream.json")
        path.write_text(json.dumps({"conversation_id": conversation, "events": events}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"scenario": args.run, "conversation_id": conversation,
                          "events": [{"type": e.get("type"), "content": e.get("content"), "invocation_id": e.get("invocation_id"), "answer_phase": e.get("answer_phase")} for e in events if e.get("type") in {"final_answer", "subagent_start", "subagent_end", "error", "warning"}]}, ensure_ascii=False))
        if conversation:
            detail = api(client, args.base, "GET", "/conversation/" + conversation)
            (args.evidence / (args.run + "-history.json")).write_text(json.dumps(detail, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(assert_evidence(args.run, events, detail)))
        return
    agents = api(client, args.base, "GET", "/agent/list")
    models = api(client, args.base, "GET", "/model/llm_list")
    def safe(value):
        if isinstance(value, list):
            return [safe(item) for item in value]
        if isinstance(value, dict):
            return {key: safe(item) for key, item in value.items()
                    if key in {"data", "agent_id", "model_id", "name", "display_name", "version_no", "model_ids", "model_name", "latest_version_no", "code", "enabled", "is_main_agent", "model_type"}}
        return value
    print(json.dumps({"agents": safe(agents), "models": safe(models)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
