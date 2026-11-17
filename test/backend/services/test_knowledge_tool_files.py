# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Path selection must resolve only authorized immutable knowledge file identities."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from management.services.knowledge_base.tool_files import resolve_tool_files
from nexent.storage.errors import ScopeDenied


@pytest.fixture
def records():
    port = Mock()
    port.query.return_value = SimpleNamespace(items=[{
        "knowledge_id": 1, "file_id": "a" * 32, "source_generation": 3,
        "source_space": "files", "source_key": "reports/a.txt", "source_revision": "v3",
        "source_sha256": "b" * 64, "status": "COMPLETED", "object_name": "reports/a.txt",
        "bucket_name": "bucket",
    }], next_cursor=None)
    return port


def test_paths_are_resolved_with_live_permission_and_exact_scoped_filters(mocker, records):
    authorize = mocker.patch("management.services.knowledge_base.tool_files.KnowledgeFileAuthorization")
    refs = resolve_tool_files(records, "user", [1], ["reports/a.txt", "s3://bucket/reports/a.txt"], context="context")
    authorize.return_value.resolve_knowledges.assert_called_once_with([1], edit=False, context="context")
    assert [ref.model_dump() for ref in refs] == [{"knowledge_id": 1, "file_id": "a" * 32, "file_version": 3}]
    query = records.query.call_args.args[1]
    assert query.where.operator == "and"
    assert query.where.terms[0].field == "knowledge_id" and query.where.terms[0].value == [1]
    assert records.query.call_args.args[2].limit == 1000


@pytest.mark.parametrize("paths", [None, []])
def test_unset_external_paths_preserve_unfiltered_semantics(records, paths):
    assert resolve_tool_files(records, "user", [1], paths, context="context") is None
    records.query.assert_not_called()


def test_nonempty_unknown_path_never_becomes_unfiltered(mocker, records):
    mocker.patch("management.services.knowledge_base.tool_files.KnowledgeFileAuthorization")
    records.query.return_value = SimpleNamespace(items=[], next_cursor=None)
    assert resolve_tool_files(records, "user", [1], ["unknown"], context="context") == []


@pytest.mark.parametrize("change", [{"knowledge_id": 2}, {"source_generation": None}, {"source_revision": None},
                                  {"source_sha256": "bad"}, {"source_key": "different"}])
def test_invalid_or_out_of_scope_record_fails_closed(mocker, records, change):
    mocker.patch("management.services.knowledge_base.tool_files.KnowledgeFileAuthorization")
    records.query.return_value.items[0].update(change)
    records.query.return_value.items[0]["object_name"] = "different"
    with pytest.raises(ScopeDenied):
        resolve_tool_files(records, "user", [1], ["reports/a.txt"], context="context")


def test_permission_denial_prevents_file_query(mocker, records):
    mocker.patch("management.services.knowledge_base.tool_files.KnowledgeFileAuthorization").return_value.resolve_knowledges.side_effect = ScopeDenied()
    with pytest.raises(ScopeDenied):
        resolve_tool_files(records, "user", [1], ["reports/a.txt"], context="context")
    records.query.assert_not_called()


def test_query_overflow_is_not_silently_truncated(mocker, records):
    mocker.patch("management.services.knowledge_base.tool_files.KnowledgeFileAuthorization")
    records.query.return_value.next_cursor = "more"
    with pytest.raises(ScopeDenied):
        resolve_tool_files(records, "user", [1], ["reports/a.txt"], context="context")


def test_s3_bucket_is_part_of_query_and_not_inferred_from_filename(mocker, records):
    mocker.patch("management.services.knowledge_base.tool_files.KnowledgeFileAuthorization")
    refs = resolve_tool_files(records, "user", [1], ["s3://bucket/reports/a.txt"], context="context")
    assert refs[0].file_version == 3
    choice = records.query.call_args.args[1].where.terms[-1].terms[0]
    assert choice.terms[0].field == "bucket_name" and choice.terms[0].value == "bucket"


@pytest.mark.parametrize("paths", [["http://example.test/a"], ["s3://bucket/a?token=secret"], [""]])
def test_unsupported_source_selectors_do_not_issue_queries(records, paths):
    with pytest.raises(ScopeDenied):
        resolve_tool_files(records, "user", [1], paths, context="context")
    records.query.assert_not_called()


def test_preparation_owns_only_explicit_file_catalog_context(mocker, records):
    from contextlib import nullcontext

    from management.services.knowledge_base import tool_files

    mocker.patch.object(tool_files, "KnowledgeFileAuthorization")
    factory = mocker.patch.object(tool_files, "knowledge_resource_ports", return_value=nullcontext(records))
    refs = tool_files.prepare_tool_files("user", "tenant", [1], ["reports/a.txt"], context="context")
    assert refs[0].file_version == 3
    factory.assert_called_once_with("tenant", "user", context="context", include_files=True)
