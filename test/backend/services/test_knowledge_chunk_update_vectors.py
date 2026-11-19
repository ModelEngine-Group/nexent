# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-UPDATE-VECTOR-01/02 replace explicit vectors under the real journal."""

from unittest.mock import Mock

import pytest
from nexent.storage.errors import Conflict, InvalidInput, NotFound, OutcomeUnknown
from nexent.storage.models import WriteReceipt

from test.backend.services.test_knowledge_chunk_executor import context
from test.backend.services.test_knowledge_chunk_executor import (
    executor as executor,  # noqa: PLC0414
)
from test.backend.services.test_knowledge_chunk_executor import (
    lifecycle as lifecycle,  # noqa: PLC0414
)


def update(value, **changes):
    return value.model_copy(update={"changes": {"content": "new", "embedding": [0.0, 1.0, 0.0], **changes}})


def test_explicit_vector_and_payload_are_replaced_once_without_reading_old_vector(executor):
    _s, service, vectors, value = executor
    original = vectors.get.return_value
    original.payload.update(embedding_model_id=2, embedding_revision="r1", parser_version="v2")
    vectors.put.return_value = WriteReceipt("put", True)
    result = service.execute(update(value), context=context())
    assert result["status"] == "completed" and result["count_delta"] == 0
    record = vectors.put.call_args.args[0]
    assert record.vector == (0.0, 1.0, 0.0) and record.payload == {**original.payload, "content": "new"}
    assert record.key == original.key and record.generation == original.generation
    assert vectors.put.call_args.kwargs["expected_generation"] == original.generation
    assert vectors.get.call_args.kwargs["include_vector"] is False
    vectors.ensure_collection.assert_called_once_with("collection", context=vectors.put.call_args.kwargs["context"])
    vectors.patch_payload.assert_not_called()
    assert service.execute(update(value), context=context())["mutation_id"] == result["mutation_id"]
    assert vectors.put.call_count == 1


@pytest.mark.parametrize("vector", [None, [], [0, 0], [True, 1], "bad", {"bad": 1}])
def test_invalid_explicit_vector_is_rejected_before_admission_or_storage(executor, vector):
    s, service, vectors, value = executor
    with pytest.raises(InvalidInput):
        service.execute(update(value, embedding=vector), context=context())
    vectors.get.assert_not_called()
    vectors.ensure_collection.assert_not_called()
    vectors.put.assert_not_called()
    assert s.mutation.revision(context=context()) == 0


def test_missing_record_never_creates_collection_or_document(executor):
    s, service, vectors, value = executor
    vectors.get.return_value = None
    with pytest.raises(NotFound):
        service.execute(update(value), context=context())
    vectors.ensure_collection.assert_not_called()
    vectors.put.assert_not_called()
    s.mutation.assert_drained(context=context())


@pytest.mark.parametrize("failure,expected", [(Conflict(), "failed"), (OutcomeUnknown(), "unknown")])
def test_provider_failure_is_recorded_without_a_second_put(executor, failure, expected):
    s, service, vectors, value = executor
    vectors.put.side_effect = failure
    with pytest.raises(type(failure)):
        service.execute(update(value), context=context())
    result = service.execute(update(value), context=context())
    assert result["status"] == expected and result["count_delta"] is None
    assert vectors.put.call_count == 1
    if expected == "failed":
        s.mutation.assert_drained(context=context())
    else:
        with pytest.raises(Conflict):
            s.mutation.assert_drained(context=context())


def test_lost_ledger_ack_does_not_replay_vector_update(executor, monkeypatch):
    s, service, vectors, value = executor
    vectors.put.return_value = WriteReceipt("put", True)
    monkeypatch.setattr(s.mutation, "complete", Mock(side_effect=OutcomeUnknown()))
    with pytest.raises(OutcomeUnknown):
        service.execute(update(value), context=context())
    assert service.execute(update(value), context=context())["status"] == "writing"
    assert vectors.put.call_count == 1
