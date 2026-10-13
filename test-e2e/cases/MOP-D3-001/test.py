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
REF = VersionedReference(ref="db_boundary_v1", version=1)
REGISTRY = {key: [REF] for key in (
    "protocol", "auth", "adapter", "code_converter", "native_converter", "parameter_transform"
)}
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
    return ResolvedModelProfile.model_validate({
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
        "capabilities": {}, "instruction_mapping": resolve_instruction_mapping(role).model_dump(mode="json"),
        "parameter_rules": [parameter("temperature", {"type": "integer"}),
                            parameter("custom_switch", {"type": "boolean"}),
                            parameter("custom_null", {"type": "null"})],
        "parameter_values": {"temperature": 0, "custom_switch": False, "custom_null": None},
        "extra_api_parameters": [{"path": "/vendor/option", "value": False}],
        "bindings": {**{key: REF.model_dump() for key in REGISTRY if key != "parameter_transform"},
                     "role_mapping": role.model_dump()},
        "provenance": {"atomic_refs": {"model": None, "provider": None, "provider_model": None},
                       "interpretation_versions": {"source_parser": None, "source_mapping": None,
                                                   "supplement_schema": None, "composer": None},
                       "overrides": [], "field_sources": [], "provider_metadata": {}},
    })


@pytest.fixture
def database(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "backend"))
    apply_product_postgres_env()
    from consts.exceptions import ModelOutletConflictError, ModelOutletDatabaseError
    from database import client, model_outlet_db
    from database.db_models import ModelRecord

    with isolated_product_database():
        yield client, model_outlet_db, ModelRecord, ModelOutletConflictError, ModelOutletDatabaseError


def create(db, session=None):
    return db.create_resolved_model_record(profile(), "creator", "db-tenant-a",
                                          registered_references=REGISTRY, api_key=DUMMY, db_session=session)


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
    assert restored.parameter_values == {"temperature": 0, "custom_switch": False, "custom_null": None}
    assert type(restored.parameter_values["temperature"]) is int
    assert restored.connection.credential_ref.model_id == identifier
    with client.get_db_session() as session:
        row = session.execute(select(model.__table__).where(model.model_id == identifier)).mappings().one()
        assert row["api_key"] == DUMMY
        assert DUMMY not in json.dumps(row["resolved_profile"])
        assert DUMMY not in json.dumps(row["extra_params"])
        assert row["temperature"] == 0
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
