# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Unit query/validation proof; actual PostgreSQL transactions belong to MOP-D3-001."""

import importlib.util
import sys
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest
from nexent.core.model_service.profiles.contracts import VersionedReference
from nexent.core.model_service.profiles.instruction_mapping import (
    resolve_instruction_mapping,
)
from nexent.core.model_service.profiles.outlet_storage import (
    encode_resolved_model_profile,
)
from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import SQLAlchemyError

ROOT = Path(__file__).resolve().parents[3]
REFERENCE = VersionedReference(ref="fixture_v1", version=1)
REGISTRY = {
    key: [REFERENCE]
    for key in (
        "protocol",
        "auth",
        "adapter",
        "code_converter",
        "native_converter",
        "parameter_transform",
    )
}


def load(name, path, monkeypatch):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def database(monkeypatch):
    # Keep actual ORM metadata and exceptions; isolate only the DB session boundary.
    from contracts.errors import exceptions

    client = ModuleType("management.db.client")
    client.sessions = []

    @contextmanager
    def get_session(session=None):
        client.sessions.append(session)
        yield session

    client.get_db_session = get_session
    monkeypatch.setitem(sys.modules, client.__name__, client)
    database = load(
        "_outlet_unit_db.model_outlet_db",
        "backend/management/db/model/outlets.py",
        monkeypatch,
    )
    return database, client, exceptions


@pytest.fixture
def profile():
    role = VersionedReference(ref="system_only_v1", version=1)
    return ResolvedModelProfile.model_validate(
        {
            "schema_version": 1,
            "outlet_id": 12,
            "config_revision": 1,
            "identity": {
                "tenant_id": "tenant-one",
                "display_name": "display",
                "model_type": "llm",
                "provider_id": "provider",
                "request_model_id": "Exact/Model",
                "provider_key": None,
                "model_profile_key": None,
            },
            "connection": {
                "base_url": "http://localhost/v1",
                "ssl_verify": False,
                "timeout_seconds": 120,
                "concurrency_limit": None,
                "credential_ref": {"kind": "model_record", "model_id": 12},
            },
            "connection_rules": {
                "credential_kind": "model_record",
                "relative_path": "/chat/completions",
                "method": "POST",
                "headers": {},
            },
            "context_configuration": {
                "output_reserve_tokens": None,
                "tokenizer_family": None,
                "capacity_source": None,
                "capability_profile_version": None,
            },
            "capabilities": {},
            "instruction_mapping": resolve_instruction_mapping(role).model_dump(
                mode="json"
            ),
            "parameter_rules": [
                {
                    "key": "custom",
                    "schema": {},
                    "visible": True,
                    "editable": True,
                    "required": False,
                    "allowed_scopes": ["outlet", "conversation"],
                    "ui_group": "common",
                    "owner": "provider",
                    "source": {},
                    "api_binding": {
                        "path": "/custom",
                        "transform_ref": "fixture_v1",
                        "transform_version": 1,
                    },
                }
            ],
            "parameter_values": {"custom": False},
            "extra_api_parameters": [],
            "bindings": {
                **{
                    key: REFERENCE.model_dump()
                    for key in REGISTRY
                    if key != "parameter_transform"
                },
                "role_mapping": role.model_dump(),
            },
            "provenance": {
                "atomic_refs": {
                    "model": None,
                    "provider": None,
                    "provider_model": None,
                },
                "interpretation_versions": {
                    "source_parser": None,
                    "source_mapping": None,
                    "supplement_schema": None,
                    "composer": None,
                },
                "overrides": [],
                "field_sources": [],
                "provider_metadata": {},
            },
        }
    )


def row(profile):
    return encode_resolved_model_profile(profile, registered_references=REGISTRY)


def statement(session, index=0):
    return (
        session.execute.call_args_list[index]
        .args[0]
        .compile(dialect=postgresql.dialect())
    )


def update(database, profile, session, **kwargs):
    return database.update_resolved_model_record(
        profile,
        1,
        "actor",
        "tenant-one",
        registered_references=REGISTRY,
        db_session=session,
        **kwargs,
    )


