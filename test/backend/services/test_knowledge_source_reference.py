# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Typed source identities survive message projection without URL guessing."""

import json

import pytest
from contracts.agentos_knowledge import KnowledgeSourceReference
from management.services.agent.stream import AssistantMessageProjection
from pydantic import ValidationError


def reference():
    return {
        "file_ref": {"knowledge_id": 1, "file_id": "a" * 32, "file_version": 2},
        "image_ref": {
            "space": "files",
            "key": "images/item.png",
            "version": "v1",
            "sha256": "b" * 64,
        },
        "location": {"page_number": 3},
    }


def test_projection_keeps_typed_reference_and_does_not_overload_aidp_metadata():
    projection = AssistantMessageProjection(persist_units=True)
    projection.project(
        json.dumps(
            {
                "type": "search_content",
                "content": json.dumps(
                    [
                        {
                            "title": "report",
                            "url": "",
                            "text": "fact",
                            "cite_index": 1,
                            "tool_sign": "a",
                            **reference(),
                        }
                    ]
                ),
            }
        )
    )
    (row,) = projection.search_records
    assert row["knowledge_reference"] == reference() and row["source_location"] == ""
    assert row["aidp_source_reference"] == {} and row["cite_index"] == 1


def test_reference_contract_rejects_arbitrary_keys_and_oversized_locations():
    for value in (
        {**reference(), "authorization": "private"},
        {**reference(), "location": {"text": "x" * 16384}},
        {**reference(), "location": {"text": "中" * 6000}},
        {
            **reference(),
            "file_ref": {"knowledge_id": 1, "file_id": "a" * 32, "file_version": -1},
        },
    ):
        with pytest.raises(ValidationError):
            KnowledgeSourceReference.model_validate(value)


def test_non_knowledge_source_does_not_invent_a_resource_reference():
    projection = AssistantMessageProjection(persist_units=True)
    projection.project(
        json.dumps(
            {
                "type": "search_content",
                "content": '[{"title":"web","url":"https://example.test"}]',
            }
        )
    )
    assert projection.search_records[0]["knowledge_reference"] is None


def test_both_history_read_paths_restore_resource_identity(mocker):
    mocker.patch(
        "nexent.storage.storage_client_factory.create_storage_client_from_config"
    )
    mocker.patch(
        "nexent.storage.minio_config.MinIOStorageConfig.validate", return_value=None
    )
    from management.services.conversation import service

    row = {
        "message_id": 2,
        "unit_id": 3,
        "source_title": "report",
        "source_content": "fact",
        "source_type": "file",
        "source_location": "",
        "published_date": None,
        "score_overall": 0.8,
        "score_accuracy": None,
        "score_semantic": None,
        "cite_index": 1,
        "search_type": "knowledge_base_search",
        "tool_sign": "a",
        "knowledge_reference": reference(),
    }
    history = mocker.patch.object(
        service,
        "get_conversation_history",
        return_value={
            "conversation_id": 1,
            "create_time": None,
            "search_records": [row],
            "image_records": [],
            "message_records": [
                {
                    "message_id": 2,
                    "role": "assistant",
                    "message_content": "answer",
                    "opinion_flag": None,
                    "status": "completed",
                    "units": [],
                }
            ],
        },
    )
    result = service.get_conversation_history_service(1, "owner")
    item = result[0]["message"][0]["search"][0]
    assert {key: item[key] for key in reference()} == reference()
    history.assert_called_once_with(1, "owner")
    sources = mocker.patch.object(
        service, "get_source_searches_by_message", return_value=[row]
    )
    item = service.get_sources_service(None, 2, source_type="search", user_id="owner")[
        "data"
    ]["searches"][0]
    assert {key: item[key] for key in reference()} == reference()
    sources.assert_called_once_with(2, "owner")
