# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-FILE-PAGE-03 prove bounded exact ObjectStore display reads."""

from contextlib import contextmanager
from threading import Event
from time import monotonic
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from management.services.knowledge_base.file_source_display import FileSourceDisplay
from nexent.storage.errors import DeadlineExceeded, NotFound, ScopeDenied, Unavailable
from nexent.storage.models import ObjectRef, OperationContext

from infrastructure.agentos_identity import ServicePrincipal


@pytest.fixture
def display():
    actor = ServicePrincipal("reader", "tenant")
    context = OperationContext("display-test", monotonic() + 10, cancelled=Event())
    stat = Mock(return_value=SimpleNamespace(size=9))
    calls, closed = [], []

    @contextmanager
    def objects(principal, key, *, context):
        calls.append((principal, key))
        try:
            yield SimpleNamespace(stat=stat), ObjectRef("files", key)
        finally:
            closed.append(key)

    service = FileSourceDisplay(objects=objects)
    return SimpleNamespace(**locals())


def test_exact_stat_reused_for_size_and_availability(display):
    s = display
    files = [
        {"path_or_url": "knowledge_base/a", "status": "COMPLETED", "file_size": 0},
        {"path_or_url": "external", "status": "PROCESSING", "file_size": 7},
    ]
    result = s.service.project(files, s.actor, context=s.context)
    assert result[0]["file_size"] == 9 and result[0]["source_available"] is True
    assert result[1]["file_size"] == 7 and result[1]["source_available"] is True
    assert s.calls == [(s.actor, "knowledge_base/a")]
    assert s.closed == ["knowledge_base/a"]
    assert s.stat.call_count == 1
    assert s.stat.call_args.args[0].space == "files"
    assert s.stat.call_args.args[0].key == "knowledge_base/a"


@pytest.mark.parametrize("error", [NotFound, Unavailable])
def test_existing_missing_or_unreadable_display_semantics(display, error):
    s = display
    s.stat.side_effect = error()
    result = s.service.project(
        [
            {
                "path_or_url": "knowledge_base/missing",
                "status": "COMPLETED",
                "file_size": 0,
            }
        ],
        s.actor,
        context=s.context,
    )
    assert result == [
        {
            "path_or_url": "knowledge_base/missing",
            "status": "COMPLETED",
            "file_size": 0,
            "source_available": False,
            "chunks": [],
        }
    ]
    assert s.stat.call_count == 1 and s.closed == ["knowledge_base/missing"]


@pytest.mark.parametrize("error", [DeadlineExceeded, ScopeDenied])
def test_deadline_and_scope_are_not_display_fallbacks(display, error):
    s = display
    s.stat.side_effect = error()
    with pytest.raises(error):
        s.service.project(
            [
                {
                    "path_or_url": "knowledge_base/a",
                    "status": "COMPLETED",
                    "file_size": 0,
                }
            ],
            s.actor,
            context=s.context,
        )
    assert s.stat.call_count == 1 and s.closed == ["knowledge_base/a"]


def test_preserves_nonzero_raw_metadata_and_does_not_stat_other_prefixes(display):
    s = display
    files = [
        {"path_or_url": "external", "status": "COMPLETED", "file_size": "stored-size"},
        {"path_or_url": None, "status": "UPLOADED", "file_size": 0},
    ]
    assert s.service.project(files, s.actor, context=s.context) == [
        dict(v, source_available=True, chunks=[]) for v in files
    ]
    assert not s.calls


def test_lifecycle_size_and_pending_source_keep_original_precedence(display):
    s = display
    source = {
        "path_or_url": "source",
        "status": "COMPLETED",
        "file_size": 0,
        "file": "effective",
        "chunk_count": 4,
    }
    rows = [
        {
            "file_id": "f",
            "object_name": "source",
            "status": "FAILED",
            "file_size": 0,
            "original_filename": "original",
        },
        {
            "file_id": "pending",
            "object_name": "knowledge_base/pending",
            "status": "UPLOADED",
            "file_size": 0,
        },
    ]
    files = s.service.project([source], s.actor, context=s.context, lifecycle_rows=rows)
    assert (
        files[0]["file_size"] == 0
        and files[0]["file"] == "effective"
        and files[0]["chunk_count"] == 4
    )
    assert files[0]["status"] == "PROCESS_FAILED"
    assert files[1]["file_size"] == 0 and files[1]["source_available"] is True
    assert s.calls == [(s.actor, "source")]
