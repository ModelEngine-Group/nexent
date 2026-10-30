# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Real PostgreSQL, product sessions and resolved outlet snapshot persistence."""

import json
from pathlib import Path

import pytest
from nexent.core.model_service.profiles.contracts import VersionedReference
from nexent.core.model_service.profiles.instruction_mapping import (
    resolve_instruction_mapping,
)
from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile
from shared.factories.scratch_database import isolated_product_database
from shared.postgres import apply_product_postgres_env
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError

pytestmark = [pytest.mark.case_id("MOP-D3-001"), pytest.mark.stage("D3")]
from nexent.core.model_service.registry import model_service_references
from nexent.core.model_service.profiles.thinking_configuration import configure_outlet_policy

REF = VersionedReference(ref="identity_v1", version=1)
REGISTRY = model_service_references()
DUMMY = "non-secret-test-credential"


def parameter(key, schema):
    return {
        "key": key, "schema": schema, "visible": True, "editable": True,
        "required": False, "allowed_scopes": ["outlet", "conversation"],
        "ui_group": "common", "owner": "provider", "source": {"rule_id": "db-fixture"},
        "api_binding": {"path": "/" + key, "transform_ref": REF.ref, "transform_version": 1},
    }


def profile():
    role = VersionedReference(ref="system_only_v1", version=1)
    return configure_outlet_policy(ResolvedModelProfile.model_validate({
        "schema_version": 1, "outlet_id": None, "config_revision": 1,
        "identity": {"tenant_id": "db-tenant-a", "display_name": "outlet fixture",
                     "model_type": "llm", "provider_id": "custom-provider",
                     "request_model_id": "Exact/Model", "provider_key": None, "model_profile_key": None},
        "connection": {"base_url": "https://fixture.invalid/v1", "ssl_verify": False,
                       "timeout_seconds": 120, "concurrency_limit": None,
                       "credential_ref": {"kind": "model_record", "model_id": None}},
        "connection_rules": {"credential_kind": "model_record", "relative_path": "/chat/completions",
                             "method": "POST", "headers": {}},
        "context_configuration": {"output_reserve_tokens": None, "tokenizer_family": None,
                                  "capacity_source": "operator", "capability_profile_version": None},
        "capabilities": {"context": {"combined_window": 200000, "output_limit": 32768}}, "instruction_mapping": resolve_instruction_mapping(role).model_dump(mode="json"),
        "parameter_rules": [parameter("temperature", {"type": "integer"}),
                            parameter("custom_switch", {"type": "boolean"}),
                            parameter("custom_null", {"type": "null"}),
                            parameter("max_output_tokens", {"type": "integer", "minimum": 1})],
        "parameter_values": {"temperature": 0, "custom_switch": False, "custom_null": None, "max_output_tokens": 4096},
        "extra_api_parameters": [{"path": "/vendor/option", "value": False}],
        "bindings": {**{key: refs[0].model_dump() for key, refs in REGISTRY.items() if key != "parameter_transform"},
                     "role_mapping": role.model_dump()},
        "provenance": {"atomic_refs": {"model": None, "provider": None, "provider_model": None},
                       "interpretation_versions": {"source_parser": None, "source_mapping": None,
                                                   "supplement_schema": None, "composer": None},
                       "overrides": [], "field_sources": [], "provider_metadata": {}},
    }))


@pytest.fixture
def database(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "backend"))
    apply_product_postgres_env()
    from contracts.errors.exceptions import ModelOutletConflictError, ModelOutletDatabaseError
    from management.db import client as client
    from management.db.model import outlets as model_outlet_db
    from management.db.model.models import ModelRecord

    with isolated_product_database():
        yield client, model_outlet_db, ModelRecord, ModelOutletConflictError, ModelOutletDatabaseError


def create(db, session=None):
    return db.create_resolved_model_record(profile(), "creator", "db-tenant-a",
                                          registered_references=REGISTRY, api_key=DUMMY,
                                          http_headers={"x-gateway": DUMMY}, db_session=session)


def read(db, identifier, session=None, tenant="db-tenant-a"):
    return db.get_resolved_model_record(identifier, tenant, registered_references=REGISTRY, db_session=session)


def change(db, snapshot, session=None):
    return db.update_resolved_model_record(snapshot, snapshot.config_revision, "editor", "db-tenant-a",
                                          registered_references=REGISTRY, db_session=session)


def test_committed_snapshot_and_transaction_ownership(database):
    client, db, model, _, _ = database
    with client.db_client.session_maker() as session:
        identifier = create(db, session)
        loaded = read(db, identifier, session)
        assert session.in_transaction()
        assert loaded.outlet_id == identifier and loaded.config_revision == 1
        # A separate connection cannot see an uncommitted creation.
        assert read(db, identifier) is None
        session.commit()
    restored = read(db, identifier)
    assert DUMMY not in json.dumps(restored.model_dump(mode="json"))
    assert restored.parameter_values == {"temperature": 0, "custom_switch": False, "custom_null": None, "max_output_tokens": 4096}
    assert type(restored.parameter_values["temperature"]) is int
    assert restored.connection.credential_ref.model_id == identifier
    with client.get_db_session() as session:
        row = session.execute(select(model.__table__).where(model.model_id == identifier)).mappings().one()
        assert row["http_headers"] == {"x-gateway": DUMMY}
        assert row["api_key"] == DUMMY
        assert DUMMY not in json.dumps(row["resolved_profile"])
        assert DUMMY not in json.dumps(row["extra_params"])
        assert row["temperature"] == 0
        assert row["max_output_tokens"] == 32768 and row["default_max_output_tokens"] == 4096
        assert "max_output_tokens" not in row["extra_params"]["parameter_values"]
        assert "temperature" not in row["extra_params"]["parameter_values"]
        assert row["created_by"] == row["updated_by"] == "creator"
        assert row["create_time"] is not None and row["update_time"] is not None
        assert row["delete_flag"] == "N"


def test_stale_writer_tenant_and_deleted_row(database):
    client, db, model, conflict, _ = database
    identifier = create(db)
    with client.db_client.session_maker() as first, client.db_client.session_maker() as second:
        winner, loser = read(db, identifier, first), read(db, identifier, second)
        winner.parameter_values["temperature"] = 1
        loser.parameter_values["temperature"] = 2
        assert change(db, winner, first) == 2
        first.commit()
        with pytest.raises(conflict):
            change(db, loser, second)
        second.rollback()
    current = read(db, identifier)
    assert current.config_revision == 2 and current.parameter_values["temperature"] == 1
    assert read(db, identifier, tenant="db-tenant-b") is None
    with client.get_db_session() as session:
        row = session.execute(select(model.__table__).where(model.model_id == identifier)).mappings().one()
        assert row["created_by"] == "creator" and row["updated_by"] == "editor"
        session.execute(update(model).where(model.model_id == identifier).values(delete_flag="Y"))
    assert read(db, identifier) is None


def test_rollback_and_sanitized_actual_database_failure(database, caplog):
    client, db, _, _, database_error = database
    identifier = create(db)
    with client.db_client.session_maker() as session:
        transient = create(db, session)
        changed = read(db, identifier, session)
        changed.parameter_values["temperature"] = 3
        assert change(db, changed, session) == 2
        # Force a real server-side failure after both writes.
        with pytest.raises(DBAPIError) as failure:
            session.execute(text("SELECT 1 / 0"))
        assert "division by zero" in str(failure.value)
        session.rollback()
    assert read(db, transient) is None
    stable = read(db, identifier)
    assert stable.config_revision == 1 and stable.parameter_values["temperature"] == 0
    # A scratch-only constraint causes an actual INSERT error containing a bound dummy value.
    with client.get_db_session() as session:
        session.execute(text("ALTER TABLE nexent.model_record_t ADD CONSTRAINT outlet_fixture_reject CHECK (api_key IS NULL) NOT VALID"))
    with pytest.raises(database_error) as sanitized:
        create(db)
    assert str(sanitized.value) == "MODEL_OUTLET_DATABASE_ERROR"
    assert sanitized.value.__suppress_context__
    assert DUMMY not in str(sanitized.value) and DUMMY not in caplog.text
    assert read(db, identifier).config_revision == 1


def test_conversation_preferences_commit_cas_ownership_and_outlet_independence(database):
    client, db, _, conflict, _ = database
    from management.db.conversation import model_preferences as preferences
    from management.db.conversation.models import ConversationRecord
    from contracts.errors.exceptions import ConversationNotFoundError

    first, second = create(db), create(db)
    outlet_before = read(db, first)
    with client.get_db_session() as session:
        row = ConversationRecord(conversation_title="Parameter preference fixture", created_by="owner",
                                 updated_by="owner", delete_flag="N")
        session.add(row)
        session.flush()
        conversation_id = row.conversation_id
    assert preferences.model_preferences(conversation_id, "owner") == {
        "version": 0, "model_parameter_preferences": {}, "selected_model_id": None,
    }
    explicit = {"temperature": 0, "custom_switch": False, "custom_null": None}
    preferences.model_preferences(conversation_id, "owner", expected_version=0, outlet_id=first,
                                  resolve_values=lambda saved: explicit)
    current = preferences.model_preferences(conversation_id, "owner", expected_version=1, outlet_id=second,
                                           resolve_values=lambda saved: {"temperature": 1})
    assert current == {"version": 2, "selected_model_id": None, "model_parameter_preferences": {
        str(first): explicit, str(second): {"temperature": 1},
    }}
    with pytest.raises(conflict):
        preferences.model_preferences(conversation_id, "owner", expected_version=1, outlet_id=first,
                                      resolve_values=lambda saved: {})
    with pytest.raises(ConversationNotFoundError):
        preferences.model_preferences(conversation_id, "another-user", expected_version=2, outlet_id=first,
                                      resolve_values=lambda saved: pytest.fail("Must check ownership before callback"))
    assert preferences.model_preferences(conversation_id, "owner") == current
    cleared = preferences.model_preferences(conversation_id, "owner", expected_version=2, outlet_id=first,
                                           resolve_values=lambda saved: {})
    assert cleared == {"version": 3, "selected_model_id": None, "model_parameter_preferences": {str(second): {"temperature": 1}}}
    assert read(db, first) == outlet_before
    with client.get_db_session() as session:
        stored = session.get(ConversationRecord, conversation_id)
        assert stored.runtime_metadata == {} and stored.workbench_config is None
        stored.delete_flag = "Y"
    with pytest.raises(ConversationNotFoundError):
        preferences.model_preferences(conversation_id, "owner")


@pytest.mark.parametrize("ok,status", [(True, "available"), (False, "unavailable")])
def test_check_receipt_survives_actual_create_edit_and_request_change(database, monkeypatch, ok, status):
    """AC-05: signed draft evidence and config CAS share the actual commit."""
    import asyncio
    from unittest.mock import AsyncMock
    from contracts.model import ModelOutletCreateRequest, ModelOutletPatchRequest, ModelOutletValidationRequest
    from management.services.model import profiles as service

    client, db, model, _, _ = database
    captured = profile()
    monkeypatch.setattr(service, "build_outlet_draft", lambda *args, **kwargs: (captured, None))
    peer = AsyncMock(return_value={"ok": ok, "error": None})
    monkeypatch.setattr(service, "probe_model_profile", peer)
    request = ModelOutletCreateRequest(provider_info={"base_url": "https://fixture.invalid/v1"},
        request_model_id="Exact/Model", api_key=DUMMY, http_headers={"x-gateway": DUMMY})
    checked = asyncio.run(service.validate_model_outlet(ModelOutletValidationRequest(draft=request), "db-tenant-a"))
    request.check_receipt = checked["check_receipt"]
    created = service.create_model_outlet(request, "creator", "db-tenant-a")
    identifier = created["model_id"]

    def status_in_new_session():
        with client.get_db_session() as session:
            return session.execute(select(model.connect_status).where(model.model_id == identifier)).scalar_one()

    assert status_in_new_session() == status
    patch = ModelOutletPatchRequest(expected_revision=1, connection={"timeout_seconds": 27})
    checked = asyncio.run(service.validate_model_outlet(ModelOutletValidationRequest(outlet_id=identifier, patch=patch), "db-tenant-a"))
    assert status_in_new_session() == status  # Unsaved edit checks do not rewrite storage.
    patch.check_receipt = checked["check_receipt"]
    patch.display_name = "Renamed after check"
    service.update_model_outlet(identifier, patch, "editor", "db-tenant-a")
    assert read(db, identifier).connection.timeout_seconds == 27
    assert status_in_new_session() == status
    # The saved proof belongs to revision 1 and cannot mark changed revision 2 available.
    service.update_model_outlet(identifier, ModelOutletPatchRequest(expected_revision=2,
        connection={"timeout_seconds": 28}, check_receipt=checked["check_receipt"]), "editor", "db-tenant-a")
    assert status_in_new_session() == "not_detected"
    assert peer.await_count == 2  # Neither creation nor either save called the peer.


def test_explicit_profile_reselection_commits_one_identity_and_preserves_credentials(database):
    """AEU-01/04/05: actual service, compiler and SQL CAS agree on profile replacement."""
    client, db, model, conflict, _ = database
    from contracts.model import ModelOutletCreateRequest, ModelOutletPatchRequest, ModelProfileSelection
    from management.services.model import profiles as service
    from nexent.core.model_service.profiles.protocol_parameters import connectivity_request

    catalog = service.get_model_profile_catalog()
    model_key = "alibaba/qwen3.7-plus"
    selection = {"key": model_key, "revision": catalog.models[model_key].revision}
    request = ModelOutletCreateRequest(selection_mode="manual", model_profile=selection,
        catalog_revision=catalog.revision, request_model_id="qwen3.7-plus",
        provider_info={"base_url": "https://fixture.invalid/v1"}, api_key=DUMMY,
        parameter_values={"temperature": 0.7, "top_p": 1.0})
    identifier = service.create_model_outlet(request, "creator", "db-tenant-a")["model_id"]
    before = read(db, identifier)
    with client.get_db_session() as session:
        session.execute(update(model).where(model.model_id == identifier).values(connect_status="available"))
    provider = {"key": "alibaba-cn", "revision": catalog.providers["alibaba-cn"].revision}
    patch = ModelOutletPatchRequest(expected_revision=1,
        profile_selection={"catalog_revision": catalog.revision, "model_profile": selection, "provider_profile": provider},
        parameter_values={"enable_thinking": True, "reasoning_budget_tokens": 1024})
    preview = service.preview_outlet_patch(identifier, patch, "db-tenant-a")
    assert preview["selected"]["provider"] == "alibaba-cn"
    assert read(db, identifier).provider_key is None
    changed = service.update_model_outlet(identifier, patch, "editor", "db-tenant-a")
    restored = read(db, identifier)
    assert changed["model_id"] == restored.outlet_id == before.outlet_id
    assert restored.config_revision == 2 and restored.provider_key == "alibaba-cn"
    assert restored.identity.request_model_id == "qwen3.7-plus"
    fresh, _ = service.build_outlet_draft(request.model_copy(update={"provider_profile": ModelProfileSelection(**provider),
        "parameter_values": dict(restored.parameter_values)}), "db-tenant-a")
    assert connectivity_request(restored)[3] == connectivity_request(fresh)[3]
    with client.get_db_session() as session:
        row = session.execute(select(model).where(model.model_id == identifier)).scalar_one()
        assert row.api_key == DUMMY and row.connect_status == "not_detected"
        assert row.model_factory == "alibaba-cn"
    with pytest.raises(conflict):
        service.update_model_outlet(identifier, patch, "editor", "db-tenant-a")
    custom_patch = ModelOutletPatchRequest(expected_revision=2,
        profile_selection={"catalog_revision": catalog.revision, "model_profile": selection, "provider_profile": None},
        thinking_control="profile_default", thinking_mode="budget_tokens")
    custom_preview = service.preview_outlet_patch(identifier, custom_patch, "db-tenant-a")
    assert custom_preview["selected"]["provider"] is None
    service.update_model_outlet(identifier, custom_patch, "editor", "db-tenant-a")
    custom = read(db, identifier)
    assert custom.outlet_id == identifier and custom.config_revision == 3
    assert custom.provenance.provider_metadata["operator_thinking"]["preset"] == "enable_thinking"
    assert connectivity_request(custom)[3] == connectivity_request(restored)[3]
    reset = ModelOutletPatchRequest(expected_revision=3, reset_parameters=True,
        thinking_control="profile_default", thinking_mode="default")
    reset_preview = service.preview_outlet_patch(identifier, reset, "db-tenant-a")
    assert "reasoning_budget_tokens" not in reset_preview["parameter_values"]
    service.update_model_outlet(identifier, reset, "editor", "db-tenant-a")
    reset_snapshot = read(db, identifier)
    assert reset_snapshot.config_revision == 4 and reset_snapshot.outlet_id == identifier
    assert reset_snapshot.provenance.atomic_refs == custom.provenance.atomic_refs
    assert reset_snapshot.parameter_values == {"temperature": 0.7, "top_p": 1.0}
    with client.get_db_session() as session:
        assert session.execute(select(model.api_key).where(model.model_id == identifier)).scalar_one() == DUMMY
