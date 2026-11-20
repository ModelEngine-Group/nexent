# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Payload edits preserve vectors and identities and never replay unknown writes."""

from dataclasses import replace
from time import monotonic
from unittest.mock import Mock

import pytest
from elastic_transport import ApiResponseMeta, NodeConfig, TransportError
from elasticsearch import ApiError
from nexent.storage.errors import (
    CapabilityUnsupported,
    Conflict,
    DeadlineExceeded,
    InvalidInput,
    OutcomeUnknown,
    ScopeDenied,
    Unavailable,
)
from nexent.storage.models import (
    FieldPatch,
    OperationContext,
    Revision,
    StorageScope,
    VectorKey,
)

from infrastructure.storage.catalog import FieldDefinition
from infrastructure.vdb.vector_schema import VectorBinding
from infrastructure.vdb.vector_store import ElasticsearchVectorStore


def context():
    return OperationContext("payload-patch", monotonic() + 5)


def api_error(status):
    return ApiError(
        "provider error",
        ApiResponseMeta(status, "1.1", {}, 0, NodeConfig("http", "localhost", 9200)),
        {},
    )


@pytest.fixture
def editable():
    client = Mock()
    client.options.return_value = client
    client.get.return_value = {
        "_seq_no": 7,
        "_primary_term": 2,
        "_source": {
            "_si_tenant": "tenant-a",
            "_si_collection": "kb",
            "_si_key": "chunk",
            "_si_generation": "published",
            "payload": {
                "content": "before",
                "file_id": "file",
                "location": {"old": "value", "keep": True},
            },
        },
    }
    client.update.return_value = {"result": "updated"}
    binding = VectorBinding(
        "kb",
        "payload-proof",
        None,
        (
            FieldDefinition("content", "string"),
            FieldDefinition("file_id", "string"),
            FieldDefinition("location", "object"),
        ),
        writable=True,
        mutable_fields=frozenset({"content", "location"}),
    )
    factory = Mock(return_value=client)
    port = ElasticsearchVectorStore(
        StorageScope("runtime", "tenant-a", "actor", {"kb"}), (binding,), factory
    )
    return port, client, factory, binding


def test_payload_edit_preserves_identity_and_uses_fixed_cas_script(editable):
    port, client, _, _ = editable
    receipt = port.patch_payload(
        VectorKey("kb", "chunk"),
        FieldPatch(
            set_values={"content": "ctx._source.clear()", "location": {"new": "only"}}
        ),
        expected_generation=Revision("published"),
        context=context(),
    )
    assert receipt.matched
    options = client.update.call_args.kwargs
    assert options["if_seq_no"] == 7 and options["if_primary_term"] == 2
    assert options["retry_on_conflict"] == 0 and options["scripted_upsert"] is False
    assert options["script"]["source"] == (
        'for (def field : params.values.keySet()) { ctx._source.payload[field] = params.values[field]; }'
    )
    assert options["script"]["params"]["values"] == {
        "content": "ctx._source.clear()",
        "location": {"new": "only"},
    }
    assert "embedding" not in client.get.call_args.kwargs["source_includes"]
    assert "vector.patch.payload" in port.capabilities.supported
    client.close.assert_called_once()


def test_payload_patch_rejects_changed_storage_revision_even_with_same_generation(editable):
    port, client, _, _ = editable
    with pytest.raises(Conflict):
        port.patch_payload(VectorKey("kb", "chunk"), FieldPatch(set_values={"content": "new"}),
                           expected_generation=Revision("published"),
                           expected_storage_revision=Revision("6:2"), context=context())
    client.update.assert_not_called()


@pytest.mark.parametrize(
    "patch",
    [
        FieldPatch(set_values={"file_id": "other"}),
        FieldPatch(set_values={"_si_generation": "other"}),
        FieldPatch(set_values={"content": None}),
        FieldPatch(),
    ],
)
def test_invalid_or_protected_fields_do_not_open_transport(editable, patch):
    port, _, factory, _ = editable
    with pytest.raises((ScopeDenied, InvalidInput)):
        port.patch_payload(
            VectorKey("kb", "chunk"),
            patch,
            expected_generation=Revision("published"),
            context=context(),
        )
    factory.assert_not_called()


@pytest.mark.parametrize(
    "patch",
    [FieldPatch(unset_fields=("content",)), FieldPatch(increments={"count": 1})],
)
def test_unsupported_patch_operations_fail_before_transport(editable, patch):
    port, _, factory, _ = editable
    with pytest.raises(CapabilityUnsupported):
        port.patch_payload(
            VectorKey("kb", "chunk"),
            patch,
            expected_generation=Revision("published"),
            context=context(),
        )
    factory.assert_not_called()


def test_generation_mismatch_does_not_write(editable):
    port, client, _, _ = editable
    with pytest.raises(Conflict):
        port.patch_payload(
            VectorKey("kb", "chunk"),
            FieldPatch(set_values={"content": "after"}),
            expected_generation=Revision("stale"),
            context=context(),
        )
    client.update.assert_not_called()
    client.close.assert_called_once()


@pytest.mark.parametrize("phase", ["get", "update"])
def test_missing_or_concurrently_deleted_record_is_not_recreated(editable, phase):
    port, client, _, _ = editable
    getattr(client, phase).side_effect = api_error(404)
    assert not port.patch_payload(
        VectorKey("kb", "chunk"),
        FieldPatch(set_values={"content": "after"}),
        expected_generation=Revision("published"),
        context=context(),
    ).matched
    assert client.update.call_count == (phase == "update")
    client.index.assert_not_called()
    client.bulk.assert_not_called()
    client.close.assert_called_once()


def test_concurrent_write_conflict_is_not_replayed(editable):
    port, client, _, _ = editable
    client.update.side_effect = api_error(409)
    with pytest.raises(Conflict):
        port.patch_payload(
            VectorKey("kb", "chunk"),
            FieldPatch(set_values={"content": "after"}),
            expected_generation=Revision("published"),
            context=context(),
        )
    assert client.update.call_count == 1 and client.get.call_count == 1


def test_unknown_update_outcome_is_not_replayed(editable):
    port, client, _, _ = editable
    client.update.side_effect = TransportError("private diagnostic")
    with pytest.raises(OutcomeUnknown):
        port.patch_payload(
            VectorKey("kb", "chunk"),
            FieldPatch(set_values={"content": "after"}),
            expected_generation=Revision("published"),
            context=context(),
        )
    assert client.update.call_count == 1 and client.get.call_count == 1
    assert all(
        call.kwargs["max_retries"] == 0 and call.kwargs["retry_on_timeout"] is False
        for call in client.options.call_args_list
    )
    client.close.assert_called_once()


def test_missing_internal_version_prevents_blind_update(editable):
    port, client, _, _ = editable
    client.get.return_value.pop("_primary_term")
    with pytest.raises(Unavailable):
        port.patch_payload(
            VectorKey("kb", "chunk"),
            FieldPatch(set_values={"content": "after"}),
            expected_generation=Revision("published"),
            context=context(),
        )
    client.update.assert_not_called()


@pytest.mark.parametrize(
    "writable,fields", [(False, frozenset({"content"})), (True, frozenset())]
)
def test_no_implicit_edit_permission(editable, writable, fields):
    _, _, factory, binding = editable
    port = ElasticsearchVectorStore(
        StorageScope("runtime", "tenant-a", "actor", {"kb"}),
        (replace(binding, writable=writable, mutable_fields=fields),),
        factory,
    )
    assert "vector.patch.payload" not in port.capabilities.supported
    with pytest.raises((ScopeDenied, CapabilityUnsupported)):
        port.patch_payload(
            VectorKey("kb", "chunk"),
            FieldPatch(set_values={"content": "after"}),
            expected_generation=Revision("published"),
            context=context(),
        )
    factory.assert_not_called()


@pytest.mark.parametrize(
    "name,value",
    [("_si_tenant", "other"), ("_si_collection", "other"), ("_si_key", "other")],
)
def test_provider_identity_mismatch_prevents_edit(editable, name, value):
    port, client, _, _ = editable
    client.get.return_value["_source"][name] = value
    with pytest.raises(ScopeDenied):
        port.patch_payload(
            VectorKey("kb", "chunk"),
            FieldPatch(set_values={"content": "after"}),
            expected_generation=Revision("published"),
            context=context(),
        )
    client.update.assert_not_called()


def test_expired_operation_does_not_open_transport(editable):
    port, _, factory, _ = editable
    with pytest.raises(DeadlineExceeded):
        port.patch_payload(
            VectorKey("kb", "chunk"),
            FieldPatch(set_values={"content": "after"}),
            expected_generation=Revision("published"),
            context=OperationContext("expired", monotonic() - 1),
        )
    factory.assert_not_called()


def test_response_after_total_deadline_is_unknown_not_success(editable):
    port, client, _, _ = editable

    class Budget:
        operation_id = "late-update"
        expired = False

        def remaining(self):
            if self.expired:
                raise DeadlineExceeded()
            return 5

    budget = Budget()

    def late_response(**kwargs):
        budget.expired = True
        return {"result": "updated"}

    client.update.side_effect = late_response
    with pytest.raises(OutcomeUnknown):
        port.patch_payload(
            VectorKey("kb", "chunk"),
            FieldPatch(set_values={"content": "after"}),
            expected_generation=Revision("published"),
            context=budget,
        )
    assert client.update.call_count == 1
    client.close.assert_called_once()


def test_explicit_none_only_matches_record_without_generation(editable):
    port, client, _, _ = editable
    client.get.return_value["_source"].pop("_si_generation")
    assert port.patch_payload(
        VectorKey("kb", "chunk"),
        FieldPatch(set_values={"content": "after"}),
        expected_generation=None,
        context=context(),
    ).matched


@pytest.mark.parametrize("fields", ["content", frozenset({"unknown"}), [42]])
def test_invalid_mutable_field_policy_is_rejected(editable, fields):
    *_, binding = editable
    with pytest.raises(InvalidInput):
        replace(binding, mutable_fields=fields)
