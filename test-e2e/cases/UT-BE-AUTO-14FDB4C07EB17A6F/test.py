from __future__ import annotations

import pytest

from management.services.knowledge_base import common
from management.services.knowledge_base.common import get_embedding_model_by_index_name

TENANT_ID = "tenant-a"
INDEX_NAME = "kb-index-1"
VALID_MODEL_ID = 987654


@pytest.mark.case_id("UT-BE-AUTO-14FDB4C07EB17A6F")
@pytest.mark.stage("D1")
def test_get_embedding_model_by_index_name_explicit_resolution(monkeypatch):
    model_instance = object()

    def install(get_record, get_model):
        invocations = []

        def fake_get_knowledge_record(query):
            return get_record()

        def fake_get_embedding_model_by_id(tenant_id, model_id):
            invocations.append(model_id)
            return get_model(model_id)

        monkeypatch.setattr(common, "get_knowledge_record", fake_get_knowledge_record)
        monkeypatch.setattr(common, "get_embedding_model_by_id", fake_get_embedding_model_by_id)
        return invocations

    invocations = install(
        lambda: {"embedding_model_id": VALID_MODEL_ID},
        lambda model_id: (model_instance, VALID_MODEL_ID),
    )
    model, model_id, meta = get_embedding_model_by_index_name(TENANT_ID, INDEX_NAME)
    assert model is model_instance
    assert model_id == VALID_MODEL_ID
    assert meta["status"] == "ok"
    assert meta["needs_update"] is False
    assert invocations == [VALID_MODEL_ID]

    invocations = install(
        lambda: {"embedding_model_id": None},
        lambda model_id: (model_instance, VALID_MODEL_ID),
    )
    model, model_id, meta = get_embedding_model_by_index_name(TENANT_ID, INDEX_NAME)
    assert model is None
    assert model_id is None
    assert meta["status"] == "needs_config"
    assert meta["needs_update"] is False
    assert invocations == []

    invocations = install(
        lambda: {"embedding_model_id": VALID_MODEL_ID},
        lambda model_id: (None, None),
    )
    model, model_id, meta = get_embedding_model_by_index_name(TENANT_ID, INDEX_NAME)
    assert model is None
    assert model_id is None
    assert meta["status"] == "needs_config"
    assert meta["needs_update"] is False
    assert invocations == [VALID_MODEL_ID]

    invocations = install(
        lambda: {},
        lambda model_id: (model_instance, VALID_MODEL_ID),
    )
    model, model_id, meta = get_embedding_model_by_index_name(TENANT_ID, INDEX_NAME)
    assert model is None
    assert model_id is None
    assert meta["status"] == "error"
    assert "not found" in meta["message"]
    assert invocations == []

    error = RuntimeError("database connection failed")

    def raise_get_record():
        raise error

    invocations = install(
        raise_get_record,
        lambda model_id: (model_instance, VALID_MODEL_ID),
    )
    model, model_id, meta = get_embedding_model_by_index_name(TENANT_ID, INDEX_NAME)
    assert model is None
    assert model_id is None
    assert meta["status"] == "error"
    assert meta["message"] == str(error)
    assert invocations == []
