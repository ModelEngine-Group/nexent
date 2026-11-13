# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from types import SimpleNamespace
from urllib.parse import quote

import pytest
from fastapi import HTTPException

from contracts.agentos import RunInput
from infrastructure.agentos_identity import ServicePrincipal
from management.services.agent.preparation.evaluation_snapshot import build_evaluation_input
from runtime.agentos import prepared_attachments

ACTOR = ServicePrincipal("actor", "tenant")


@pytest.fixture(autouse=True)
def storage_boundary(mocker):
    mocker.patch("infrastructure.agent_attachments.MINIO_DEFAULT_BUCKET", "nexent")
    mocker.patch.object(prepared_attachments, "NORTHBOUND_EXTERNAL_URL", "https://gateway.invalid")
    return mocker.patch(
        "infrastructure.object_storage.client.minio_client.get_file_url",
        return_value=(True, "https://storage.invalid/new-signed-link"),
    )


def test_history_attachment_preserves_turn_and_uses_fresh_link_once(storage_boundary):
    history = [
        SimpleNamespace(role="user", content="earlier", minio_files=[
            {"name": "report.txt", "url": "s3:/nexent/attachments/actor/report.txt", "presigned_url": "old-link"},
        ]),
        SimpleNamespace(role="assistant", content="response", minio_files=None),
    ]
    current = [{"name": "report.txt", "object_name": "attachments/actor/report.txt", "presigned_url": "stale"}]
    request = build_evaluation_input("latest", current, history, ACTOR.user_id, ACTOR.tenant_id)
    encoded = request.model_dump_json()
    assert "old-link" not in encoded and "stale" not in encoded

    query, restored, files = prepared_attachments.materialize_evaluation_input(
        RunInput.model_validate_json(encoded), ACTOR, "en",
    )
    fresh = "https://gateway.invalid/nb/v1/file/fetch?presigned_url=" + quote(
        "https://storage.invalid/new-signed-link", safe="",
    )
    assert query.count("s3://nexent/attachments/actor/report.txt") == 1
    assert fresh in query and "latest" in query
    assert restored[0].content.startswith("earlier") and fresh in restored[0].content
    assert restored[1].content == "response"
    assert files == [{"name": "report.txt", "url": "s3://nexent/attachments/actor/report.txt", "presigned_url": fresh}]
    storage_boundary.assert_called_once_with("attachments/actor/report.txt", "nexent")


def test_non_dialogue_history_retains_attachment_order_without_its_text():
    def file(name):
        return {"name": name, "url": f"s3://nexent/attachments/actor/{name}"}

    history = [
        SimpleNamespace(role="tool", content="private tool transcript", minio_files=[file("first.txt")]),
        SimpleNamespace(role="user", content="earlier", minio_files=[file("second.txt"), file("first.txt")]),
    ]
    request = build_evaluation_input("latest", [file("current.txt")], history, ACTOR.user_id, ACTOR.tenant_id)
    encoded = request.model_dump_json()
    assert "private tool transcript" not in encoded
    assert request.history[0].role == "attachment"

    query, restored, files = prepared_attachments.materialize_evaluation_input(
        RunInput.model_validate_json(encoded), ACTOR, "en",
    )
    assert [entry.name for entry in request.history[0].attachment_refs] == ["first.txt"]
    assert [entry["name"] for entry in files] == ["current.txt", "first.txt", "second.txt"]
    assert query.count("s3://nexent/attachments/actor/first.txt") == 1
    assert [entry.role for entry in restored] == ["user"]
    assert restored[0].content.startswith("earlier")


def test_attachment_only_history_rejects_text():
    with pytest.raises(ValueError, match="content"):
        RunInput.model_validate({"query": "query", "history": [{
            "role": "attachment", "content": "unexpected text",
            "attachment_refs": [{"name": "x", "url": "s3://nexent/attachments/actor/x"}],
        }]})


@pytest.mark.parametrize("url", [
    "s3://nexent/attachments/other/private.txt",
    "s3://other-bucket/attachments/actor/report.txt",
])
@pytest.mark.parametrize("role", ["user", "attachment"])
def test_all_attachment_references_are_checked_before_any_signing(storage_boundary, url, role):
    first = {"name": "ok", "url": "s3://nexent/attachments/actor/report.txt", "presign": True}
    request = RunInput.model_validate({
        "query": "query", "attachment_refs": [first],
        "history": [{"role": role, "content": "", "attachment_refs": [{"name": "bad", "url": url, "presign": True}]}],
    })
    with pytest.raises(HTTPException) as error:
        prepared_attachments.materialize_evaluation_input(request, ACTOR, "en")
    assert error.value.status_code == 403
    assert error.value.detail == {"code": "AGENTOS_ATTACHMENT_FORBIDDEN"}
    storage_boundary.assert_not_called()


@pytest.mark.parametrize("presign", [False, True])
def test_runtime_only_requests_links_when_needed(storage_boundary, presign):
    storage_boundary.return_value = (False, "sensitive infrastructure details")
    request = RunInput.model_validate({
        "query": "query",
        "attachment_refs": [{"name": "report", "url": "s3://nexent/attachments/actor/report.txt", "presign": presign}],
    })
    if presign:
        with pytest.raises(HTTPException) as error:
            prepared_attachments.materialize_evaluation_input(request, ACTOR, "en")
        assert error.value.status_code == 503
        assert error.value.detail == {"code": "AGENTOS_ATTACHMENT_LINK_UNAVAILABLE"}
    else:
        query, _, files = prepared_attachments.materialize_evaluation_input(request, ACTOR, "en")
        assert "s3://nexent/attachments/actor/report.txt" in query
        assert files[0]["presigned_url"] == ""
        storage_boundary.assert_not_called()


@pytest.mark.asyncio
async def test_evaluation_compiler_exports_history_refs_without_pre_rendering_links(mocker, storage_boundary):
    from contracts.agentos import EvaluationAgentRun
    from infrastructure.agent_model_config import create_model_config_from_record
    from management.services.agent.preparation import evaluation_snapshot, run
    from nexent.core.agents.agent_model import AgentConfig

    record = {
        "model_id": 11, "tenant_id": "tenant", "model_type": "llm", "model_name": "provider-model",
        "display_name": "Evaluation", "model_repo": None, "api_key": "local-only", "base_url": "https://provider.invalid",
        "update_time": "revision-1",
    }
    model = create_model_config_from_record(record)
    config = AgentConfig(
        agent_id=7, version_no=2, name="evaluation", description="", model_name=model.cite_name, tools=[],
    )
    mocker.patch.object(evaluation_snapshot, "get_model_records", return_value=[record])
    mocker.patch.object(run, "_ensure_agent_reasoning_snapshot")
    mocker.patch.object(run, "search_agent_info_by_agent_id", return_value={})
    mocker.patch.object(run, "create_model_config_list", return_value=[model])
    compile_agent = mocker.patch.object(run, "create_agent_config", return_value=config)
    format_legacy = mocker.patch.object(run, "join_minio_file_description_to_query")
    result = await evaluation_snapshot.prepare_evaluation_snapshot(EvaluationAgentRun(
        agent_id=7, version_no=2, query="latest", history=[{
            "role": "user", "content": "earlier", "minio_files": [{
                "name": "report.txt", "object_name": "attachments/actor/report.txt", "presigned_url": "stale",
            }],
        }],
    ), ACTOR.user_id, ACTOR.tenant_id)
    assert result.input.query == "latest" and result.input.history[0].content == "earlier"
    assert result.input.history[0].attachment_refs[0].url == "s3://nexent/attachments/actor/report.txt"
    assert "stale" not in result.model_dump_json()
    assert compile_agent.await_args.kwargs["last_user_query"] == "latest"
    format_legacy.assert_not_awaited()
    storage_boundary.assert_not_called()
