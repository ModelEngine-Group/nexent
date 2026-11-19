# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-SOURCE-DISPLAY-01/02/03 pin display fields to current file grants."""

from datetime import UTC, datetime

import pytest
from contracts.agentos_knowledge import KnowledgeFileGrant, KnowledgeFileSourceDisplay
from nexent.storage.errors import InvalidInput
from pydantic import ValidationError

from test.backend.services import test_knowledge_authorization as auth_tests
from test.backend.services import test_knowledge_ingestion as ingest_tests
from test.backend.services.test_cleanse_authorization import (
    resources as resources,  # noqa: PLC0414
)
from test.backend.services.test_cleanse_jobs import context

authorization = auth_tests.setup
ingestion = ingest_tests.setup


def display():
    return KnowledgeFileSourceDisplay(
        size_bytes=9, created_at="2026-11-19T01:02:03+00:00"
    )


@pytest.mark.parametrize(
    "values",
    [
        {"size_bytes": -1, "created_at": None},
        {"size_bytes": True, "created_at": None},
        {"size_bytes": 0, "created_at": "not-time"},
        {"size_bytes": 0, "created_at": "2026-11-19T01:02:03"},
        {"size_bytes": 0, "created_at": None, "path_or_url": "forged"},
    ],
)
def test_display_has_strict_finite_values(values):
    with pytest.raises(ValidationError):
        KnowledgeFileSourceDisplay(**values)


def test_grant_pins_display_and_preserves_unknown_history(authorization):
    policy, payload, update, _, _ = authorization
    update("cleanse_files", file_size=9, uploaded_at=datetime(2026, 11, 19, 1, 2, 3, tzinfo=UTC))
    grant = policy.authorize(payload, context=context())
    assert grant.source_display == display()
    assert grant.source_display.model_dump() == {
        "size_bytes": 9,
        "created_at": "2026-11-19T01:02:03+00:00",
    }
    update("cleanse_files", file_size=None, uploaded_at=None)
    assert policy.authorize(
        payload, context=context()
    ).source_display == KnowledgeFileSourceDisplay(size_bytes=None, created_at=None)
    inspect = payload.model_copy(
        update={"action": "inspect", "artifact": None, "parser_version": None}
    )
    assert policy.authorize(inspect, context=context()).source_display is None


def test_execution_grant_cannot_omit_display_or_put_it_on_lookup(authorization):
    policy, payload, *_ = authorization
    value = policy.authorize(payload, context=context()).model_dump(mode="json")
    without = {k: v for k, v in value.items() if k != "source_display"}
    with pytest.raises(ValidationError):
        KnowledgeFileGrant.model_validate(without)
    with pytest.raises(ValidationError):
        KnowledgeFileGrant.model_validate({**value, "source_display": None})
    with pytest.raises(ValidationError):
        KnowledgeFileGrant.model_validate(
            {
                **value,
                "action": "inspect",
                "source": None,
                "artifact": None,
                "parser_version": None,
            }
        )


@pytest.mark.parametrize("filename", ["source.txt", "book.xlsx"])
@pytest.mark.parametrize("strategy", ["basic", "by_title", "none"])
async def test_all_text_strategies_store_authorized_source_fields(
    ingestion, strategy, filename
):
    s = ingestion
    await s.service.execute(
        s.request.model_copy(update={"chunking_strategy": strategy}),
        **{**s.arguments, "source_display": display(), "filename": filename},
    )
    rows = [row for call in s.vectors.upsert.call_args_list for row in call.args[0]]
    assert rows
    for row in rows:
        assert row.payload["filename"] == filename
        location = row.payload["location"]
        assert (
            location["path_or_url"] == s.value.source.key and location["file_size"] == 9
        )
        assert (
            location["create_time"] == "2026-11-19T01:02:03+00:00"
            and location["source_type"] == "file"
        )


async def test_parser_cannot_replace_source_or_add_competing_public_block(
    ingestion, mocker
):
    s = ingestion
    mocker.patch(
        "runtime.knowledge_base.ingestion.chunk_text",
        return_value=[
            {
                "content": "text",
                "metadata": {
                    "path_or_url": "foreign/object",
                    "file_size": 900,
                    "create_time": "forged",
                    "source_type": "http",
                    "nexent_public_chunk_v1": {"path_or_url": "foreign/nested"},
                    "page_number": 3,
                },
            }
        ],
    )
    await s.service.execute(s.request, **{**s.arguments, "source_display": display()})
    location = s.vectors.upsert.call_args.args[0][0].payload["location"]
    assert (
        location["path_or_url"] == s.value.source.key
        and location["file_size"] == 9
        and location["page_number"] == 3
    )
    assert (
        location["create_time"] == display().created_at
        and location["source_type"] == "file"
    )
    assert "nexent_public_chunk_v1" not in location


async def test_missing_display_is_rejected_before_model_or_storage(ingestion):
    s = ingestion
    with pytest.raises(InvalidInput):
        await s.service.execute(s.request, **{**s.arguments, "source_display": None})
    s.models.get.assert_not_called()
    s.vectors.upsert.assert_not_called()
