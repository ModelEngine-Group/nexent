import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from consts.exceptions import (
    TagManagementConflictError,
    TagManagementNotFoundError,
    ValidationError,
)
from services.tag_management_service import TagManagementService
from services.tag_resource_adapters import AuthenticatedCaller
from sqlalchemy.exc import DBAPIError, IntegrityError


def _caller():
    return AuthenticatedCaller(user_id="user-1", authenticated_tenant_id="tenant-a", role="ADMIN")


def request(**values):
    return SimpleNamespace(**values)


def db_error(message):
    return IntegrityError("statement", {}, Exception(message))


def test_database_error_translation_includes_capacity_schema_and_duplicate_branch():
    with pytest.raises(TagManagementConflictError) as definition_error:
        TagManagementService._translate_database_error(db_error("Tag definition limit exceeded"))
    assert definition_error.value.details == {"limit": 100, "current_count": 100, "scope": "definition"}

    with pytest.raises(TagManagementConflictError) as value_error:
        TagManagementService._translate_database_error(db_error("Tag value limit exceeded"))
    assert value_error.value.details == {"limit": 1000, "current_count": 1000, "scope": "value"}

    with pytest.raises(TagManagementConflictError, match="same normalized name"):
        TagManagementService._translate_database_error(db_error("duplicate key uq_tag_value"))

    original = RuntimeError("unexpected")
    with pytest.raises(RuntimeError, match="unexpected"):
        TagManagementService._translate_database_error(original)


def test_list_and_definition_operations_forward_tenant_and_actor(monkeypatch):
    db = MagicMock()
    monkeypatch.setattr("services.tag_management_service.TagManagementDB", db)
    db.list_libraries.return_value = [{"bucket_id": 1}]
    db.list_definitions.return_value = [{"definition_id": 9}]
    assert TagManagementService.list_libraries("tenant-a") == [{"bucket_id": 1}]
    assert TagManagementService.list_definitions("tenant-a", 1) == [{"definition_id": 9}]

    created = {"definition_id": 9}
    db.create_definition.return_value = created
    create_request = request(
        definition_key="color",
        definition_name="Color",
        selection_mode="single_select",
        initial_values=["Red"],
        sort_order=2,
    )
    assert TagManagementService.create_definition("tenant-a", 1, create_request, "user-1") == created
    db.create_definition.assert_called_with("tenant-a", 1, "color", "Color", "single_select", ["Red"], 2, "user-1")

    db.update_definition.return_value = ({"definition_id": 9}, 0)
    update_request = request(definition_name="New", selection_mode="multi_select")
    assert TagManagementService.update_definition("tenant-a", 1, 9, update_request, "user-2") == {
        "definition_id": 9
    }
    db.update_definition.assert_called_with("tenant-a", 1, 9, "New", "multi_select", "user-2")

    with pytest.raises(ValidationError, match="At least one definition"):
        TagManagementService.update_definition(
            "tenant-a", 1, 9, request(definition_name=None, selection_mode=None), "user-2"
        )


def test_create_definition_generates_a_key_when_the_client_omits_one(monkeypatch):
    db = MagicMock()
    monkeypatch.setattr("services.tag_management_service.TagManagementDB", db)
    monkeypatch.setattr(
        "services.tag_management_service.uuid4",
        lambda: SimpleNamespace(hex="generatedkey"),
    )
    create_request = request(
        definition_key=None,
        definition_name="Featured",
        selection_mode="no_value",
        initial_values=[],
        sort_order=None,
    )

    TagManagementService.create_definition("tenant-a", 1, create_request, "user-1")

    db.create_definition.assert_called_once_with(
        "tenant-a",
        1,
        "custom_generatedkey",
        "Featured",
        "no_value",
        [],
        None,
        "user-1",
    )


def test_definition_update_conflict_and_delete_conflict_have_structured_details(monkeypatch):
    db = MagicMock()
    monkeypatch.setattr("services.tag_management_service.TagManagementDB", db)
    db.update_definition.return_value = (
        {"definition_id": 9, "definition_name": "Color"},
        3,
    )
    with pytest.raises(TagManagementConflictError) as update_error:
        TagManagementService.update_definition(
            "tenant-a", 1, 9, request(definition_name=None, selection_mode="single_select"), "user-2"
        )
    assert update_error.value.details == {"definition_id": 9, "resources_with_multiple_values": 3}

    db.delete_definition.return_value = {"active_value_count": 2, "active_usage_count": 1}
    with pytest.raises(TagManagementConflictError) as delete_error:
        TagManagementService.delete_definition("tenant-a", 1, 9, "user-2")
    assert delete_error.value.details == {
        "definition_id": 9,
        "active_value_count": 2,
        "active_usage_count": 1,
    }

    db.delete_definition.return_value = {"active_value_count": 0, "active_usage_count": 0}
    assert TagManagementService.delete_definition("tenant-a", 1, 9, "user-2") is None


def test_definition_status_order_and_usage_delegate(monkeypatch):
    db = MagicMock()
    monkeypatch.setattr("services.tag_management_service.TagManagementDB", db)
    db.set_definition_status.return_value = {"status": "disabled"}
    db.set_definition_order.return_value = {"sort_order": 5}
    db.move_definition_to_top.return_value = {"sort_order": 0}
    db.get_definition_usage.return_value = {"definition_id": 9}
    assert TagManagementService.set_definition_status("tenant-a", 1, 9, "disabled", "user-1") == {
        "status": "disabled"
    }
    assert TagManagementService.set_definition_order("tenant-a", 1, 9, 5, "user-1") == {"sort_order": 5}
    assert TagManagementService.move_definition_to_top("tenant-a", 1, 9, "user-1") == {
        "sort_order": 0
    }
    assert TagManagementService.get_definition_usage("tenant-a", 1, 9) == {"definition_id": 9}


def test_value_operations_forward_values_and_translate_database_errors(monkeypatch):
    db = MagicMock()
    monkeypatch.setattr("services.tag_management_service.TagManagementDB", db)
    create_request = request(display_value="Red", sort_order=4)
    db.create_value.return_value = {"value_id": 11}
    assert TagManagementService.create_value("tenant-a", 1, 9, create_request, "user-1") == {"value_id": 11}
    db.create_value.assert_called_with("tenant-a", 1, 9, "Red", 4, "user-1")

    update_request = request(display_value="Blue")
    db.update_value.return_value = {"value_id": 11, "normalized_value": "blue"}
    assert TagManagementService.update_value("tenant-a", 1, 9, 11, update_request, "user-2") == {
        "value_id": 11,
        "normalized_value": "blue",
    }
    db.update_value.assert_called_with("tenant-a", 1, 9, 11, "Blue", "user-2")

    db.set_value_status.return_value = {"status": "disabled"}
    db.set_value_order.return_value = {"sort_order": 6}
    db.get_value_usage.return_value = {"value_id": 11, "active_usage_count": 0}
    assert TagManagementService.set_value_status("tenant-a", 1, 9, 11, "disabled", "user-2") == {
        "status": "disabled"
    }
    assert TagManagementService.set_value_order("tenant-a", 1, 9, 11, 6, "user-2") == {"sort_order": 6}
    assert TagManagementService.get_value_usage("tenant-a", 1, 9, 11) == {
        "value_id": 11,
        "active_usage_count": 0,
    }

    db.delete_value.return_value = 0
    assert TagManagementService.delete_value("tenant-a", 1, 9, 11, "user-2") is None
    db.delete_value.return_value = 4
    with pytest.raises(TagManagementConflictError) as error:
        TagManagementService.delete_value("tenant-a", 1, 9, 11, "user-2")
    assert error.value.details == {"value_id": 11, "active_usage_count": 4}


@pytest.mark.parametrize(
    ("method_name", "error_message"),
    [
        ("create_definition", "Tag definition limit exceeded"),
        ("create_value", "Tag value limit exceeded"),
        ("update_value", "duplicate key uq_tag_value"),
    ],
)
def test_write_methods_translate_integrity_and_dbapi_errors(monkeypatch, method_name, error_message):
    db = MagicMock()
    monkeypatch.setattr("services.tag_management_service.TagManagementDB", db)
    db_method = getattr(db, method_name)
    db_method.side_effect = db_error(error_message)
    if method_name == "create_definition":
        args = (
            "tenant-a",
            1,
            request(
                definition_key="color",
                definition_name="Color",
                selection_mode="single_select",
                initial_values=["Red"],
                sort_order=0,
            ),
            "user-1",
        )
    elif method_name == "create_value":
        args = ("tenant-a", 1, 9, request(display_value="Red", sort_order=0), "user-1")
    else:
        args = ("tenant-a", 1, 9, 11, request(display_value="Blue"), "user-1")
    with pytest.raises(TagManagementConflictError):
        getattr(TagManagementService, method_name)(*args)

    db_method.side_effect = DBAPIError("statement", {}, Exception(error_message))
    with pytest.raises(TagManagementConflictError):
        getattr(TagManagementService, method_name)(*args)



def _identity(resource_type="tool", resource_id="tool-1", library_code="default_resource", provider=None, knowledge_base_id=None, provider_document_id=None):
    return SimpleNamespace(
        resource_type=SimpleNamespace(value=resource_type),
        resource_id=resource_id,
        library_code=library_code,
        provider=provider,
        knowledge_base_id=knowledge_base_id,
        provider_document_id=provider_document_id,
    )


def test_get_resource_assignments_returns_canonical_summary(monkeypatch):
    identity = _identity()
    async def resolve_mock(*args, **kwargs):
        return identity

    monkeypatch.setattr(
        "services.tag_management_service.TagManagementService._resolve_assignment_resource",
        resolve_mock,
    )
    monkeypatch.setattr(
        "services.tag_management_service.TagManagementDB.list_resource_assignments",
        lambda *args, **kwargs: [{"definition_id": 1, "value_id": 2}],
    )

    result = asyncio.run(
        TagManagementService.get_resource_assignments(_caller(), "tool", "tool-1")
    )
    assert result == {
        "resource_type": "tool",
        "resource_id": "tool-1",
        "assignment_count": 1,
        "assignment_capacity": 100,
        "assignments": [{"definition_id": 1, "value_id": 2}],
    }


def test_replace_resource_assignments_includes_document_projection_status(monkeypatch):
    identity = _identity(
        resource_type="knowledge_document",
        resource_id="encoded",
        library_code="knowledge_content",
        provider="local",
        knowledge_base_id="kb-1",
        provider_document_id="doc-1",
    )
    async def resolve_mock(*args, **kwargs):
        return identity

    monkeypatch.setattr(
        "services.tag_management_service.TagManagementService._resolve_assignment_resource",
        resolve_mock,
    )
    def fake_replace(*args, **kwargs):
        captured.update(kwargs)
        return [{"definition_id": 1, "value_id": 2}]

    monkeypatch.setattr(
        "services.tag_management_service.TagManagementDB.replace_resource_assignments",
        fake_replace,
    )
    monkeypatch.setattr(
        "services.tag_management_service.TAG_DOCUMENT_PROJECTION_ENABLED",
        True,
    )
    captured = {}

    def fake_project(*args, **kwargs):
        captured["provider"] = args[1]
        captured["knowledge_base_id"] = args[2]
        captured.update(kwargs)
        return {"status": "synced", "version": 1, "tag_count": 1}

    monkeypatch.setattr(
        "services.tag_document_projection.project_document_assignments",
        fake_project,
    )

    result = asyncio.run(
        TagManagementService.replace_resource_assignments(
            _caller(), "knowledge_document", "doc-1", [1], provider="local", knowledge_base_id="kb-1"
        )
    )
    assert result["projection_status"]["status"] == "synced"
    assert captured["enabled"] is True
    assert captured["provider"] == "local"
    assert captured["knowledge_base_id"] == "kb-1"


def test_bulk_assignment_outcomes_cover_success_not_found_and_validation(monkeypatch):
    async def fake_replace(caller, resource_type, resource_id, value_ids, **kwargs):
        if resource_id == "missing":
            raise TagManagementNotFoundError("Resource not found")
        if resource_id == "invalid":
            raise ValidationError("Bad values")
        return {"resource_id": resource_id, "assignment_count": 1}

    monkeypatch.setattr(
        "services.tag_management_service.TagManagementService.replace_resource_assignments",
        fake_replace,
    )

    targets = [
        SimpleNamespace(resource_id="ok", value_ids=[1], provider=None, knowledge_base_id=None),
        SimpleNamespace(resource_id="missing", value_ids=[1], provider=None, knowledge_base_id=None),
        SimpleNamespace(resource_id="invalid", value_ids=[1], provider=None, knowledge_base_id=None),
    ]
    outcomes = asyncio.run(
        TagManagementService.replace_resource_assignments_bulk(_caller(), "tool", targets)
    )

    assert outcomes[0]["outcome"] == "updated"
    assert outcomes[0]["assignment"]["resource_id"] == "ok"
    assert outcomes[1] == {"resource_id": "missing", "outcome": "not_found_or_forbidden"}
    assert outcomes[2]["outcome"] == "validation"
    assert outcomes[2]["message"] == "Bad values"



def test_batch_status_respects_limit_and_encoding(monkeypatch):
    # Covers batch status: >200 validation, dedup, encode/decode, states dict, projection status
    from services.tag_document_projection import _encode_document_resource_id

    db = MagicMock()
    monkeypatch.setattr("services.tag_management_service.TagManagementDB", db)
    registry = MagicMock()
    monkeypatch.setattr(
        "services.tag_management_service.TagManagementService.resource_adapter_registry",
        registry,
    )
    monkeypatch.setattr(
        "services.tag_management_service.TAG_DOCUMENT_PROJECTION_ENABLED",
        True,
    )
    resolved = MagicMock()
    resolved.found = True
    resolved.identity = MagicMock()
    resolved.capabilities.can_read = True
    async def resolve_mock(*args, **kwargs):
        return resolved

    registry.resolve = resolve_mock

    ids = [str(i) for i in range(201)]
    with pytest.raises(ValidationError, match="at most 200"):
        asyncio.run(
            TagManagementService.get_document_tag_batch_status(
                _caller(), "local", "kb-1", ids
            )
        )
    assert db.count_resource_assignments_by_ids.call_count == 0

    # dedup + predicate none + projection state present
    db.count_resource_assignments_by_ids.return_value = {
        _encode_document_resource_id("local", "kb-1", "doc-1"): 3
    }
    db.filter_authorized_resource_ids.side_effect = lambda *a, **k: [
        _encode_document_resource_id("local", "kb-1", "doc-1")
    ]
    monkeypatch.setattr(
        "database.document_tag_projection_db.list_projection_states_for_knowledge_base",
        lambda *a, **k: {"doc-1": {"status": "synced", "version": 1, "tag_count": 0}},
    )

    result = asyncio.run(
        TagManagementService.get_document_tag_batch_status(
            _caller(), "local", "kb-1", ["doc-1", "doc-1"]
        )
    )
    assert len(result) == 1
    assert result[0]["document_id"] == "doc-1"
    assert result[0]["assignment_count"] == 3
    assert result[0]["projection_status"]["status"] == "synced"
    assert result[0]["projection_status"]["version"] == 1


def test_filter_resource_ids_for_caller_rejects_documents_and_unknown(monkeypatch):
    monkeypatch.setattr(
        "services.tag_management_service.TagManagementDB.filter_authorized_resource_ids",
        lambda *a, **k: ["r-1", "r-2"],
    )
    with pytest.raises(ValidationError, match="batch-status endpoint"):
        TagManagementService.filter_resource_ids_for_caller(
            _caller(), "knowledge_document", ["d-1"], []
        )
    with pytest.raises(ValidationError, match="unsupported resource type"):
        TagManagementService.filter_resource_ids_for_caller(
            _caller(), "unknown", ["r-1"], []
        )
    result = TagManagementService.filter_resource_ids_for_caller(
        _caller(), "tool", ["r-1", "r-2"], [{"definition_id": 1}]
    )
    assert result == {"resource_type": "tool", "matched_resource_ids": ["r-1", "r-2"]}


def test_cleanup_resource_and_document_assignments(monkeypatch):
    db = MagicMock()
    monkeypatch.setattr("services.tag_management_service.TagManagementDB", db)
    db.soft_delete_resource_assignments.return_value = 2
    db.soft_delete_document_assignments_for_knowledge_base.return_value = 5
    monkeypatch.setattr(
        "services.tag_document_projection.clear_document_projection",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "services.tag_document_projection.clear_projection_states_for_knowledge_base",
        lambda *a, **k: None,
    )

    assert TagManagementService.cleanup_resource_assignments(
        "tenant-a", "tool", "tool-1", "actor-1"
    ) == 2
    assert TagManagementService.cleanup_document_assignments(
        "tenant-a", "local", "kb-1", "doc-1", "actor-1"
    ) == 2
    assert TagManagementService.cleanup_document_assignments_for_knowledge_base(
        "tenant-a", "local", "kb-1", "actor-1"
    ) == 5


def test_get_document_projection_status_and_legacy_flat_tags(monkeypatch):
    identity = _identity(
        resource_type="knowledge_document",
        resource_id="encoded",
        library_code="knowledge_content",
        provider="local",
        knowledge_base_id="kb-1",
        provider_document_id="doc-1",
    )
    async def resolve_mock(*args, **kwargs):
        return identity

    monkeypatch.setattr(
        "services.tag_management_service.TagManagementService._resolve_assignment_resource",
        resolve_mock,
    )
    monkeypatch.setattr(
        "services.tag_document_projection.get_document_projection_status",
        lambda *a, **k: {"status": "synced", "version": 1},
    )
    result = asyncio.run(
        TagManagementService.get_document_projection_status(
            _caller(), "knowledge_document", "doc-1", provider="local", knowledge_base_id="kb-1"
        )
    )
    assert result == {"status": "synced", "version": 1}

    monkeypatch.setattr(
        "services.tag_management_service.TagManagementDB.list_resource_assignments",
        lambda *a, **k: [
            {"display_value": "Red"},
            {"display_value": "Blue"},
            {"display_value": "Red"},
        ],
    )
    legacy = asyncio.run(
        TagManagementService.get_legacy_flat_tags_projection(
            _caller(), "knowledge_document", "doc-1", provider="local", knowledge_base_id="kb-1", limit=2
        )
    )
    assert legacy == {
        "resource_type": "knowledge_document",
        "resource_id": "encoded",
        "tags": ["Blue", "Red"],
        "count": 2,
        "limit": 2,
        "deprecated": True,
    }


def test_document_projection_status_requires_provider_document(monkeypatch):
    identity = _identity()  # no provider
    async def resolve_mock(*args, **kwargs):
        return identity

    monkeypatch.setattr(
        "services.tag_management_service.TagManagementService._resolve_assignment_resource",
        resolve_mock,
    )
    with pytest.raises(ValidationError, match="requires a provider document"):
        asyncio.run(
            TagManagementService.get_document_projection_status(
                _caller(), "knowledge_document", "doc-1"
            )
        )


def test_projection_delegates_and_retry(monkeypatch):
    monkeypatch.setattr(
        "services.tag_document_projection.filter_document_ids_by_predicates",
        lambda *a, **k: ["doc-1"],
    )
    assert TagManagementService.filter_document_ids_by_predicates(
        "tenant-a", "local", "kb-1", [{"definition_id": 1}]
    ) == ["doc-1"]
    monkeypatch.setattr(
        "services.tag_document_projection.retry_pending_document_projections",
        lambda tenant_id=None, limit=50: {"retried": limit, "tenant_id": tenant_id},
    )
    assert TagManagementService.retry_pending_document_projections("tenant-a", 10) == {
        "retried": 10,
        "tenant_id": "tenant-a",
    }


def test_resolve_requires_edit_permission_capability(monkeypatch):
    registry = MagicMock()
    monkeypatch.setattr(
        "services.tag_management_service.TagManagementService.resource_adapter_registry",
        registry,
    )
    async def resolve_mock(*args, **kwargs):
        resolved = MagicMock()
        resolved.found = True
        resolved.identity = MagicMock()
        resolved.capabilities.can_edit = False
        resolved.capabilities.can_read = True
        return resolved

    registry.resolve = resolve_mock
    with pytest.raises(TagManagementNotFoundError, match="Resource not found"):
        asyncio.run(
            TagManagementService._resolve_assignment_resource(
                _caller(), "tool", "tool-1", require_edit=True
            )
        )


def test_batch_status_empty_documents_and_predicates(monkeypatch):
    db = MagicMock()
    monkeypatch.setattr("services.tag_management_service.TagManagementDB", db)
    registry = MagicMock()
    monkeypatch.setattr(
        "services.tag_management_service.TagManagementService.resource_adapter_registry",
        registry,
    )
    async def resolve_mock(*args, **kwargs):
        resolved = MagicMock()
        resolved.found = True
        resolved.identity = MagicMock()
        resolved.capabilities.can_read = True
        return resolved

    registry.resolve = resolve_mock

    # empty document ids -> []
    empty = asyncio.run(
        TagManagementService.get_document_tag_batch_status(_caller(), "local", "kb-1", [])
    )
    assert empty == []

    # predicates filter branch
    from services.tag_document_projection import _encode_document_resource_id

    encoded = _encode_document_resource_id("local", "kb-1", "doc-1")
    db.count_resource_assignments_by_ids.return_value = {encoded: 1}
    db.filter_authorized_resource_ids.return_value = []
    filtered = asyncio.run(
        TagManagementService.get_document_tag_batch_status(
            _caller(), "local", "kb-1", ["doc-1"], predicates=[{"definition_id": 1}]
        )
    )
    assert filtered == []
    db.filter_authorized_resource_ids.assert_called_once()
    # empty branch also reaches count (no short-circuit on unique ids); both calls hit the mock
    assert db.count_resource_assignments_by_ids.call_count == 1


def test_cleanup_document_exception_branches(monkeypatch):
    db = MagicMock()
    monkeypatch.setattr("services.tag_management_service.TagManagementDB", db)
    db.soft_delete_resource_assignments.return_value = 1
    db.soft_delete_document_assignments_for_knowledge_base.return_value = 1

    # clear_document_projection raises
    monkeypatch.setattr(
        "services.tag_document_projection.clear_document_projection",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    result = TagManagementService.cleanup_document_assignments(
        "tenant-a", "local", "kb-1", "doc-1", "actor-1"
    )
    assert result == 1

    # clear_projection_states_for_knowledge_base raises
    monkeypatch.setattr(
        "services.tag_document_projection.clear_projection_states_for_knowledge_base",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    result2 = TagManagementService.cleanup_document_assignments_for_knowledge_base(
        "tenant-a", "local", "kb-1", "actor-1"
    )
    assert result2 == 1
