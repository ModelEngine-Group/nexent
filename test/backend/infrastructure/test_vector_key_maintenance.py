# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Single-key maintenance preserves generation, scope and atomic provider versions."""

from dataclasses import replace
from unittest.mock import Mock

import pytest
from elastic_transport import TransportError
from nexent.storage.errors import (
    CapabilityUnsupported,
    Conflict,
    OutcomeUnknown,
    ScopeDenied,
)
from nexent.storage.models import Revision, VectorKey

from infrastructure.vdb.vector_store import ElasticsearchVectorStore
from test.backend.infrastructure.test_vector_payload_patch import (
    api_error,
    context,
)
from test.backend.infrastructure.test_vector_payload_patch import (
    editable as editable,  # noqa: PLC0414
)


def test_payload_get_does_not_request_or_validate_embeddings(editable):
    port, client, _, _ = editable
    row = port.get(VectorKey("kb", "chunk"), include_vector=False, context=context())
    assert row.vector == () and row.payload["content"] == "before"
    assert row.generation == Revision("published")
    assert "embedding" not in client.get.call_args.kwargs["source_includes"]
    client.close.assert_called_once()
    with pytest.raises(CapabilityUnsupported):
        port.get(VectorKey("kb", "chunk"), context=context())


def test_delete_key_uses_generation_and_native_cas_once(editable):
    port, client, _, _ = editable
    client.delete.return_value = {"result": "deleted"}
    receipt = port.delete_key(
        VectorKey("kb", "chunk"),
        expected_generation=Revision("published"),
        context=context(),
    )
    assert receipt.deleted
    args = client.delete.call_args.kwargs
    assert args["if_seq_no"] == 7 and args["if_primary_term"] == 2
    assert args["id"] == port._key("kb", "chunk")
    assert "embedding" not in client.get.call_args.kwargs["source_includes"]
    assert client.delete.call_count == 1
    client.close.assert_called_once()


@pytest.mark.parametrize("phase", ["get", "delete"])
def test_missing_single_key_returns_not_matched(editable, phase):
    port, client, _, _ = editable
    getattr(client, phase).side_effect = api_error(404)
    assert not port.delete_key(
        VectorKey("kb", "chunk"),
        expected_generation=Revision("published"),
        context=context(),
    ).deleted
    if phase == "get":
        client.delete.assert_not_called()
    client.close.assert_called_once()


def test_changed_generation_refuses_delete_before_transport(editable):
    port, client, _, _ = editable
    with pytest.raises(Conflict):
        port.delete_key(
            VectorKey("kb", "chunk"),
            expected_generation=Revision("new"),
            context=context(),
        )
    client.delete.assert_not_called()


@pytest.mark.parametrize(
    "error", [api_error(409), TransportError("lost"), api_error(503)]
)
def test_conflict_or_unknown_delete_is_never_replayed(editable, error):
    port, client, _, _ = editable
    client.delete.side_effect = error
    expected = (
        Conflict if getattr(error, "status_code", None) == 409 else OutcomeUnknown
    )
    with pytest.raises(expected):
        port.delete_key(
            VectorKey("kb", "chunk"),
            expected_generation=Revision("published"),
            context=context(),
        )
    assert client.delete.call_count == 1
    client.close.assert_called_once()


def test_readonly_binding_cannot_delete_a_key(editable):
    port, _, _, binding = editable
    factory = Mock()
    readonly = ElasticsearchVectorStore(
        port.scope, (replace(binding, writable=False),), factory
    )
    with pytest.raises(ScopeDenied):
        readonly.delete_key(
            VectorKey("kb", "chunk"),
            expected_generation=Revision("published"),
            context=context(),
        )
    factory.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    [("_si_tenant", "foreign"), ("_si_key", "other"), ("_si_collection", "other")],
)
def test_foreign_source_cannot_be_deleted(editable, field, value):
    port, client, _, _ = editable
    client.get.return_value["_source"][field] = value
    with pytest.raises(ScopeDenied):
        port.delete_key(
            VectorKey("kb", "chunk"),
            expected_generation=Revision("published"),
            context=context(),
        )
    client.delete.assert_not_called()


def test_none_generation_does_not_bypass_existing_generation(editable):
    port, client, _, _ = editable
    with pytest.raises(Conflict):
        port.delete_key(
            VectorKey("kb", "chunk"), expected_generation=None, context=context()
        )
    client.delete.assert_not_called()
    client.get.return_value["_source"].pop("_si_generation")
    client.delete.return_value = {"result": "deleted"}
    assert port.delete_key(
        VectorKey("kb", "chunk"), expected_generation=None, context=context()
    ).deleted


def test_invalid_delete_receipt_stays_unknown(editable):
    port, client, _, _ = editable
    client.delete.return_value = {"result": "unexpected"}
    with pytest.raises(OutcomeUnknown):
        port.delete_key(
            VectorKey("kb", "chunk"),
            expected_generation=Revision("published"),
            context=context(),
        )
    assert client.delete.call_count == 1
