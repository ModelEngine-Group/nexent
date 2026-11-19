# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Shared fixtures for the AIDP ontology and Metadata formal test cases.

The helper keeps each Case script focused on its assertions: it prepares the
backend import path, substitutes authentication/permission boundaries, can run
the standalone AIDP mock over real HTTP, and provides a small in-memory fake of
the upstream ontology service for API-contract cases.
"""
from __future__ import annotations

import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_DIR = REPO_ROOT / "backend"
SDK_DIR = REPO_ROOT / "sdk"
MOCK_SERVER = REPO_ROOT / "test/ext_components/aidp/mock_servers/aidp_mgmt_mock_server.py"


def ensure_backend_imports() -> None:
    for path in (str(BACKEND_DIR), str(SDK_DIR)):
        if path not in sys.path:
            sys.path.insert(0, path)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class MockAidp:
    """Run the standalone AIDP mock on a loopback port for one test."""

    def __init__(self, tmp_path: Path):
        self.tmp_path = tmp_path
        self.port = free_port()
        self.process: subprocess.Popen | None = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self) -> "MockAidp":
        state_file = self.tmp_path / "aidp-ontology-mock-state.json"
        env = {
            "AIDP_MOCK_STATE_FILE": str(state_file),
            "PYTHONUNBUFFERED": "1",
        }
        self.process = subprocess.Popen(
            [
                sys.executable,
                str(MOCK_SERVER),
                "--port",
                str(self.port),
                "--upload-seconds",
                "0",
            ],
            env={**__import__("os").environ, **env},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"{self.base_url}/health", timeout=1) as response:
                    if response.status == 200:
                        return self
            except Exception:
                time.sleep(0.2)
        self.__exit__(None, None, None)
        raise RuntimeError("AIDP mock did not become healthy")

    def __exit__(self, *_exc: Any) -> None:
        if self.process is None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
        self.process = None


class FakeAidpOntology:
    """In-memory replacement for ``aidp_ontology_service`` upstream calls.

    Only the service functions actually used by the HTTP handlers are
    provided, so a missing substitution fails loudly instead of silently
    reaching the network.
    """

    def __init__(self) -> None:
        self.domains: dict[str, dict[str, Any]] = {
            "1": {"od_id": "1", "name": "电商本体", "description": "desc", "create_time": 1},
            "2": {"od_id": "2", "name": "客服本体", "description": "", "create_time": 2},
        }
        self.entities: dict[str, list[dict[str, Any]]] = {
            "1": [
                {
                    "entity_id": "101",
                    "api_name": "Category",
                    "display_name": "类目",
                    "description": "",
                    "kind": "type",
                    "type_id": None,
                    "properties": [],
                    "primary_properties": [],
                },
                {
                    "entity_id": "201",
                    "api_name": "Smartphone",
                    "display_name": "智能手机",
                    "description": "",
                    "kind": "entity",
                    "type_id": "101",
                    "properties": [],
                    "primary_properties": [],
                },
            ],
            "2": [],
        }
        self.bindings: list[dict[str, str]] = [
            {"id": "1", "od_id": "1", "kds_id": "kb-a"},
            {"id": "2", "od_id": "1", "kds_id": "kb-b"},
            {"id": "3", "od_id": "2", "kds_id": "kb-c"},
        ]
        self.fields: dict[str, list[dict[str, Any]]] = {
            "1": [
                {
                    "id": 101,
                    "fieldName": "doc_type",
                    "fieldType": "string",
                    "columnIndex": 1,
                    "candidates": ["FAQ", "Guide"],
                    "associatedChunkCount": 12,
                    "status": "新增成功",
                },
                {
                    "id": 102,
                    "fieldName": "publish_year",
                    "fieldType": "number",
                    "columnIndex": 2,
                    "candidates": ["2020 ~ 2030"],
                    "associatedChunkCount": 0,
                    "status": "新增成功",
                },
                {
                    "id": 103,
                    "fieldName": "effective_date",
                    "fieldType": "time",
                    "columnIndex": 3,
                    "candidates": ["2025-01-01 ~ 2026-12-31"],
                    "associatedChunkCount": 0,
                    "status": "新增成功",
                },
            ],
            "2": [
                {
                    "id": 201,
                    "fieldName": "channel",
                    "fieldType": "string",
                    "columnIndex": 1,
                    "candidates": ["电话", "在线"],
                    "associatedChunkCount": 4,
                    "status": "新增成功",
                }
            ],
        }
        self.chunks: dict[str, list[dict[str, Any]]] = {
            "kb-a": [
                {
                    "chunk_id": 1001,
                    "chunk_text": "alpha text",
                    "chunk_type": "TEXT",
                    "file_name": "a.txt",
                    "file_url": "",
                    "page_ids": [],
                    "metadata": {"doc_type": "FAQ"},
                    "_file_uuid": "file-a",
                }
            ],
            "kb-b": [
                {
                    "chunk_id": 2001,
                    "chunk_text": "beta text",
                    "chunk_type": "TEXT",
                    "file_name": "b.txt",
                    "file_url": "",
                    "page_ids": [],
                    "metadata": {},
                    "_file_uuid": "file-b",
                }
            ],
        }
        self.calls: list[str] = []
        self.last_search: str | None = None

    # ---- domain ----
    def list_ontology_domains_impl(self, _server, _key, *, page=1, page_size=20, search=None, **_kw):
        self.calls.append("list_domains")
        self.last_search = search
        items = list(self.domains.values())
        if search:
            needle = search.strip().lower()
            items = [item for item in items if needle in item["name"].lower()]
        return {
            "value": items[(page - 1) * page_size: page * page_size],
            "total_count": len(items),
            "has_more": page * page_size < len(items),
            "total_reliable": True,
        }

    def get_ontology_domain_impl(self, _server, _key, domain_id, **_kw):
        self.calls.append("get_domain")
        return dict(self.domains[str(domain_id)])

    def create_ontology_domain_impl(self, _server, _key, body, **_kw):
        self.calls.append("create_domain")
        new_id = str(max(int(value) for value in self.domains) + 1)
        record = {"od_id": new_id, "name": body["name"], "description": body.get("description", ""), "create_time": 1}
        self.domains[new_id] = record
        self.entities[new_id] = []
        return dict(record)

    def update_ontology_domain_impl(self, _server, _key, domain_id, body, **_kw):
        self.calls.append("update_domain")
        self.domains[str(domain_id)].update(body)
        return dict(self.domains[str(domain_id)])

    def delete_ontology_domain_impl(self, _server, _key, domain_id, **_kw):
        self.calls.append("delete_domain")
        self.domains.pop(str(domain_id), None)
        return True

    # ---- entities ----
    def list_ontology_entities_impl(
        self, _server, _key, domain_id, *, page=1, page_size=20, size=None, keyword=None, kind=None, **_kw
    ):
        page_size = size or page_size
        self.calls.append("list_entities")
        items = list(self.entities.get(str(domain_id), []))
        if kind:
            items = [item for item in items if item.get("kind") == kind]
        if keyword:
            needle = keyword.lower()
            items = [
                item
                for item in items
                if needle in item["api_name"].lower() or needle in (item.get("display_name") or "").lower()
            ]
        return {
            "value": items[(page - 1) * page_size: page * page_size],
            "total_count": len(items),
            "has_more": page * page_size < len(items),
            "total_reliable": True,
        }

    def get_ontology_entity_impl(self, _server, _key, domain_id, entity_id, **_kw):
        self.calls.append("get_entity")
        for item in self.entities[str(domain_id)]:
            if item["entity_id"] == str(entity_id):
                return dict(item)
        raise AssertionError("entity not found in fake")

    def create_ontology_entity_impl(self, _server, _key, domain_id, body, **_kw):
        self.calls.append("create_entity")
        record = {
            "entity_id": str(300 + len(self.entities[str(domain_id)])),
            **body,
            "properties": body.get("properties") or [],
            "primary_properties": body.get("primary_properties") or [],
        }
        self.entities[str(domain_id)].append(record)
        return dict(record)

    def update_ontology_entity_impl(self, _server, _key, domain_id, entity_id, body, **_kw):
        self.calls.append("update_entity")
        for item in self.entities[str(domain_id)]:
            if item["entity_id"] == str(entity_id):
                item.update(body)
                return dict(item)
        raise AssertionError("entity not found in fake")

    def delete_ontology_entity_impl(self, _server, _key, domain_id, entity_id, **_kw):
        self.calls.append("delete_entity")
        self.entities[str(domain_id)] = [
            item for item in self.entities[str(domain_id)] if item["entity_id"] != str(entity_id)
        ]
        return True

    # ---- bindings ----
    def list_ontology_bindings_impl(self, _server, _key, *, domain_id=None, kds_id=None, **_kw):
        self.calls.append("list_bindings")
        return [
            dict(binding)
            for binding in self.bindings
            if (domain_id is None or binding["od_id"] == str(domain_id))
            and (kds_id is None or binding["kds_id"] == str(kds_id))
        ]

    def create_ontology_binding_impl(self, _server, _key, *, domain_id, kds_id, **_kw):
        self.calls.append("create_binding")
        binding = {
            "id": str(len(self.bindings) + 1),
            "od_id": str(domain_id),
            "kds_id": str(kds_id),
        }
        self.bindings.append(binding)
        return {"id": binding["id"], "kb_id": binding["kds_id"], "domain_id": binding["od_id"]}

    def delete_ontology_binding_impl(
        self, _server, _key, *, binding_id=None, domain_id=None, kds_id=None, **_kw
    ):
        self.calls.append("delete_binding")
        if binding_id is not None:
            self.bindings[:] = [
                binding for binding in self.bindings if str(binding.get("id")) != str(binding_id)
            ]
        else:
            self.bindings[:] = [
                binding
                for binding in self.bindings
                if not (
                    binding["od_id"] == str(domain_id)
                    and binding["kds_id"] == str(kds_id)
                )
            ]
        return True

    # ---- metadata definitions ----
    def list_ontology_metadata_fields_impl(self, _server, _key, domain_id, *, page=1, page_size=100, **_kw):
        self.calls.append("list_fields")
        items = [
            {
                "id": item.get("id"),
                "field_name": item["fieldName"],
                "field_type": item["fieldType"],
                "column_index": item.get("columnIndex"),
                "candidates": item.get("candidates", []),
                "extended_properties": [],
                "associated_chunk_count": item.get("associatedChunkCount"),
                "create_time": item.get("createTime"),
                "status": item.get("status"),
                "demo_task": item.get("demoTask"),
            }
            for item in self.fields.get(str(domain_id), [])
        ]
        return {
            "value": items,
            "total_count": len(items),
            "has_more": False,
            "total_reliable": True,
        }

    def create_ontology_metadata_field_impl(self, _server, _key, domain_id, *, field_name, field_type, **_kw):
        self.calls.append("create_field")
        fields = self.fields[str(domain_id)]
        all_ids = [
            int(item["id"])
            for group in self.fields.values()
            for item in group
            if str(item.get("id", "")).isdigit()
        ]
        record = {
            "id": (max(all_ids) + 1) if all_ids else 1,
            "fieldName": field_name,
            "fieldType": field_type,
            "columnIndex": len(fields) + 1,
            "candidates": [],
            "associatedChunkCount": 0,
            "status": "新增成功",
        }
        fields.append(record)
        return dict(record)

    def rename_ontology_metadata_field_impl(
        self, _server, _key, domain_id, *, metadata_id, new_field_name, **_kw
    ):
        self.calls.append("rename_field")
        for item in self.fields[str(domain_id)]:
            if str(item.get("id")) == str(metadata_id):
                item["fieldName"] = new_field_name
                return dict(item)
        raise AssertionError("field missing in fake")

    def delete_ontology_metadata_field_impl(self, _server, _key, domain_id, metadata_id, **_kw):
        self.calls.append("delete_field")
        self.fields[str(domain_id)] = [
            item
            for item in self.fields[str(domain_id)]
            if str(item.get("id")) != str(metadata_id)
        ]
        return True

    def batch_unbind_metadata_impl(
        self, _server, _key, domain_id, *, metadata_ids, creator, **_kw
    ):
        self.calls.append("batch_unbind")
        for item in self.fields.get(str(domain_id), []):
            if str(item.get("id")) in {str(value) for value in metadata_ids}:
                item["associatedChunkCount"] = 0
                item["status"] = "解绑中"
        return {
            "task_id": "fake-unbind-1",
            "status": "RUNNING",
            "progress": 0,
            "creator": creator,
        }

    # ---- chunks ----
    def list_aidp_chunks_impl(self, _server, _key, kds_id, *, file_uuid, page=1, page_size=20, **_kw):
        self.calls.append("list_chunks")
        items = [chunk for chunk in self.chunks.get(kds_id, []) if chunk["_file_uuid"] == file_uuid]
        return {
            "value": [
                {key: value for key, value in chunk.items() if not key.startswith("_")}
                for chunk in items
            ],
            "total_count": len(items),
            "has_more": False,
            "total_reliable": True,
        }

    def get_aidp_chunk_impl(self, _server, _key, kds_id, chunk_id, **_kw):
        self.calls.append("get_chunk")
        for chunk in self.chunks.get(kds_id, []):
            if str(chunk["chunk_id"]) == str(chunk_id):
                return {key: value for key, value in chunk.items() if not key.startswith("_")}
        from contracts.errors.codes import ErrorCode
        from contracts.errors.exceptions import AppException

        raise AppException(
            ErrorCode.AIDP_SERVICE_ERROR,
            "Chunk not found",
            details={"upstream_status": 404},
        )

    def batch_set_chunk_metadata_impl(self, _server, _key, kds_id, *, domain_id, metadata, chunk_ids, **_kw):
        self.calls.append("batch_metadata")
        success = []
        failed = []
        for chunk_id in chunk_ids:
            chunk = next(
                (item for item in self.chunks.get(kds_id, []) if str(item["chunk_id"]) == str(chunk_id)),
                None,
            )
            if chunk is None:
                failed.append({"chunk_id": chunk_id, "message": "missing"})
            else:
                chunk["metadata"].update(metadata)
                success.append({"chunk_id": chunk_id})
        return {
            "total": len(chunk_ids),
            "success_count": len(success),
            "failed_count": len(failed),
            "success_list": success,
            "failed_list": failed,
        }

    # ---- import / export ----
    def export_ontology_impl(self, _server, _key, domain_id, **_kw):
        self.calls.append("export")
        return {
            "code": 200,
            "message": "OK",
            "data": {
                "电商本体": {
                    "display_name": "电商本体",
                    "description": "",
                    "types": [{"api_name": "Category", "display_name": "类目"}],
                    "entities": [{"api_name": "Smartphone", "display_name": "智能手机"}],
                    "relations": [],
                }
            },
        }

    def import_ontology_impl(self, _server, _key, domain_id, body, **_kw):
        self.calls.append("import")
        return {
            "code": 200,
            "message": "OK",
            "data": {
                "imported_count": len(body.get("ENTITIES") or []),
                "skipped_count": 0,
                "failed_count": 0,
                "relation_imported": len(body.get("RELATIONS") or []),
                "relation_failed": 0,
                "first_error": None,
                "errors": [],
            },
        }

    def install(self, monkeypatch) -> None:
        from ext_components.aidp.services import aidp_ontology_service as service

        for name in (
            "list_ontology_domains_impl",
            "get_ontology_domain_impl",
            "create_ontology_domain_impl",
            "update_ontology_domain_impl",
            "delete_ontology_domain_impl",
            "list_ontology_entities_impl",
            "get_ontology_entity_impl",
            "create_ontology_entity_impl",
            "update_ontology_entity_impl",
            "delete_ontology_entity_impl",
            "list_ontology_bindings_impl",
            "create_ontology_binding_impl",
            "delete_ontology_binding_impl",
            "list_ontology_metadata_fields_impl",
            "create_ontology_metadata_field_impl",
            "rename_ontology_metadata_field_impl",
            "delete_ontology_metadata_field_impl",
            "batch_unbind_metadata_impl",
            "list_aidp_chunks_impl",
            "get_aidp_chunk_impl",
            "batch_set_chunk_metadata_impl",
            "export_ontology_impl",
            "import_ontology_impl",
        ):
            monkeypatch.setattr(service, name, getattr(self, name))


def configure_environment(
    monkeypatch,
    *,
    role: str = "ADMIN",
    permissions: dict[str, str] | None = None,
    kb_names: dict[str, str] | None = None,
    server_url: str = "http://aidp.invalid:30081",
    api_key: str = "test-key",
) -> None:
    """Replace auth, role and KB-permission boundaries for router tests."""
    ensure_backend_imports()
    from ext_components.aidp.apps import aidp_mgmt_app, aidp_ontology_app
    from ext_components.aidp.consts.aidp_exceptions import (
        AidpKbNotFoundError,
        AidpKbPermissionDeniedError,
    )
    from ext_components.aidp.services import aidp_permission_service as perms

    permission_map = dict(permissions or {"kb-a": "EDIT", "kb-b": "READ_ONLY", "kb-c": "EDIT"})
    names = dict(kb_names or {"kb-a": "KB A", "kb-b": "KB B", "kb-c": "KB C"})

    async def fake_auth(_request):
        return ("user-test", "tenant-test")

    monkeypatch.setattr(aidp_ontology_app, "_auth", fake_auth)
    monkeypatch.setattr(
        aidp_ontology_app,
        "get_user_role_by_tenant",
        lambda _user, _tenant: role,
    )
    monkeypatch.setattr(aidp_mgmt_app, "AIDP_SERVER_URL", server_url)
    monkeypatch.setattr(aidp_mgmt_app, "AIDP_API_KEY", api_key)

    def fake_require(kb_id, user_id, tenant_id, required="READ"):
        level = permission_map.get(kb_id)
        if level is None:
            raise AidpKbNotFoundError(kb_id, tenant_id)
        ranks = {"READ_ONLY": 1, "EDIT": 2, "CREATOR": 2}
        needed = 1 if required == "READ" else 2
        if ranks.get(level, 0) < needed:
            raise AidpKbPermissionDeniedError(kb_id, user_id, required)
        return SimpleNamespace(permission=level)

    monkeypatch.setattr(perms, "require_permission", fake_require)
    monkeypatch.setattr(
        perms,
        "filter_accessible_kds",
        lambda ids, _user, _tenant: [item for item in ids if item in permission_map],
    )
    monkeypatch.setattr(
        aidp_ontology_app.aidp_permission_db,
        "get_permission_by_kb_id",
        lambda kb_id, _tenant: {"kds_name": names.get(kb_id, kb_id)},
    )


def build_client():
    """Build a FastAPI app containing only the ontology router."""
    ensure_backend_imports()
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from management.utils.app_factory import register_exception_handlers
    from ext_components.aidp.apps.aidp_ontology_app import aidp_ontology_router

    app = FastAPI()
    app.include_router(aidp_ontology_router)
    register_exception_handlers(app)
    return TestClient(app)


def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def assert_no_internal_task_endpoint() -> None:
    """The temporary UI must never call AIDP's internal ontology task API."""
    for relative in (
        "backend/ext_components/aidp/apps/aidp_ontology_app.py",
        "backend/ext_components/aidp/services/aidp_ontology_service.py",
        "backend/ext_components/aidp/services/aidp_ontology_transform.py",
    ):
        text = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert "kmsctrl" not in text
        assert "ontology/tasks" not in text
