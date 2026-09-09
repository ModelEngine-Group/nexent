import pytest
from services import tag_document_projection as projection_module
from services.tag_document_projection import (
    AIDP_DOCUMENT_PROVIDER,
    STATUS_FAILED,
    STATUS_SYNCED,
    STATUS_UNSUPPORTED,
    AidpDocumentProjectionProvider,
    DocumentTagProjectionUnsupported,
    LocalElasticsearchDocumentProjectionProvider,
    clear_document_projection,
    decode_document_resource_id,
    filter_document_ids_by_predicates,
    get_document_projection_status,
    get_projection_provider,
    project_document_assignments,
    retry_pending_document_projections,
)
from services.tag_management_service import TagManagementService
from services.tag_resource_adapters import (
    AuthenticatedCaller,
    CanonicalResourceIdentity,
    ResolvedTagResource,
    ResourceCapabilities,
    ResourceType,
    _encode_document_resource_id,
)


def _assignments():
    return [
        {
            "definition_id": 11,
            "definition_key": "Keywords",
            "definition_name": "Keywords",
            "value_id": 21,
            "display_value": "red",
        }
    ]


class _Registry:
    def __init__(self, resource):
        self.resource = resource

    async def resolve(self, reference, caller):
        return self.resource


def test_local_projection_success_records_synced(monkeypatch):
    assignments = _assignments()
    monkeypatch.setattr(
        projection_module.TagManagementDB,
        "list_resource_assignments",
        lambda *args, **kwargs: assignments,
    )
    monkeypatch.setattr(
        projection_module.document_tag_projection_db,
        "get_projection_state",
        lambda *args, **kwargs: None,
    )
    captured = {}

    def fake_upsert(**kwargs):
        captured.update(kwargs)
        return {**kwargs, "payload": kwargs["payload"]}

    monkeypatch.setattr(
        projection_module.document_tag_projection_db,
        "upsert_projection_state",
        fake_upsert,
    )
    projected = []

    class FakeProvider:
        provider_name = "local"

        def capability(self):
            return "full"

        def project(self, payload):
            projected.append(payload)

        def clear(self, resource_id):
            pass

    monkeypatch.setattr(
        projection_module, "get_projection_provider", lambda *args, **kwargs: FakeProvider()
    )

    result = project_document_assignments("t1", "local", "kb-1", "doc-a", "user-1")

    assert result["status"] == STATUS_SYNCED
    assert result["tag_count"] == 1
    assert result["version"] == 1
    assert captured["version"] == 1
    assert captured["status"] == STATUS_SYNCED
    assert projected[0]["tags"] == assignments
    assert projected[0]["resource_id"] == captured["resource_id"]
    assert projected[0]["tenant_id"] == "t1"


def test_idempotent_rerun_keeps_version_and_skips_provider(monkeypatch):
    assignments = _assignments()
    monkeypatch.setattr(
        projection_module.TagManagementDB,
        "list_resource_assignments",
        lambda *args, **kwargs: assignments,
    )
    current = {
        "payload": assignments,
        "status": STATUS_SYNCED,
        "version": 3,
        "retry_count": 0,
        "last_error": None,
        "last_attempt_at": None,
        "next_attempt_at": None,
        "update_time": None,
    }
    monkeypatch.setattr(
        projection_module.document_tag_projection_db,
        "get_projection_state",
        lambda *args, **kwargs: current,
    )
    calls = []

    class FakeProvider:
        provider_name = "local"

        def capability(self):
            return "full"

        def project(self, payload):
            calls.append(payload)

        def clear(self, resource_id):
            pass

    monkeypatch.setattr(
        projection_module, "get_projection_provider", lambda *args, **kwargs: FakeProvider()
    )

    result = project_document_assignments("t1", "local", "kb-1", "doc-a", "user-1")

    assert result["status"] == STATUS_SYNCED
    assert result["version"] == 3
    assert calls == []


def test_provider_rejection_is_retryable_and_preserves_canonical_assignments(monkeypatch):
    assignments = _assignments()
    monkeypatch.setattr(
        projection_module.TagManagementDB,
        "list_resource_assignments",
        lambda *args, **kwargs: assignments,
    )
    current = {
        "payload": [],
        "status": STATUS_FAILED,
        "version": 1,
        "retry_count": 1,
        "last_error": None,
        "last_attempt_at": None,
        "next_attempt_at": None,
        "update_time": None,
    }
    monkeypatch.setattr(
        projection_module.document_tag_projection_db,
        "get_projection_state",
        lambda *args, **kwargs: current,
    )
    captured = {}

    def fake_upsert(**kwargs):
        captured.update(kwargs)
        return {**kwargs, "payload": kwargs["payload"]}

    monkeypatch.setattr(
        projection_module.document_tag_projection_db,
        "upsert_projection_state",
        fake_upsert,
    )
    projected = []

    class FailingProvider:
        provider_name = "local"

        def capability(self):
            return "full"

        def project(self, payload):
            projected.append(payload)
            raise RuntimeError("es unavailable")

        def clear(self, resource_id):
            pass

    monkeypatch.setattr(
        projection_module, "get_projection_provider", lambda *args, **kwargs: FailingProvider()
    )

    result = project_document_assignments("t1", "local", "kb-1", "doc-a", "user-1")

    assert result["status"] == STATUS_FAILED
    assert result["retry_count"] == 2
    assert result["next_attempt_at"] is not None
    assert captured["last_error"] == "es unavailable"
    assert captured["status"] == STATUS_FAILED
    assert projected[0]["tags"] == assignments
    assert assignments == _assignments()


def test_aidp_provider_records_unsupported(monkeypatch):
    monkeypatch.setattr(
        projection_module.TagManagementDB,
        "list_resource_assignments",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        projection_module.document_tag_projection_db,
        "get_projection_state",
        lambda *args, **kwargs: None,
    )
    captured = {}

    def fake_upsert(**kwargs):
        captured.update(kwargs)
        return {**kwargs, "payload": kwargs["payload"]}

    monkeypatch.setattr(
        projection_module.document_tag_projection_db,
        "upsert_projection_state",
        fake_upsert,
    )
    calls = []

    class FakeAidp:
        provider_name = AIDP_DOCUMENT_PROVIDER

        def capability(self):
            return "unsupported"

        def project(self, payload):
            calls.append(payload)

        def clear(self, resource_id):
            pass

    monkeypatch.setattr(
        projection_module, "get_projection_provider", lambda *args, **kwargs: FakeAidp()
    )

    result = project_document_assignments("t1", "aidp", "kb-9", "doc-9", "user-1")

    assert result["status"] == STATUS_UNSUPPORTED
    assert captured["status"] == STATUS_UNSUPPORTED
    assert calls == []


def test_local_provider_writes_and_clears_es_sidecar():
    class FakeCore:
        def __init__(self):
            self.created = []
            self.chunks = []
            self.deleted = []

        def create_index(self, name):
            self.created.append(name)

        def create_chunk(self, name, chunk):
            self.chunks.append((name, chunk))

        def delete_documents(self, name, path):
            self.deleted.append((name, path))
            return 1

    core = FakeCore()
    provider = LocalElasticsearchDocumentProjectionProvider(vdb_core=core)
    payload = {
        "resource_id": "rid-1",
        "provider_document_id": "doc-a",
        "tenant_id": "t1",
        "provider": "local",
        "knowledge_base_id": "kb-1",
        "version": 2,
        "tags": [{"definition_id": 1, "value_id": 2}],
    }

    provider.project(payload)

    assert core.created == ["nexent_tag_projection"]
    name, chunk = core.chunks[0]
    assert name == "nexent_tag_projection"
    assert chunk["id"] == "rid-1"
    assert chunk["path_or_url"] == "rid-1"
    assert chunk["metadata"]["tags"] == payload["tags"]
    assert chunk["metadata"]["version"] == 2

    provider.clear("rid-1")
    assert core.deleted == [("nexent_tag_projection", "rid-1")]


def test_aidp_provider_is_explicitly_unsupported():
    provider = AidpDocumentProjectionProvider()
    assert provider.capability() == "unsupported"
    provider.clear("rid-1")


def test_clear_document_projection_removes_ledger_and_provider(monkeypatch):
    cleared = []

    class FakeProvider:
        def clear(self, resource_id):
            cleared.append(resource_id)

    monkeypatch.setattr(
        projection_module, "get_projection_provider", lambda *args, **kwargs: FakeProvider()
    )
    monkeypatch.setattr(
        projection_module.document_tag_projection_db,
        "delete_projection_state",
        lambda *args, **kwargs: True,
    )

    result = clear_document_projection("t1", "local", "kb-1", "doc-a")

    assert result is True
    assert cleared == [_encode_document_resource_id("local", "kb-1", "doc-a")]


def test_clear_keeps_working_when_provider_clear_fails(monkeypatch):
    class FailingProvider:
        def clear(self, resource_id):
            raise RuntimeError("es down")

    monkeypatch.setattr(
        projection_module, "get_projection_provider", lambda *args, **kwargs: FailingProvider()
    )
    monkeypatch.setattr(
        projection_module.document_tag_projection_db,
        "delete_projection_state",
        lambda *args, **kwargs: True,
    )

    result = clear_document_projection("t1", "local", "kb-1", "doc-a")
    assert result is True


def test_status_not_projected_when_ledger_empty(monkeypatch):
    monkeypatch.setattr(
        projection_module.document_tag_projection_db,
        "get_projection_state",
        lambda *args, **kwargs: None,
    )

    result = get_document_projection_status("t1", "local", "kb-1", "doc-a")

    assert result["status"] == "not_projected"
    assert result["version"] == 0
    assert result["tag_count"] == 0


def test_filter_merges_same_definition_groups_and_normalizes_provider(monkeypatch):
    captured = {}

    def fake_filter(tenant_id, provider, knowledge_base_id, predicates):
        captured.update(
            tenant_id=tenant_id,
            provider=provider,
            knowledge_base_id=knowledge_base_id,
            predicates=predicates,
        )
        return ["rid-1"]

    monkeypatch.setattr(
        projection_module.document_tag_projection_db,
        "filter_document_ids_by_predicates",
        fake_filter,
    )

    result = filter_document_ids_by_predicates(
        "t1",
        "LOCAL",
        "kb-1",
        [
            {"definition_id": 5, "value_ids": [1, 2]},
            {"definition_id": 5, "value_ids": [3]},
            {"definition_id": 9, "value_ids": []},
        ],
    )

    assert result == ["rid-1"]
    assert captured["tenant_id"] == "t1"
    assert captured["provider"] == "local"
    assert captured["predicates"] == [{"definition_id": 5, "value_ids": [1, 2, 3]}]


def test_retry_pending_projections_attempts_due_rows(monkeypatch):
    monkeypatch.setattr(
        projection_module.document_tag_projection_db,
        "list_due_projection_states",
        lambda *args, **kwargs: [
            {
                "tenant_id": "t1",
                "provider": "local",
                "knowledge_base_id": "kb-1",
                "provider_document_id": "d1",
            },
            {
                "tenant_id": "t1",
                "provider": "local",
                "knowledge_base_id": "kb-1",
                "provider_document_id": "d2",
            },
        ],
    )

    def fake_project(tenant_id, provider, kb, doc, actor, **kwargs):
        return {"status": STATUS_SYNCED if doc == "d1" else STATUS_FAILED}

    monkeypatch.setattr(
        projection_module, "project_document_assignments", fake_project
    )

    result = retry_pending_document_projections(tenant_id="t1")

    assert result == {"attempted": 2, "synced": 1, "failed": 1, "unsupported": 0}


def test_hybrid_search_applies_document_tag_predicates(monkeypatch):
    from management.services.knowledge_base.service import ElasticSearchService

    def fake_predicates(tenant_id, provider, knowledge_base_id, predicates):
        return [_encode_document_resource_id("local", knowledge_base_id, "docs/a.pdf")]

    monkeypatch.setattr(
        TagManagementService, "filter_document_ids_by_predicates", fake_predicates
    )
    monkeypatch.setattr(
        "management.services.knowledge_base.service.get_embedding_model_by_index_name",
        lambda *args, **kwargs: (object(), 1, {"status": "ok"}),
    )

    class FakeVdb:
        def hybrid_search(self, **kwargs):
            return [
                {
                    "document": {"path_or_url": "docs/a.pdf", "title": "A"},
                    "score": 1.0,
                    "index": "kb-1",
                },
                {
                    "document": {"path_or_url": "docs/b.pdf", "title": "B"},
                    "score": 0.9,
                    "index": "kb-1",
                },
            ]

    result = ElasticSearchService.search_hybrid(
        index_names=["kb-1"],
        query="query",
        tenant_id="t1",
        tag_predicates=[{"definition_id": 5, "value_ids": [1]}],
        vdb_core=FakeVdb(),
    )

    assert result["total"] == 1
    assert result["results"][0]["path_or_url"] == "docs/a.pdf"


def test_hybrid_search_without_predicates_keeps_all_results(monkeypatch):
    from management.services.knowledge_base.service import ElasticSearchService

    monkeypatch.setattr(
        "management.services.knowledge_base.service.get_embedding_model_by_index_name",
        lambda *args, **kwargs: (object(), 1, {"status": "ok"}),
    )

    class FakeVdb:
        def hybrid_search(self, **kwargs):
            return [
                {"document": {"path_or_url": "docs/a.pdf"}, "score": 1.0, "index": "kb-1"},
                {"document": {"path_or_url": "docs/b.pdf"}, "score": 0.9, "index": "kb-1"},
            ]

    result = ElasticSearchService.search_hybrid(
        index_names=["kb-1"],
        query="query",
        tenant_id="t1",
        vdb_core=FakeVdb(),
    )

    assert result["total"] == 2


def _document_resource():
    return ResolvedTagResource(
        found=True,
        identity=CanonicalResourceIdentity(
            ResourceType.KNOWLEDGE_DOCUMENT,
            "encoded-doc",
            "tenant-a",
            library_code="knowledge_content",
            provider="local",
            knowledge_base_id="kb-1",
            provider_document_id="doc-a",
        ),
        capabilities=ResourceCapabilities(can_read=True, can_edit=True),
    )


@pytest.mark.asyncio
async def test_replace_document_assignments_returns_projection_status(monkeypatch):
    monkeypatch.setattr(
        TagManagementService, "resource_adapter_registry", _Registry(_document_resource())
    )
    monkeypatch.setattr(
        "services.tag_management_service.TagManagementDB.replace_resource_assignments",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr("services.tag_management_service.TAG_DOCUMENT_PROJECTION_ENABLED", True)
    called = {}

    def fake_project(tenant_id, provider, kb, doc, actor, **kwargs):
        called.update(
            tenant_id=tenant_id, provider=provider, kb=kb, doc=doc, actor=actor
        )
        return {"status": STATUS_SYNCED, "version": 1, "tag_count": 0}

    monkeypatch.setattr(
        "services.tag_document_projection.project_document_assignments", fake_project
    )

    result = await TagManagementService.replace_resource_assignments(
        AuthenticatedCaller("user-a", "tenant-a", "DEV"),
        "knowledge_document",
        "encoded-doc",
        [1],
        provider="local",
        knowledge_base_id="kb-1",
    )

    assert result["projection_status"]["status"] == STATUS_SYNCED
    assert called == {
        "tenant_id": "tenant-a",
        "provider": "local",
        "kb": "kb-1",
        "doc": "doc-a",
        "actor": "user-a",
    }


@pytest.mark.asyncio
async def test_replace_non_document_skips_projection(monkeypatch):
    resource = ResolvedTagResource(
        found=True,
        identity=CanonicalResourceIdentity(ResourceType.SKILL, "12", "tenant-a"),
        capabilities=ResourceCapabilities(can_read=True, can_edit=True),
    )
    monkeypatch.setattr(
        TagManagementService, "resource_adapter_registry", _Registry(resource)
    )
    monkeypatch.setattr(
        "services.tag_management_service.TagManagementDB.replace_resource_assignments",
        lambda *args, **kwargs: [],
    )
    calls = []

    def fake_project(*args, **kwargs):
        calls.append(args)
        return {"status": STATUS_SYNCED}

    monkeypatch.setattr(
        "services.tag_document_projection.project_document_assignments", fake_project
    )

    result = await TagManagementService.replace_resource_assignments(
        AuthenticatedCaller("user-a", "tenant-a", "DEV"), "skill", "12", [7]
    )

    assert result["projection_status"] is None
    assert calls == []

from services.tag_document_projection import document_projection_status_dict


def test_document_projection_status_dict_formats_raw_state():
    state = {
        "status": "failed",
        "version": 3,
        "payload": [{"definition_id": 11, "value_id": 21}],
        "retry_count": 2,
        "last_error": "boom",
        "last_attempt_at": None,
        "next_attempt_at": None,
        "update_time": None,
    }
    result = document_projection_status_dict(state)
    assert result == {
        "status": "failed",
        "version": 3,
        "tag_count": 1,
        "last_error": "boom",
        "retry_count": 2,
        "last_attempt_at": None,
        "next_attempt_at": None,
        "update_time": None,
    }


def test_document_projection_status_dict_handles_missing_state():
    result = document_projection_status_dict(None)
    assert result == {
        "status": "not_projected",
        "version": 0,
        "tag_count": 0,
        "last_error": None,
        "retry_count": 0,
        "last_attempt_at": None,
        "next_attempt_at": None,
        "update_time": None,
    }


def test_provider_core_falls_back_to_vector_db(monkeypatch):
    """LocalElasticsearch provider resolves the shared vdb core lazily."""

    captured = {}

    class FakeCore:
        def create_index(self, name):
            captured["index"] = name

        def create_chunk(self, name, chunk):
            captured["chunk"] = chunk

    def fake_get_vector_db_core():
        return FakeCore()

    monkeypatch.setattr(
        "management.services.knowledge_base.service.get_vector_db_core", fake_get_vector_db_core
    )

    provider = LocalElasticsearchDocumentProjectionProvider()
    provider.project(
        {
            "resource_id": "rid-1",
            "provider_document_id": "doc-a",
            "tenant_id": "t1",
            "provider": "local",
            "knowledge_base_id": "kb-1",
            "version": 1,
            "tags": [],
        }
    )

    assert captured["index"] == "nexent_tag_projection"


def test_local_project_uses_document_name_for_title():
    class FakeCore:
        def create_index(self, name):
            pass

        def create_chunk(self, name, chunk):
            self.chunk = chunk

    core = FakeCore()
    provider = LocalElasticsearchDocumentProjectionProvider(vdb_core=core)
    provider.project(
        {
            "resource_id": "rid-1",
            "provider_document_id": "doc-a",
            "document_name": "Quarterly Report.pdf",
            "tenant_id": "t1",
            "provider": "local",
            "knowledge_base_id": "kb-1",
            "version": 2,
            "tags": [{"definition_id": 1, "value_id": 2}],
        }
    )

    assert core.chunk["title"] == "Quarterly Report.pdf"
    assert core.chunk["filename"] == "doc-a"


def test_get_projection_provider_rejects_unknown():
    import pytest

    with pytest.raises(ValueError, match="Unsupported document projection provider"):
        get_projection_provider("unknown-provider")


def test_decode_document_resource_id_roundtrip():
    encoded = _encode_document_resource_id("local", "kb-1", "docs/a.pdf")

    assert decode_document_resource_id(encoded) == ("local", "kb-1", "docs/a.pdf")


def test_decode_document_resource_id_rejects_invalid():
    import pytest

    with pytest.raises(ValueError, match="Invalid document resource id"):
        decode_document_resource_id("not-valid-base64!!!")


def test_project_disabled_returns_not_projected():
    result = project_document_assignments(
        "t1", "local", "kb-1", "doc-a", "user-1", enabled=False
    )

    assert result["status"] == "not_projected"
    assert result["version"] == 0


def test_project_rejects_unknown_provider():
    import pytest

    with pytest.raises(ValueError, match="Unsupported document projection provider"):
        project_document_assignments("t1", "unknown", "kb-1", "doc-a", "user-1")


def test_project_keeps_version_when_payload_unchanged_but_status_failed(monkeypatch):
    """Same payload but not synced keeps the current version instead of incrementing."""

    assignments = _assignments()
    monkeypatch.setattr(
        projection_module.TagManagementDB,
        "list_resource_assignments",
        lambda *args, **kwargs: assignments,
    )
    current = {
        "payload": assignments,
        "status": STATUS_FAILED,
        "version": 4,
        "retry_count": 1,
        "last_error": "previous failure",
        "last_attempt_at": None,
        "next_attempt_at": None,
        "update_time": None,
    }
    monkeypatch.setattr(
        projection_module.document_tag_projection_db,
        "get_projection_state",
        lambda *args, **kwargs: current,
    )
    captured = {}

    def fake_upsert(**kwargs):
        captured.update(kwargs)
        return {**kwargs, "payload": kwargs["payload"]}

    monkeypatch.setattr(
        projection_module.document_tag_projection_db,
        "upsert_projection_state",
        fake_upsert,
    )

    class FakeProvider:
        provider_name = "local"

        def capability(self):
            return "full"

        def project(self, payload):
            pass

        def clear(self, resource_id):
            pass

    monkeypatch.setattr(
        projection_module, "get_projection_provider", lambda *args, **kwargs: FakeProvider()
    )

    result = project_document_assignments("t1", "local", "kb-1", "doc-a", "user-1")

    assert result["version"] == 4
    assert captured["version"] == 4


def test_project_unsupported_raised_by_provider_is_recorded(monkeypatch):
    """A provider that raises DocumentTagProjectionUnsupported is recorded as unsupported."""

    monkeypatch.setattr(
        projection_module.TagManagementDB,
        "list_resource_assignments",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        projection_module.document_tag_projection_db,
        "get_projection_state",
        lambda *args, **kwargs: None,
    )
    captured = {}

    def fake_upsert(**kwargs):
        captured.update(kwargs)
        return {**kwargs, "payload": kwargs["payload"]}

    monkeypatch.setattr(
        projection_module.document_tag_projection_db,
        "upsert_projection_state",
        fake_upsert,
    )

    class UnsupportedRaisingProvider:
        provider_name = "local"

        def capability(self):
            return "full"

        def project(self, payload):
            raise DocumentTagProjectionUnsupported("no metadata endpoint")

        def clear(self, resource_id):
            pass

    monkeypatch.setattr(
        projection_module, "get_projection_provider", lambda *args, **kwargs: UnsupportedRaisingProvider()
    )

    result = project_document_assignments("t1", "local", "kb-1", "doc-a", "user-1")

    assert result["status"] == STATUS_UNSUPPORTED
    assert captured["status"] == STATUS_UNSUPPORTED
    assert captured["last_error"] == "no metadata endpoint"


def test_retry_loop_catches_unexpected_project_exception(monkeypatch):
    monkeypatch.setattr(
        projection_module.document_tag_projection_db,
        "list_due_projection_states",
        lambda *args, **kwargs: [
            {
                "tenant_id": "t1",
                "provider": "local",
                "knowledge_base_id": "kb-1",
                "provider_document_id": "d1",
            }
        ],
    )

    def fake_project(tenant_id, provider, kb, doc, actor, **kwargs):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(projection_module, "project_document_assignments", fake_project)

    result = retry_pending_document_projections(tenant_id="t1")

    assert result == {"attempted": 1, "synced": 0, "failed": 1, "unsupported": 0}
