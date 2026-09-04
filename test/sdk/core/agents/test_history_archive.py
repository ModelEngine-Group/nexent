"""Acceptance tests for P6 run-local searchable history."""

import pytest

from nexent.core.agents.context.archive import RunHistoryArchive, SearchArchivedHistoryTool


def test_ac_p6_003_unicode_ranking_redaction_filters_and_caps():
    archive = RunHistoryArchive(run_id="tenant-a/run-a", hard_input_budget=100, chars_per_token=2)
    archive.add(kind="chat_turn", source_id="turn:1", content={
        "user": "请部署华为云服务", "assistant": "部署完成", "reasoning": "never reveal",
        "api_key": "credential-value",
    })
    archive.add(kind="error", source_id="step:1", content="DashScope timeout")

    chinese = archive.search("华为云部署", top_k=99, kinds=["chat_turn"])
    english = SearchArchivedHistoryTool(archive).forward("timeout", kinds=["error"])

    assert len(chinese["results"]) == 1
    assert chinese["results"][0]["kind"] == "chat_turn"
    assert "never reveal" not in chinese["results"][0]["content"]
    assert "credential-value" not in chinese["results"][0]["content"]
    assert english["results"][0]["source_id"] == "step:1"
    assert chinese["recalled_tokens"] <= 20
    assert english["recalled_tokens"] <= 20


def test_ac_p6_003_stable_ids_and_kind_validation():
    first = RunHistoryArchive(run_id="run-1", hard_input_budget=100)
    second = RunHistoryArchive(run_id="run-2", hard_input_budget=100)
    assert first.add(kind="result", source_id="step:1", content="ok").archive_id != second.add(
        kind="result", source_id="step:1", content="ok"
    ).archive_id
    assert first.search("ok", top_k=0)["results"]
    with pytest.raises(ValueError, match="unsupported archive kinds"):
        first.search("ok", kinds=["reasoning"])
