# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Schema defaults must preserve provider provenance without guessing identities."""

import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from test_jiuwen_errors import adapter as _adapter
from test_jiuwen_tool_spans import spans as _spans

from nexent.core.agents.context.execution_history import ExecutionHistory
from nexent.core.agents.context.action_history import register_authorized_sources
from nexent.core.agents.context.native_history import decode_history_event
from nexent.core.model_service.contracts import AssistantMessage, ToolCall
from nexent.core.tools.read_skill_md_tool import ReadSkillMdTool

adapter = _adapter
spans = _spans
SCHEMA = {"type": "object", "properties": {"key": {"type": "string"},
          "optional": {"type": "array", "items": {}}}, "required": ["key"]}


def register(adapter, schema=SCHEMA, name="local"):
    return adapter._tool_card(name=name, description="Registered tool", input_params=deepcopy(schema))


def pending(adapter, arguments, name="local"):
    adapter.events.begin_step(None)
    calls = [ToolCall(provider_call_id=f"original-{index}", index=index, name=name,
                      raw_arguments=json.dumps(value, separators=(",", ":")), parsed_arguments=deepcopy(value))
             for index, value in enumerate(arguments)]
    adapter.events.model_event(SimpleNamespace(type="message_completed", message=AssistantMessage(
        tool_calls=calls, finish_reason="tool_calls")))
    return calls


def emitted(adapter):
    return [json.loads(value) for value in adapter.run_info.observer.get_cached_message()]


def test_actual_local_function_default_survives_history_and_source_restore(adapter, spans):
    from openjiuwen.core.foundation.tool import LocalFunction
    from nexent.core.agents.cores.jiuwen.adapter import _tool_schema
    from test_context_message_format import history, render

    card = register(adapter, _tool_schema(ReadSkillMdTool.inputs), "read_skill_md")
    provider_args = {"skill_name": "fixture_skill"}
    original = pending(adapter, [provider_args], "read_skill_md")[0]
    received = []

    async def forward(**arguments):
        received.append(arguments)
        return "EXACT_SKILL_SOURCE"

    tool = LocalFunction(card, adapter._business_handler("read_skill_md", forward))
    assert asyncio.run(tool.invoke(provider_args)) == "EXACT_SKILL_SOURCE"
    assert provider_args == {"skill_name": "fixture_skill"}
    assert received == [{"skill_name": "fixture_skill", "additional_files": None}]
    events = [value for value in emitted(adapter) if value["type"] in {"tool", "tool_result"}]
    call, result = events
    assert call["provider_call_id"] == result["provider_call_id"] == original.provider_call_id
    assert call["raw_arguments"] == original.raw_arguments
    assert call["tool_arguments"] == received[0]
    assert call["source_protocol"] == "model_native_fc"
    assert call["call_index"] == 0 and call["call_count"] == 1 and call["call_group_id"]
    records = []
    for index, event in enumerate(events):
        record = {"record_type": event["type"], "content": json.dumps(event), "unit_index": index,
                  "tool_call_id": event["local_call_id"], "invocation_id": None}
        record["execution_event"] = decode_history_event(record)
        records.append(record)
    messages = render(records)
    assert messages[1]["tool_calls"][0]["id"] == original.provider_call_id
    assert json.loads(messages[1]["tool_calls"][0]["function"]["arguments"]) == provider_args
    assert messages[2] == {"role": "tool", "tool_call_id": original.provider_call_id,
                           "content": "EXACT_SKILL_SOURCE"}
    store = ExecutionHistory()
    register_authorized_sources([history(records)], store, "owner")
    sources = store.authorized_sources("owner")
    assert any(source.source_kind == "tool_result" and source.text == "EXACT_SKILL_SOURCE" for source in sources)
    tool_spans = [span for span in spans[1].get_finished_spans()
                  if span.attributes.get("openinference.span.kind") == "TOOL"]
    assert len(tool_spans) == 1
    assert tool_spans[0].attributes["nexent.tool.provider_call_id"] == original.provider_call_id


@pytest.mark.parametrize("default", [None, False, 0, "default", [], {"a": 1}])
def test_declared_default_omission_and_explicit_value(adapter, default):
    schema = deepcopy(SCHEMA)
    schema["properties"]["optional"] = {"default": default}
    register(adapter, schema)
    before = deepcopy(schema)
    pending(adapter, [{"key": "a"}, {"key": "b", "optional": default}])
    actual = {"key": "a", "optional": deepcopy(default)}
    assert adapter.events.tool_call("local", actual, "a") == "original-0"
    assert adapter.events.tool_call("local", {"key": "b", "optional": default}, "b") == "original-1"
    assert actual == {"key": "a", "optional": default} and schema == before
    assert adapter.events.tool_call("local", actual, "again") is None


@pytest.mark.parametrize("provider,actual", [
    ({"key": "a"}, {"key": "a", "optional": None, "unknown": None}),
    ({}, {"optional": None}),
    ({"key": "a"}, {"key": "a", "optional": []}),
    ({"key": "a", "optional": []}, {"key": "a", "optional": None}),
    ({"key": "a"}, {"key": "b", "optional": None}),
    ({"key": 1}, {"key": True, "optional": None}),
    ({"key": 1}, {"key": 1.0, "optional": None}),
    ({"key": "1"}, {"key": 1, "optional": None}),
    ({"key": "a", "unknown": None}, {"key": "a", "optional": None}),
])
def test_non_default_differences_never_bind(adapter, provider, actual):
    register(adapter)
    pending(adapter, [provider])
    originals = deepcopy((provider, actual))
    assert adapter.events.tool_call("local", actual, "local") is None
    assert len(adapter.events.calls) == 1 and (provider, actual) == originals


def test_exact_match_precedes_new_default_equivalence(adapter):
    register(adapter)
    pending(adapter, [{"key": "a"}, {"key": "a", "optional": None}])
    actual = {"key": "a", "optional": None}
    assert adapter.events.tool_call("local", actual, "first") == "original-1"
    assert adapter.events.tool_call("local", actual, "second") == "original-0"
    assert adapter.events.tool_call("local", actual, "third") is None


@pytest.mark.parametrize("values", [[{"key": "a"}, {"key": "a"}],
                                   [{"key": "a", "optional": None}] * 2])
def test_ambiguous_matches_remain_unbound(adapter, values):
    register(adapter)
    pending(adapter, values)
    assert adapter.events.tool_call("local", {"key": "a", "optional": None}, "local") is None
    assert len(adapter.events.calls) == 2


def test_same_name_calls_keep_original_order_metadata_and_ids(adapter):
    register(adapter)
    pending(adapter, [{"key": "a"}, {"key": "b"}])
    assert adapter.events.tool_call("local", {"key": "b", "optional": None}, "b") == "original-1"
    assert adapter.events.tool_call("local", {"key": "a", "optional": None}, "a") == "original-0"
    tools = [value for value in emitted(adapter) if value["type"] == "tool"]
    assert [value["call_index"] for value in tools] == [1, 0]
    assert [value["call_count"] for value in tools] == [2, 2]
    assert tools[0]["call_group_id"] == tools[1]["call_group_id"]


def test_unregistered_mcp_exact_and_nested_paths_keep_existing_rules(adapter):
    pending(adapter, [{"key": "a"}], "remote")
    assert adapter.events.tool_call("remote", {"key": "a", "optional": None}, "unbound") is None
    assert adapter.events.tool_call("remote", {"key": "a"}, "exact") == "original-0"
    register(adapter)
    pending(adapter, [{"key": "a"}])
    assert adapter.events.tool_call("local", {"key": "a", "optional": None}, "child", parent_call_id="p") is None
    assert len(adapter.events.calls) == 1


@pytest.mark.parametrize("default,executed", [(False, 0), (0, False), (1, "1")])
def test_declared_defaults_do_not_coerce_types(adapter, default, executed):
    schema = deepcopy(SCHEMA)
    schema["properties"]["optional"] = {"default": default}
    register(adapter, schema)
    pending(adapter, [{"key": "a"}])
    assert adapter.events.tool_call("local", {"key": "a", "optional": executed}, "local") is None
    assert len(adapter.events.calls) == 1


@pytest.mark.parametrize("difference", [None, "unknown", "required"])
def test_actual_nested_schema_defaults_need_complete_declared_provenance(adapter, difference):
    from openjiuwen.core.common.utils.schema_utils import SchemaUtils

    schema = {"type": "object", "properties": {"items": {"type": "array", "items": SCHEMA}, "top": {}},
              "required": ["items"]}
    register(adapter, schema)
    provided = {"items": [{"key": "a"}, {"key": "b"}]}
    actual = SchemaUtils.format_with_schema(provided, schema)
    assert actual == {"items": [{"key": "a"}, {"key": "b"}], "top": None}
    if difference == "unknown":
        actual["items"][1]["optional"] = None
    elif difference == "required":
        del provided["items"][1]["key"]
        del actual["items"][1]["key"]
    original = pending(adapter, [provided])[0]
    found = adapter.events.tool_call("local", actual, "local")
    assert found == (original.provider_call_id if difference is None else None)
    assert provided["items"][0] == {"key": "a"}
