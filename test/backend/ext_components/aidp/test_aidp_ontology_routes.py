# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Route-level coverage for the ontology proxy using the shared management app."""

from __future__ import annotations

import copy
import importlib
from unittest.mock import MagicMock

import httpx
import pytest
from pydantic import ValidationError

from test.ext_components.aidp.test_aidp_mgmt_app import (  # noqa: F401
    _bearer,
    _client,
    _isolated_imports,
    configure_aidp_constants,
)

pytestmark = pytest.mark.usefixtures("configure_aidp_constants")

_TRANSPORT_PAYLOAD = {
    "data": {"id": 1, "name": "Demo", "api_name": "Phone", "count": 1},
    "value": [
        {
            "id": 1,
            "name": "Demo",
            "od_name": "Demo",
            "domain_name": "Demo",
            "api_name": "Phone",
        }
    ],
    "items": [{"api_name": "Phone", "entity_id": "1", "id": 1}],
    "task_list": [{"id": "1", "status": "completed"}],
    "total": 1,
    "total_count": 1,
    "has_next": False,
    "folder_path": "/",
}


@pytest.fixture(autouse=True)
def _load_ontology_modules():
    global ontology_common, ontology_models, ontology_validation
    from ext_components.aidp.apps import aidp_ontology_models as models_module
    from ext_components.aidp.apps import aidp_ontology_validation as validation_module
    from ext_components.aidp.services import aidp_ontology_common as common_module

    ontology_common = common_module
    ontology_models = models_module
    ontology_validation = validation_module


@pytest.fixture(autouse=True)
def _stub_ontology_transport(monkeypatch):
    for name in (
        "aidp_ontology_domain_service",
        "aidp_ontology_task_service",
        "aidp_ontology_binding_service",
        "aidp_ontology_rule_service",
        "aidp_ontology_metadata_service",
    ):
        module = importlib.import_module(f"ext_components.aidp.services.{name}")
        monkeypatch.setattr(
            module, "_ontology_request", lambda *a, **kw: copy.deepcopy(_TRANSPORT_PAYLOAD)
        )


def test_list_domains_route(monkeypatch):
    from ext_components.aidp.apps import aidp_ontology_domain_routes as routes

    monkeypatch.setattr(
        routes,
        "list_ontology_domains_impl",
        lambda *a, **kw: {
            "value": [{"id": 1, "name": "Demo", "description": "d"}],
            "total_count": 1,
            "has_more": False,
            "total_reliable": True,
        },
    )
    monkeypatch.setattr(
        routes, "list_ontology_bindings_impl", lambda *a, **kw: [{"kds_id": "kb"}]
    )
    response = _client().get(
        "/aidp-mgmt/ontology/domains?page=1&page_size=20", headers=_bearer()
    )
    assert response.status_code == 200
    assert isinstance(response.json()["value"], list)


def _allow_manager(monkeypatch):
    from ext_components.aidp.apps import aidp_ontology_validation as validation

    monkeypatch.setattr(
        validation, "get_user_role_by_tenant", lambda *_a, **_kw: ["ADMIN"]
    )


def _patch_domain_helpers(monkeypatch):
    from ext_components.aidp.apps import aidp_ontology_domain_routes as routes

    async def binding_count(_domain_id):
        return 1

    async def reconcile(*_a, **_kw):
        return None

    monkeypatch.setattr(routes, "_binding_count", binding_count)
    monkeypatch.setattr(routes, "_reconcile_entity_relations", reconcile)
    monkeypatch.setattr(
        routes,
        "_domain_summary",
        lambda value, count=None: {
            "od_id": "1",
            "name": "Demo",
            "description": "d",
            "binding_count": count,
        },
    )
    monkeypatch.setattr(
        routes,
        "_entity_summary",
        lambda value, **kwargs: {
            "entity_id": kwargs.get("entity_id", "1"),
            "api_name": "Phone",
            "display_name": "Phone",
        },
    )
    return routes


def test_domain_crud_routes(monkeypatch):
    routes = _patch_domain_helpers(monkeypatch)
    _allow_manager(monkeypatch)
    monkeypatch.setattr(
        routes, "create_ontology_domain_impl", lambda *a, **kw: {"id": 1}
    )
    monkeypatch.setattr(
        routes, "update_ontology_domain_impl", lambda *a, **kw: {"id": 1}
    )
    monkeypatch.setattr(
        routes, "delete_ontology_domain_impl", lambda *a, **kw: True
    )
    monkeypatch.setattr(
        routes, "get_ontology_domain_impl", lambda *a, **kw: {"id": 1}
    )
    monkeypatch.setattr(
        routes,
        "list_ontology_entities_impl",
        lambda *a, **kw: {"value": [], "total_count": 0},
    )
    monkeypatch.setattr(
        routes,
        "list_ontology_metadata_fields_impl",
        lambda *a, **kw: {"value": [], "total_count": 0},
    )

    client = _client()
    assert client.post(
        "/aidp-mgmt/ontology/domains",
        headers=_bearer(),
        json={"name": "Demo", "description": "d"},
    ).status_code == 200
    assert client.get(
        "/aidp-mgmt/ontology/domains/1", headers=_bearer()
    ).status_code == 200
    assert client.patch(
        "/aidp-mgmt/ontology/domains/1",
        headers=_bearer(),
        json={"description": "new"},
    ).status_code == 200
    assert client.delete(
        "/aidp-mgmt/ontology/domains/1", headers=_bearer()
    ).status_code == 200


def test_entity_and_relation_routes(monkeypatch):
    routes = _patch_domain_helpers(monkeypatch)
    _allow_manager(monkeypatch)
    monkeypatch.setattr(
        routes,
        "list_ontology_entities_impl",
        lambda *a, **kw: {
            "value": [{"api_name": "Phone"}],
            "total_count": 1,
            "has_more": False,
            "total_reliable": True,
        },
    )
    monkeypatch.setattr(
        routes, "get_ontology_entity_impl", lambda *a, **kw: {"api_name": "Phone"}
    )
    monkeypatch.setattr(
        routes,
        "create_ontology_entity_impl",
        lambda *a, **kw: {"entity_id": "1"},
    )
    monkeypatch.setattr(
        routes,
        "update_ontology_entity_impl",
        lambda *a, **kw: {"api_name": "Phone"},
    )
    monkeypatch.setattr(
        routes, "delete_ontology_entity_impl", lambda *a, **kw: True
    )
    monkeypatch.setattr(
        routes,
        "list_ontology_relations_impl",
        lambda *a, **kw: {"value": [], "total_count": 0},
    )
    monkeypatch.setattr(
        routes,
        "create_ontology_relation_impl",
        lambda *a, **kw: {"relation_id": "2"},
    )
    monkeypatch.setattr(
        routes, "delete_ontology_relation_impl", lambda *a, **kw: True
    )

    client = _client()
    assert client.get(
        "/aidp-mgmt/ontology/domains/1/entities", headers=_bearer()
    ).status_code == 200
    assert client.post(
        "/aidp-mgmt/ontology/domains/1/entities",
        headers=_bearer(),
        json={"api_name": "Phone", "display_name": "Phone"},
    ).status_code == 200
    assert client.get(
        "/aidp-mgmt/ontology/domains/1/entities/2", headers=_bearer()
    ).status_code == 200
    assert client.patch(
        "/aidp-mgmt/ontology/domains/1/entities/2",
        headers=_bearer(),
        json={"display_name": "P"},
    ).status_code == 200
    assert client.delete(
        "/aidp-mgmt/ontology/domains/1/entities/2", headers=_bearer()
    ).status_code == 200
    assert client.get(
        "/aidp-mgmt/ontology/domains/1/relations", headers=_bearer()
    ).status_code == 200
    assert client.put(
        "/aidp-mgmt/ontology/domains/1/relations",
        headers=_bearer(),
        json={
            "api_name": "is-a",
            "display_name": "is-a",
            "source_kind": "entity",
            "source_id": "1",
            "object_kind": "type",
            "object_id": "2",
        },
    ).status_code == 200
    assert client.delete(
        "/aidp-mgmt/ontology/domains/1/relations/2", headers=_bearer()
    ).status_code == 200


def test_metadata_routes(monkeypatch):
    from ext_components.aidp.apps import aidp_ontology_metadata_routes as routes

    _allow_manager(monkeypatch)
    monkeypatch.setattr(routes.perms, "require_permission", lambda *a, **kw: None)
    async def load_fields(*_a, **_kw):
        return [{"id": 2, "field_name": "f", "field_type": "string"}]

    monkeypatch.setattr(routes, "_load_metadata_fields", load_fields)
    monkeypatch.setattr(
        routes,
        "_find_metadata_field",
        lambda _fields, ref: {"id": 2, "field_name": "f"}
        if str(ref) in ("2", "f")
        else None,
    )

    client = _client()
    assert client.get(
        "/aidp-mgmt/ontology/domains/1/metadata-fields", headers=_bearer()
    ).status_code == 200
    assert client.post(
        "/aidp-mgmt/ontology/domains/1/metadata-fields",
        headers=_bearer(),
        json={"field_name": "g", "field_type": "string"},
    ).status_code == 200
    assert client.patch(
        "/aidp-mgmt/ontology/domains/1/metadata-fields/2",
        headers=_bearer(),
        json={"new_field_name": "g"},
    ).status_code == 200
    assert client.post(
        "/aidp-mgmt/ontology/domains/1/metadata-fields/batch-unbind",
        headers=_bearer(),
        json={"metadata_ids": ["2"]},
    ).status_code == 200
    assert client.delete(
        "/aidp-mgmt/ontology/domains/1/metadata-fields/2", headers=_bearer()
    ).status_code == 200
    assert client.post(
        "/aidp-mgmt/ontology/domains/1/chunks/metadata/export",
        headers=_bearer(),
        json={"kds_id": 1, "chunk_id": 2},
    ).status_code == 200
    assert client.post(
        "/aidp-mgmt/ontology/domains/1/chunks/metadata/import",
        headers=_bearer(),
        json={"kds_id": 1, "metadata_json": {"f": "v"}, "chunk_id_list": [2]},
    ).status_code == 200
    assert client.post(
        "/aidp-mgmt/ontology/domains/1/metadata/batch-unbind-sync",
        headers=_bearer(),
        json={"metadata_id_list": [2]},
    ).status_code == 200
    assert client.post(
        "/aidp-mgmt/ontology/tags/sync",
        headers=_bearer(),
        json={"kb_ids": [1]},
    ).status_code == 200


def test_rule_and_task_routes(monkeypatch):
    from ext_components.aidp.apps import aidp_ontology_rule_routes as rules
    from ext_components.aidp.apps import aidp_ontology_task_routes as tasks

    _allow_manager(monkeypatch)
    monkeypatch.setattr(
        rules,
        "list_ontology_rules_impl",
        lambda *a, **kw: {"value": [], "total_count": 0},
    )
    monkeypatch.setattr(
        rules, "count_ontology_rules_impl", lambda *a, **kw: 1
    )
    monkeypatch.setattr(
        rules, "get_ontology_rule_impl", lambda *a, **kw: {"rule_id": "2"}
    )
    monkeypatch.setattr(
        rules, "create_ontology_rule_impl", lambda *a, **kw: {"rule_id": "2"}
    )
    monkeypatch.setattr(
        rules, "update_ontology_rule_impl", lambda *a, **kw: {"rule_id": "2"}
    )
    monkeypatch.setattr(
        rules, "delete_ontology_rule_impl", lambda *a, **kw: True
    )
    monkeypatch.setattr(
        tasks,
        "list_tasks_impl",
        lambda *a, **kw: {
            "value": [],
            "total_count": 0,
            "task_count": 0,
            "has_more": False,
            "total_reliable": True,
        },
    )
    monkeypatch.setattr(tasks, "get_task_impl", lambda *a, **kw: {"task_id": "1"})

    client = _client()
    assert client.get(
        "/aidp-mgmt/ontology/domains/1/rules", headers=_bearer()
    ).status_code == 200
    assert client.get(
        "/aidp-mgmt/ontology/domains/1/rules/count", headers=_bearer()
    ).status_code == 200
    assert client.get(
        "/aidp-mgmt/ontology/domains/1/rules/2", headers=_bearer()
    ).status_code == 200
    rule_body = {
        "name": "r",
        "description": "",
        "enabled": True,
        "condition": {"type": "json", "value": {"logical_operator": "and", "conditions": []}},
        "action": {"type": "json", "value": {"effect_mode": "add", "coefficient": 0.1}},
    }
    assert client.put(
        "/aidp-mgmt/ontology/domains/1/rules",
        headers=_bearer(),
        json=rule_body,
    ).status_code == 200
    assert client.patch(
        "/aidp-mgmt/ontology/domains/1/rules/2",
        headers=_bearer(),
        json=rule_body,
    ).status_code == 200
    assert client.delete(
        "/aidp-mgmt/ontology/domains/1/rules/2", headers=_bearer()
    ).status_code == 200
    assert client.get(
        "/aidp-mgmt/ontology/tasks?page=1&page_size=20", headers=_bearer()
    ).status_code == 200
    assert client.get(
        "/aidp-mgmt/ontology/tasks/1", headers=_bearer()
    ).status_code == 200


def test_batch_routes(monkeypatch):
    from ext_components.aidp.apps import aidp_ontology_batch_routes as routes

    _allow_manager(monkeypatch)
    monkeypatch.setattr(
        routes,
        "export_ontology_impl",
        lambda *a, **kw: {"data": {"Demo": {"types": [], "entities": [], "relations": []}}},
    )
    monkeypatch.setattr(
        routes,
        "get_ontology_domain_impl",
        lambda *a, **kw: {"name": "Demo"},
    )
    monkeypatch.setattr(
        routes,
        "import_ontology_impl",
        lambda *a, **kw: {"execution_mode": "sync", "result": {"imported_count": 0}},
    )

    client = _client()
    assert client.post(
        "/aidp-mgmt/ontology/domains/1/export",
        headers=_bearer(),
        json={"include_properties": True, "include_relations": True},
    ).status_code == 200
    assert client.post(
        "/aidp-mgmt/ontology/domains/1/import",
        headers=_bearer(),
        json={
            "file_name": "demo.json",
            "document": {
                "Demo": {"types": [], "entities": [], "relations": []}
            },
        },
    ).status_code == 200


def test_binding_routes(monkeypatch):
    from ext_components.aidp.apps import aidp_ontology_binding_routes as routes

    _allow_manager(monkeypatch)
    monkeypatch.setattr(routes.perms, "require_permission", lambda *a, **kw: None)

    async def load_bindings(*_a, **_kw):
        return [{"kds_id": "kb", "od_id": "1"}]

    async def domain_names(*_a, **_kw):
        return {"1": "Demo"}

    monkeypatch.setattr(routes, "_load_bindings", load_bindings)
    monkeypatch.setattr(routes, "_domain_names", domain_names)
    monkeypatch.setattr(
        routes,
        "_enrich_bindings_sync",
        lambda rows, *_a, **_kw: [{**row, "kds_name": "KB"} for row in rows],
    )
    monkeypatch.setattr(
        routes, "get_ontology_domain_impl", lambda *a, **kw: {"id": 1}
    )
    monkeypatch.setattr(
        routes, "get_aidp_kb_impl", lambda *a, **kw: {"bind_lib_type": None}
    )
    monkeypatch.setattr(
        routes, "create_ontology_binding_impl", lambda *a, **kw: {}
    )
    monkeypatch.setattr(
        routes,
        "delete_ontology_binding_impl",
        lambda *a, **kw: {"tag_clear_task": {"task_id": "1", "task_type": "tag"}},
    )

    client = _client()
    assert client.get(
        "/aidp-mgmt/ontology/domains/1/bindings", headers=_bearer()
    ).status_code == 200
    assert client.post(
        "/aidp-mgmt/ontology/domains/1/bindings",
        headers=_bearer(),
        json={"kb_id": "kb"},
    ).status_code == 200
    assert client.put(
        "/aidp-mgmt/ontology/domains/1/bindings",
        headers=_bearer(),
        json={"kb_id": "kb"},
    ).status_code == 200
    assert client.delete(
        "/aidp-mgmt/ontology/domains/1/bindings/kb", headers=_bearer()
    ).status_code == 200


def _response(status: int, *, json_body=None, content: bytes | None = None):
    request = httpx.Request("GET", "http://aidp.example/x")
    if json_body is not None:
        return httpx.Response(status, json=json_body, request=request)
    return httpx.Response(status, content=content or b"", request=request)


@pytest.fixture
def client(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(
        ontology_common.http_client_manager,
        "get_sync_client",
        MagicMock(return_value=client),
    )
    monkeypatch.setattr(
        ontology_common, "_request_with_retry", lambda request_fn, context: request_fn()
    )
    return client


def test_path_and_domain_id_helpers():
    assert ontology_common._get_ontology_path("t1").endswith("/Tenants/t1/OntologyDomain")
    assert ontology_common._domain_id_value("42") == 42


def test_request_returns_json_and_empty_body(client):
    client.request.return_value = _response(200, json_body={"ok": True})
    assert ontology_common._ontology_request("http://aidp.example", "key", "GET", "/x", operation="op") == {"ok": True}

    client.request.return_value = _response(204)
    assert ontology_common._ontology_request("http://aidp.example", "key", "GET", "/x", operation="op") == {}


def test_request_rejects_non_json(client):
    client.request.return_value = _response(200, content=b"not json")
    with pytest.raises(ontology_common.AppException) as error:
        ontology_common._ontology_request("http://aidp.example", "key", "GET", "/x", operation="op")
    assert error.value.error_code == ontology_common.ErrorCode.AIDP_RESPONSE_ERROR


def test_request_maps_business_and_client_errors(client):
    client.request.return_value = _response(
        409,
        json_body={"error": {"code": 1025, "message": "exists"}},
    )
    with pytest.raises(ontology_common.AppException) as error:
        ontology_common._ontology_request("http://aidp.example", "key", "GET", "/x", operation="op")
    assert error.value.error_code == ontology_common.ErrorCode.COMMON_RESOURCE_ALREADY_EXISTS

    client.request.return_value = _response(404, json_body={"message": "missing"})
    with pytest.raises(ontology_common.AppException) as error:
        ontology_common._ontology_request("http://aidp.example", "key", "GET", "/x", operation="op")
    assert error.value.error_code == ontology_common.ErrorCode.COMMON_RESOURCE_NOT_FOUND


def test_request_maps_connection_error(client):
    client.request.side_effect = httpx.ConnectError("down")
    with pytest.raises(ontology_common.AppException) as error:
        ontology_common._ontology_request("http://aidp.example", "key", "GET", "/x", operation="op")
    assert error.value.error_code == ontology_common.ErrorCode.AIDP_CONNECTION_ERROR


def test_log_business_failure(caplog):
    ontology_common._log_business_failure({"code": 1056, "message": "missing"}, "op")
    ontology_common._log_business_failure({"code": "200"}, "op")
    ontology_common._log_business_failure([], "op")
    assert "business failure" in caplog.text


@pytest.mark.parametrize(
    "payload,page,page_size,expected",
    [
        (
            {"value": [{"id": 1}], "total_count": 1},
            1,
            20,
            (1, 1, False),
        ),
        (
            {"items": [{"id": 1}], "total": 2},
            1,
            20,
            (1, 2, False),
        ),
        (
            {"data": {"value": [{"id": 1}], "has_next": True, "total_count": 30}},
            1,
            20,
            (1, 30, True),
        ),
        (
            {"items": [{"id": 1}], "total": 21},
            2,
            20,
            (1, 21, False),
        ),
        (
            {"items": [], "total": 41},
            3,
            20,
            (0, 41, False),
        ),
    ],
)
def test_list_envelope_variants(payload, page, page_size, expected):
    envelope = ontology_common._list_envelope(payload, page=page, page_size=page_size)
    assert (len(envelope["value"]), envelope["total_count"], envelope["has_more"]) == expected


def test_domain_and_entity_updates_require_a_change():
    with pytest.raises(ValidationError):
        ontology_models.OntologyDomainUpdateRequest()
    with pytest.raises(ValidationError):
        ontology_models.OntologyEntityUpdateRequest()


def test_entity_create_rejects_duplicate_property_names():
    with pytest.raises(ValidationError):
        ontology_models.OntologyEntityCreateRequest(
            api_name="Phone",
            properties=[
                {"api_name": "price"},
                {"api_name": "price"},
            ],
        )


def test_entity_create_defaults_display_name_and_property_type():
    entity = ontology_models.OntologyEntityCreateRequest(
        api_name="Phone", properties=[{"api_name": "price"}]
    )
    assert entity.display_name is None
    assert entity.properties[0].data_type == "string"


def test_binding_and_relation_validation():
    assert ontology_models.OntologyBindingRequest(kb_id=" kb ").target_kb_id == "kb"
    with pytest.raises(ValidationError):
        ontology_models.OntologyRelationRequest(
            api_name="related",
            display_name="related",
            source_kind="entity",
            source_id="1",
            object_kind="type",
            object_id="2",
        )


def test_metadata_json_boundaries():
    assert ontology_validation._validate_metadata_json({"f": "v"}) == {"f": "v"}
    with pytest.raises(ValueError):
        ontology_validation._validate_metadata_json({})
    with pytest.raises(ValueError):
        ontology_validation._validate_metadata_json({f"f{i}": "v" for i in range(21)})


def test_utf8_byte_validator():
    validate = ontology_validation._utf8_max_bytes(4)
    assert validate("abc") == "abc"
    with pytest.raises(ValueError):
        validate("中文")



def test_ontology_write_requires_manager(monkeypatch):
    from ext_components.aidp.apps import aidp_ontology_validation as validation

    monkeypatch.setattr(
        validation, "get_user_role_by_tenant", lambda *_a, **_kw: ["DEV"]
    )
    response = _client().post(
        "/aidp-mgmt/ontology/domains",
        headers=_bearer(),
        json={"name": "Demo"},
    )
    assert response.status_code == 403


def test_domain_path_and_metadata_errors(monkeypatch):
    from ext_components.aidp.apps import aidp_ontology_metadata_routes as routes

    _allow_manager(monkeypatch)
    monkeypatch.setattr(routes.perms, "require_permission", lambda *a, **kw: None)

    async def load_fields(*_a, **_kw):
        return [{"id": 2, "field_name": "f", "field_type": "string"}]

    monkeypatch.setattr(routes, "_load_metadata_fields", load_fields)
    monkeypatch.setattr(
        routes,
        "_find_metadata_field",
        lambda _fields, ref: None,
    )
    client = _client()
    assert client.get(
        "/aidp-mgmt/ontology/domains/not-a-number", headers=_bearer()
    ).status_code == 422
    assert client.post(
        "/aidp-mgmt/ontology/domains/1/metadata-fields",
        headers=_bearer(),
        json={"field_name": "f", "field_type": "string"},
    ).status_code == 400
    assert client.delete(
        "/aidp-mgmt/ontology/domains/1/metadata-fields/f", headers=_bearer()
    ).status_code == 400


def test_batch_async_and_invalid_import(monkeypatch):
    from ext_components.aidp.apps import aidp_ontology_batch_routes as routes

    _allow_manager(monkeypatch)
    monkeypatch.setattr(
        routes,
        "export_ontology_impl",
        lambda *a, **kw: {"data": {"task_id": "1", "status": "pending"}},
    )
    monkeypatch.setattr(
        routes, "get_ontology_domain_impl", lambda *a, **kw: {"name": "Demo"}
    )
    client = _client()
    assert client.post(
        "/aidp-mgmt/ontology/domains/1/export",
        headers=_bearer(),
        json={"include_properties": True, "include_relations": True},
    ).status_code == 200
    assert client.post(
        "/aidp-mgmt/ontology/domains/1/import",
        headers=_bearer(),
        json={"file_name": "bad.json", "document": {"Demo": {"types": "bad"}}},
    ).status_code == 400
