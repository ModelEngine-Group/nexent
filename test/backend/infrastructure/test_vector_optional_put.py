# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Explicit payload-only storage upgrades without fake vectors, blind writes or index replacement."""

from dataclasses import replace
from unittest.mock import Mock

import pytest
from elastic_transport import TransportError
from nexent.storage.errors import (
    CapabilityUnsupported,
    Conflict,
    InvalidInput,
    OutcomeUnknown,
    ScopeDenied,
)
from nexent.storage.models import Revision, StorageScope, VectorKey, VectorRecord

from infrastructure.storage.catalog import FieldDefinition
from infrastructure.vdb.vector_schema import VectorBinding
from infrastructure.vdb.vector_store import ElasticsearchVectorStore
from test.backend.infrastructure.test_vector_payload_patch import api_error, context


@pytest.fixture
def optional():
    binding = VectorBinding(
        "kb",
        "optional-proof",
        None,
        (
            FieldDefinition("content", "string"),
            FieldDefinition("file_id", "string", nullable=True),
        ),
        writable=True,
        allow_unembedded=True,
    )
    client = Mock()
    client.options.return_value = client
    client.index.return_value = {"result": "created"}
    client.indices.exists.return_value = True
    client.indices.get_mapping.return_value = {
        binding.index: {"mappings": binding.mapping()}
    }
    client.get.return_value = {
        "_seq_no": 3,
        "_primary_term": 1,
        "_source": {
            "_si_tenant": "tenant",
            "_si_collection": "kb",
            "_si_key": "key",
            "_si_generation": "old",
            "payload": {"content": "before", "file_id": None},
        },
    }
    factory = Mock(return_value=client)
    port = ElasticsearchVectorStore(
        StorageScope("runtime", "tenant", "actor", {"kb"}), (binding,), factory
    )
    row = VectorRecord(
        VectorKey("kb", "key"),
        (),
        {"content": "plain", "file_id": None},
        Revision("new"),
    )
    return port, client, factory, binding, row


def test_plaintext_create_has_no_embedding_and_uses_create_condition(optional):
    port, client, _, _, row = optional
    assert port.put(row, expected_generation=None, context=context()).matched
    args = client.index.call_args.kwargs
    assert args["op_type"] == "create"
    assert "embedding" not in args["document"]
    assert args["document"]["payload"] == row.payload
    client.get.assert_not_called()
    client.close.assert_called_once()


def test_conditioned_replace_uses_generation_and_native_cas(optional):
    port, client, _, _, row = optional
    client.index.return_value = {"result": "updated"}
    assert port.put(row, expected_generation=Revision("old"), context=context()).matched
    args = client.index.call_args.kwargs
    assert (args["if_seq_no"], args["if_primary_term"]) == (3, 1)
    assert "op_type" not in args


@pytest.mark.parametrize("error", [api_error(409), TransportError("lost")])
def test_create_conflict_or_unknown_never_replays(optional, error):
    port, client, _, _, row = optional
    client.index.side_effect = error
    with pytest.raises(
        Conflict if isinstance(error, type(api_error(409))) else OutcomeUnknown
    ):
        port.put(row, expected_generation=None, context=context())
    assert client.index.call_count == 1


def test_missing_or_changed_generation_does_not_replace(optional):
    port, client, _, _, row = optional
    with pytest.raises(Conflict):
        port.put(row, expected_generation=Revision("changed"), context=context())
    client.get.side_effect = api_error(404)
    with pytest.raises(Conflict):
        port.put(row, expected_generation=Revision("old"), context=context())
    client.index.assert_not_called()


def test_unexpected_write_result_is_unknown(optional):
    port, client, _, _, row = optional
    client.index.return_value = {"result": "updated"}
    with pytest.raises(OutcomeUnknown):
        port.put(row, expected_generation=None, context=context())


def test_plaintext_requires_explicit_policy_and_strict_upsert_stays_strict(optional):
    port, client, factory, binding, row = optional
    strict = ElasticsearchVectorStore(
        port.scope, (replace(binding, dimensions=3, allow_unembedded=False),), factory
    )
    with pytest.raises(InvalidInput):
        strict.put(row, expected_generation=None, context=context())
    with pytest.raises(CapabilityUnsupported):
        port.upsert((row,), context=context())
    factory.assert_not_called()
    client.index.assert_not_called()


def test_payload_only_collection_is_explicit_and_describes_no_dimension(optional):
    port, client, _, binding, _ = optional
    client.indices.exists.return_value = False
    client.indices.create.return_value = {"acknowledged": True}
    info = port.ensure_collection("kb", context=context())
    assert info.dimensions is None
    mapping = client.indices.create.call_args.kwargs["mappings"]
    assert "embedding" not in mapping["properties"] and mapping["dynamic"] == "strict"
    assert mapping == binding.mapping()


def test_known_dimension_only_adds_missing_embedding_mapping(optional):
    port, client, factory, binding, _ = optional
    known = replace(binding, dimensions=3)
    client.indices.put_mapping.return_value = {"acknowledged": True}
    client.indices.get_mapping.side_effect = [
        {binding.index: {"mappings": binding.mapping()}},
        {binding.index: {"mappings": known.mapping()}},
    ]
    writable = ElasticsearchVectorStore(port.scope, (known,), factory)
    assert writable.ensure_collection("kb", context=context()).dimensions == 3
    assert set(client.indices.put_mapping.call_args.kwargs["properties"]) == {
        "embedding"
    }
    client.indices.create.assert_not_called()
    client.indices.delete.assert_not_called()


def test_existing_different_vector_dimension_is_not_changed(optional):
    port, client, factory, binding, _ = optional
    wanted = replace(binding, dimensions=3)
    client.indices.get_mapping.return_value = {
        binding.index: {"mappings": replace(binding, dimensions=4).mapping()}
    }
    writable = ElasticsearchVectorStore(port.scope, (wanted,), factory)
    with pytest.raises(Conflict):
        writable.ensure_collection("kb", context=context())
    client.indices.put_mapping.assert_not_called()
    client.indices.delete.assert_not_called()


def test_mismatched_payload_mapping_cannot_be_upgraded(optional):
    port, client, factory, binding, _ = optional
    actual = binding.mapping()
    actual["properties"]["payload"]["properties"]["content"] = {"type": "keyword"}
    client.indices.get_mapping.return_value = {binding.index: {"mappings": actual}}
    writable = ElasticsearchVectorStore(
        port.scope, (replace(binding, dimensions=3),), factory
    )
    with pytest.raises(Conflict):
        writable.ensure_collection("kb", context=context())
    client.indices.put_mapping.assert_not_called()


def test_optional_payload_put_also_supports_real_vectors(optional):
    port, client, factory, binding, row = optional
    writable = ElasticsearchVectorStore(
        port.scope, (replace(binding, dimensions=3),), factory
    )
    assert writable.put(
        replace(row, vector=(1.0, 0.0, 0.0)),
        expected_generation=None,
        context=context(),
    ).matched
    assert client.index.call_args.kwargs["document"]["embedding"] == (1.0, 0.0, 0.0)


def test_metadata_view_reports_existing_real_dimensions_without_changing_them(optional):
    port, client, _, binding, _ = optional
    client.indices.get_mapping.return_value = {
        binding.index: {"mappings": replace(binding, dimensions=4).mapping()}
    }
    assert port.describe_collection("kb", context=context()).dimensions == 4
    client.indices.put_mapping.assert_not_called()


@pytest.mark.parametrize("acknowledged", [False, None])
def test_unknown_mapping_upgrade_ack_is_not_replayed(optional, acknowledged):
    port, client, factory, binding, _ = optional
    client.indices.put_mapping.return_value = {"acknowledged": acknowledged}
    writable = ElasticsearchVectorStore(
        port.scope, (replace(binding, dimensions=3),), factory
    )
    with pytest.raises(OutcomeUnknown):
        writable.ensure_collection("kb", context=context())
    assert client.indices.put_mapping.call_count == 1


def test_readonly_plaintext_binding_cannot_write(optional):
    port, _, factory, binding, row = optional
    readonly = ElasticsearchVectorStore(
        port.scope, (replace(binding, writable=False),), factory
    )
    with pytest.raises(ScopeDenied):
        readonly.put(row, expected_generation=None, context=context())
    factory.assert_not_called()


def test_missing_dimensions_are_not_guessed_for_supplied_vector(optional):
    port, _, factory, _, row = optional
    with pytest.raises(CapabilityUnsupported):
        port.put(
            replace(row, vector=(1.0, 0.0, 0.0)),
            expected_generation=None,
            context=context(),
        )
    factory.assert_not_called()


@pytest.mark.parametrize("policy", [None, 1, "true"])
def test_optional_policy_requires_an_actual_boolean(optional, policy):
    with pytest.raises(InvalidInput):
        replace(optional[3], allow_unembedded=policy)


def test_kb_maintenance_does_not_inherit_plaintext_creation_power(monkeypatch):
    from infrastructure import knowledge_vectors
    from infrastructure.agentos_identity import ServicePrincipal

    factory = Mock()
    monkeypatch.setattr(knowledge_vectors, "_configured_client", factory)
    actor = ServicePrincipal("actor", "tenant")
    port = knowledge_vectors.bind_knowledge_chunk_vectors(actor, "kb")
    try:
        with pytest.raises(CapabilityUnsupported):
            port.ensure_collection("kb", context=context())
        with pytest.raises(CapabilityUnsupported):
            port.put(
                VectorRecord(VectorKey("kb", "key"), (), {}),
                expected_generation=None,
                context=context(),
            )
        factory.assert_not_called()
    finally:
        port.close()


@pytest.mark.parametrize("mapping", [None, {"properties": None}])
def test_malformed_existing_mapping_refuses_upgrade_without_write(optional, mapping):
    port, client, factory, binding, _ = optional
    client.indices.get_mapping.return_value = {binding.index: {"mappings": mapping}}
    writable = ElasticsearchVectorStore(port.scope, (replace(binding, dimensions=3),), factory)
    with pytest.raises(Conflict):
        writable.ensure_collection("kb", context=context())
    client.indices.put_mapping.assert_not_called()
    client.indices.delete.assert_not_called()
