# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""PR4249 AC-003/004: provenance and request scope before persistence."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from management.services.memory.extraction import FaMemoryExtractor
from management.services.memory.extraction_scope import parse_grounded_items


def candidate(evidence, category="user_preference", source="user", scope="durable", **extra):
    return dict(evidence=evidence, category=category, source=source, scope=scope, **extra)


def parse(items, query="", answer=""):
    return parse_grounded_items(json.dumps({"items": items}), query, answer)


@pytest.mark.parametrize("query,evidence", [
    ("本轮控制在200字以内。", "控制在200字以内"),
    ("这次请始终使用表格。", "始终使用表格"),
    ("今天我喜欢用英文。", "我喜欢用英文"),
    ("仅用于本次任务：我偏好 JSON。", "我偏好 JSON"),
    ("For this answer I prefer JSON.", "I prefer JSON"),
    ("This time always keep replies under 75 words.", "always keep replies under 75 words"),
    ("Today I prefer bullet points.", "I prefer bullet points"),
    ("Use a temporary default of CSV.", "default of CSV"),
])
def test_ac004_local_qualifiers_cannot_be_stripped(query, evidence):
    assert parse([candidate(evidence)], query) == []


@pytest.mark.parametrize("query", [
    "我长期偏好先给三条结论，再列风险和回滚方案。",
    "我们每周四16:00发布版本。",
    "数据库变更必须先备份，失败时不得删除数据。",
    "I always prefer three conclusions followed by risks and rollback.",
    "By default use Chinese for our release reports.",
])
def test_ac003_explicit_stable_preferences_remain_learnable(query):
    assert parse([candidate(query)], query) == [query]


def test_ac003_mixed_scope_message_keeps_only_the_durable_preference():
    durable = "我长期偏好中文三条结论，再列风险和回滚方案。"
    local = "这次答案控制在200字以内。"
    query = durable + local
    assert parse([candidate(durable), candidate(local), candidate("控制在200字以内")], query) == [durable]


def test_ac004_assistant_procedure_is_not_user_preference_even_if_labelled_durable():
    answer = "用户偏好按变更前、变更中、变更后组织汇报。"
    assert parse([candidate(answer, source="final_answer")], "给我一份升级方案。", answer) == []
    assert parse([candidate(answer)], "给我一份升级方案。", answer) == []


def test_ac004_mislabelled_assistant_suggestion_is_not_a_confirmed_outcome():
    text = "建议已完成升级后按三个阶段汇报。"
    assert parse([candidate(text, "task_outcome", "final_answer")], "升级建议？", text) == []


def test_ac003_verified_outcome_is_retained_without_inventing_a_preference():
    text = "Backup restoration completed and verified."
    assert parse([candidate(text, "task_outcome", "final_answer")], "Restore the backup.", text) == [text]


def test_ac003_user_fact_does_not_require_a_preference_keyword():
    text = "我是林舟，负责星河项目交付。"
    assert parse([candidate(text, "user_fact")], text) == [text]


def test_ac004_grounded_quote_cannot_smuggle_an_assistant_paraphrase():
    query = "我长期偏好中文。"
    item = candidate(query, content="用户偏好每次都用表格和200字以内。")
    assert parse([item], query) == [query]


@pytest.mark.parametrize("item", [
    candidate("not present"),
    candidate("I prefer Python.", scope="request"),
    candidate("I prefer Python.", source="unknown"),
    candidate("I prefer Python.", category="unknown"),
    candidate("I prefer Python.", category=[]),
    candidate("I prefer Python.", category={}),
    candidate(None),
    candidate(""),
    candidate("x" * 1001),
    None, [], "invalid", {},
])
def test_ac007_unsupported_and_malformed_candidates_fail_closed(item):
    assert parse([item], "I prefer Python.") == []


def test_ac007_invalid_json_and_oversized_candidate_batches_fail_closed():
    assert parse_grounded_items('{"items":', "", "") == []
    assert parse([candidate("I prefer Python.")] * 21, "I prefer Python.") == []


def test_ac003_repeated_evidence_is_stored_once():
    query = "I prefer Python."
    assert parse([candidate(query), candidate(query)], query) == [query]


@pytest.mark.asyncio
async def test_ac003_mixed_scope_extractor_only_persists_grounded_stable_item():
    durable = "我长期偏好先给结论。"
    local = "本轮仅用表格且不超过120字。"
    service = MagicMock()
    service.store_memory = AsyncMock(return_value=MagicMock(memory_id=1, event="ADD"))
    client = MagicMock()
    client.chat = AsyncMock(return_value=json.dumps({"items": [candidate(durable), candidate(local)]}))
    extractor = FaMemoryExtractor(tenant_id="tenant", user_id="user", agent_id="agent",
                                 conversation_id="conversation", model_client=client, memory_service=service)
    result = await extractor.extract_and_store("助手建议按三个阶段汇报。", durable + local)
    assert result.reason == "ok"
    service.store_memory.assert_awaited_once()
    assert service.store_memory.await_args.kwargs["content"] == durable
    assert service.store_memory.await_args.kwargs["tenant_id"] == "tenant"


@pytest.mark.asyncio
async def test_ac003_extraction_uses_monitored_wrapper_and_managed_lane(monkeypatch):
    from types import SimpleNamespace
    from management.services.memory import extraction

    model = MagicMock()
    manager = MagicMock()
    manager.run = AsyncMock(return_value=SimpleNamespace(content='{"items": []}'))
    operations = []
    monkeypatch.setattr(extraction, 'set_monitoring_operation', operations.append)
    adapter = extraction.MemoryExtractionModelClient(model, manager)
    messages = [{'role': 'user', 'content': 'source-grounded extraction'}]
    assert await adapter.chat(messages) == '{"items": []}'
    lane, spec, invoked, supplied = manager.run.await_args.args
    assert lane == 'model-tool-io'
    assert spec.task_name == 'memory-extractor-model-generate'
    assert invoked is model
    assert supplied is messages
    assert operations == ['memory_extraction']
    model.generate.assert_not_called()


@pytest.mark.parametrize('query', ['请用中文解释索引。', 'Explain indexes using a table.'])
def test_ac004_bare_answer_instruction_does_not_establish_lasting_intent(query):
    assert parse([candidate(query)], query) == []


@pytest.mark.parametrize('query', [
    '请按我长期的汇报习惯给发布负责人一份核对提醒：既定窗口是什么？',
    '沿用我长期的汇报习惯给出建议。',
    'Please follow my long-term reporting preference.',
    'What is my usual reporting format?',
])
@pytest.mark.parametrize('category', ['user_preference', 'user_fact'])
def test_ac004_reference_to_existing_preference_is_not_a_new_fact(query, category):
    assert parse([candidate(query, category)], query) == []
