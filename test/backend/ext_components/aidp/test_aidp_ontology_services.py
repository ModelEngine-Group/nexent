# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Coverage for the ontology proxy service layer with a stubbed transport."""

from __future__ import annotations

import copy
import importlib
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
for _p in (str(_REPO_ROOT), str(_REPO_ROOT / "backend"), str(_REPO_ROOT / "sdk")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

SERVER = "http://aidp.example"
KEY = "key"

PAYLOAD = {
    "data": {
        "id": 1,
        "name": "Demo",
        "api_name": "Phone",
        "domain_name": "Demo",
        "count": 1,
    },
    "value": [
        {"id": 1, "name": "Demo", "rule_id": "1", "kds_id": "kb", "field_name": "f"}
    ],
    "items": [
        {"api_name": "Phone", "entity_id": "1", "rule_id": "1", "id": 1}
    ],
    "task_list": [{"id": "1", "status": "completed"}],
    "result": {"imported_count": 1},
    "total": 1,
    "total_count": 1,
    "has_next": False,
    "folder_path": "/",
    "count": 1,
}


@pytest.fixture
def transport(monkeypatch):
    calls: list[tuple] = []

    def fake(*args, **kwargs):
        calls.append((args, kwargs))
        return copy.deepcopy(PAYLOAD)

    modules = [
        importlib.import_module(f"ext_components.aidp.services.{name}")
        for name in (
            "aidp_ontology_domain_service",
            "aidp_ontology_task_service",
            "aidp_ontology_binding_service",
            "aidp_ontology_rule_service",
            "aidp_ontology_metadata_service",
        )
    ]
    for module in modules:
        monkeypatch.setattr(module, "_ontology_request", fake)
    return calls


def test_domain_and_entity_operations(transport):
    module = importlib.import_module(
        "ext_components.aidp.services.aidp_ontology_domain_service"
    )

    module.list_ontology_domains_impl(SERVER, KEY, search=" Demo ", page=2, page_size=5)
    module.get_ontology_domain_impl(SERVER, KEY, "1")
    module.create_ontology_domain_impl(SERVER, KEY, {"name": "Demo"})
    module.update_ontology_domain_impl(SERVER, KEY, "1", {"name": "Demo"})
    module.delete_ontology_domain_impl(SERVER, KEY, "1")
    module.list_ontology_entities_impl(
        SERVER, KEY, "1", keyword=" Phone ", kind="entity"
    )
    module.get_ontology_entity_impl(SERVER, KEY, "1", "2")
    module.create_ontology_entity_impl(SERVER, KEY, "1", {"api_name": "Phone"})
    module.update_ontology_entity_impl(SERVER, KEY, "1", "2", {"display_name": "x"})
    module.delete_ontology_entity_impl(SERVER, KEY, "1", "2")
    module.list_ontology_relations_impl(
        SERVER, KEY, "1", page=2, size=5, relation_type="is_a"
    )
    module.create_ontology_relation_impl(SERVER, KEY, "1", {"api_name": "r"})
    module.delete_ontology_relation_impl(SERVER, KEY, "1", "2")

    assert len(transport) == 13


def test_domain_delete_tolerates_not_found(transport, monkeypatch):
    from ext_components.aidp.services import aidp_ontology_domain_service as module

    def missing(*args, **kwargs):
        raise module.AppException(
            None, "missing", details={"upstream_status": 404}
        )

    monkeypatch.setattr(module, "_ontology_request", missing)
    assert module.delete_ontology_domain_impl(SERVER, KEY, "1") is True


def test_task_operations(transport):
    module = importlib.import_module(
        "ext_components.aidp.services.aidp_ontology_task_service"
    )

    module.list_tasks_impl(SERVER, KEY, page=2, page_size=5, task_type="import")
    module.get_task_impl(SERVER, KEY, "1")
    assert len(transport) == 2


def test_binding_operations(transport):
    module = importlib.import_module(
        "ext_components.aidp.services.aidp_ontology_binding_service"
    )

    module.list_ontology_bindings_impl(SERVER, KEY, domain_id="1")
    module.create_ontology_binding_impl(SERVER, KEY, domain_id="1", kds_id="kb")
    module.delete_ontology_binding_impl(SERVER, KEY, domain_id="1", kds_id="kb")
    assert len(transport) == 3


def test_rule_operations(transport):
    module = importlib.import_module(
        "ext_components.aidp.services.aidp_ontology_rule_service"
    )

    module.list_ontology_rules_impl(SERVER, KEY, "1")
    module.count_ontology_rules_impl(SERVER, KEY, "1")
    module.get_ontology_rule_impl(SERVER, KEY, "1", "2")
    module.create_ontology_rule_impl(SERVER, KEY, "1", {"name": "r"})
    module.update_ontology_rule_impl(SERVER, KEY, "1", "2", {"name": "r"})
    module.delete_ontology_rule_impl(SERVER, KEY, "1", "2")
    assert len(transport) == 6


def test_metadata_operations(transport):
    module = importlib.import_module(
        "ext_components.aidp.services.aidp_ontology_metadata_service"
    )

    module.list_ontology_metadata_fields_impl(SERVER, KEY, "1")
    module.create_ontology_metadata_field_impl(
        SERVER, KEY, "1", field_name="f", field_type="string"
    )
    module.rename_ontology_metadata_field_impl(
        SERVER, KEY, "1", metadata_id="2", new_field_name="new"
    )
    module.delete_ontology_metadata_field_impl(SERVER, KEY, "1", "2")
    module.batch_unbind_metadata_impl(
        SERVER, KEY, "1", metadata_ids=[2], creator="admin"
    )
    module.export_chunk_metadata_impl(SERVER, KEY, "1", kds_id=3, chunk_id=4)
    module.import_chunk_metadata_impl(
        SERVER,
        KEY,
        "1",
        kds_id=3,
        metadata_json={"f": "v"},
        chunk_id_list=[4],
    )
    module.batch_unbind_metadata_sync_impl(SERVER, KEY, "1", metadata_ids=[2])
    assert len(transport) >= 8
