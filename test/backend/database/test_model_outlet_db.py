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
    # Use actual metadata/exception definitions without importing configured DB clients.
    for package, directory in (
        ("_outlet_unit_consts", "backend/consts"),
        ("_outlet_unit_db", "backend/database"),
    ):
        module = ModuleType(package)
        module.__path__ = [str(ROOT / directory)]
        monkeypatch.setitem(sys.modules, package, module)
    exceptions = load(
        "_outlet_unit_consts.exceptions", "backend/consts/exceptions.py", monkeypatch
    )
    monkeypatch.setitem(sys.modules, "consts.exceptions", exceptions)
    client = ModuleType("_outlet_unit_db.client")
    client.sessions = []

    @contextmanager
    def get_session(session=None):
        client.sessions.append(session)
        yield session

    client.get_db_session = get_session
    monkeypatch.setitem(sys.modules, client.__name__, client)
    database = load(
        "_outlet_unit_db.model_outlet_db",
        "backend/database/model_outlet_db.py",
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


def test_creation_returns_id_and_keeps_shared_session_owned_by_caller(
    database, profile
):
    db, client, _ = database
    value = profile.model_dump(mode="json")
    value["outlet_id"] = value["connection"]["credential_ref"]["model_id"] = None
    session = MagicMock()
    session.execute.return_value.scalar_one.return_value = 23
    assert (
        db.create_resolved_model_record(
            ResolvedModelProfile.model_validate(value),
            "actor",
            "tenant-one",
            registered_references=REGISTRY,
            api_key="dummy-private",
            db_session=session,
        )
        == 23
    )
    compiled = statement(session)
    assert compiled.params["api_key"] == "dummy-private"
    assert "dummy-private" not in repr(compiled.params["resolved_profile"])
    assert compiled.params["delete_flag"] == "N"
    assert compiled.params["created_by"] == compiled.params["updated_by"] == "actor"
    assert client.sessions == [session]
    session.commit.assert_not_called()
    session.rollback.assert_not_called()
    session.close.assert_not_called()


def test_reads_use_tenant_and_active_predicates(database, profile):
    db, _, _ = database
    session = MagicMock()
    session.execute.return_value.mappings.return_value.first.return_value = row(profile)
    result = db.get_resolved_model_record(
        12, "tenant-one", registered_references=REGISTRY, db_session=session
    )
    assert result.model_dump() == profile.model_dump()
    compiled = statement(session)
    assert "model_record_t.model_id =" in str(compiled)
    assert "model_record_t.tenant_id =" in str(compiled)
    assert "model_record_t.delete_flag =" in str(compiled)
    assert {12, "tenant-one", "N"} <= set(compiled.params.values())


def test_missing_rows_do_not_construct_a_snapshot(database):
    db, _, _ = database
    session = MagicMock()
    session.execute.return_value.mappings.return_value.first.return_value = None
    assert (
        db.get_resolved_model_record(
            12, "tenant-one", registered_references=REGISTRY, db_session=session
        )
        is None
    )


@pytest.mark.parametrize("api_key", [None, "updated-dummy", ""])
def test_update_is_one_atomic_cas_write_with_optional_credential(
    database, profile, api_key
):
    db, client, _ = database
    session = MagicMock()
    read_result, write_result = MagicMock(), MagicMock()
    read_result.mappings.return_value.first.return_value = row(profile)
    write_result.scalar_one_or_none.return_value = 2
    session.execute.side_effect = [read_result, write_result]
    value = profile.model_dump(mode="json")
    value["parameter_values"]["custom"] = 0
    proposed = ResolvedModelProfile.model_validate(value)
    assert update(db, proposed, session, api_key=api_key) == 2
    compiled = statement(session, 1)
    assert "model_record_t.config_revision =" in str(compiled)
    assert "model_record_t.tenant_id =" in str(compiled)
    assert "model_record_t.delete_flag =" in str(compiled)
    assert compiled.params["config_revision"] == 2
    assert compiled.params["config_revision_1"] == 1
    assert compiled.params["model_id_1"] == 12
    assert compiled.params["tenant_id_1"] == "tenant-one"
    assert compiled.params["delete_flag_1"] == "N"
    assert compiled.params["api_key"] == api_key
    assert compiled.params["extra_params"]["parameter_values"] == {"custom": 0}
    assert client.sessions == [session, session]
    session.commit.assert_not_called()
    session.close.assert_not_called()


def test_omitted_credential_is_not_cleared(database, profile):
    db, _, _ = database
    session = MagicMock()
    read_result, write_result = MagicMock(), MagicMock()
    read_result.mappings.return_value.first.return_value = row(profile)
    write_result.scalar_one_or_none.return_value = 2
    session.execute.side_effect = [read_result, write_result]
    update(db, profile, session)
    assert "api_key" not in statement(session, 1).params


@pytest.mark.parametrize("current", [None, "stale"])
def test_missing_or_stale_update_has_no_write(database, profile, current):
    db, _, errors = database
    session = MagicMock()
    saved = row(profile) if current else None
    if saved:
        saved["config_revision"] = 2
    session.execute.return_value.mappings.return_value.first.return_value = saved
    with pytest.raises(errors.ModelOutletConflictError):
        update(db, profile, session)
    assert session.execute.call_count == 1


def test_cas_race_after_read_raises_conflict(database, profile):
    db, _, errors = database
    session = MagicMock()
    read_result, write_result = MagicMock(), MagicMock()
    read_result.mappings.return_value.first.return_value = row(profile)
    write_result.scalar_one_or_none.return_value = None
    session.execute.side_effect = [read_result, write_result]
    with pytest.raises(errors.ModelOutletConflictError):
        update(db, profile, session)


@pytest.mark.parametrize("bad", ["x" * 501, 0, "bad\x00key", "bad\ud800"])
def test_invalid_credentials_are_rejected_before_any_query(database, profile, bad):
    db, client, errors = database
    session = MagicMock()
    with pytest.raises(errors.ModelOutletValidationError):
        update(db, profile, session, api_key=bad)
    assert client.sessions == []
    session.execute.assert_not_called()


def test_sql_errors_are_sanitized_without_private_parameters(database):
    db, _, errors = database
    session = MagicMock()
    session.execute.side_effect = SQLAlchemyError("dummy-credential-private")
    with pytest.raises(errors.ModelOutletDatabaseError) as captured:
        db.get_resolved_model_record(
            12, "tenant-one", registered_references=REGISTRY, db_session=session
        )
    assert "dummy-credential-private" not in str(captured.value)
    assert captured.value.__suppress_context__ is True


def test_immutable_definition_change_is_rejected(database, profile):
    db, _, errors = database
    session = MagicMock()
    session.execute.return_value.mappings.return_value.first.return_value = row(profile)
    value = profile.model_dump(mode="json")
    value["identity"]["request_model_id"] = "another-model"
    with pytest.raises(errors.ModelOutletValidationError):
        update(db, ResolvedModelProfile.model_validate(value), session)
    assert session.execute.call_count == 1


def test_readonly_parameter_deletion_is_rejected(database, profile):
    db, _, errors = database
    value = profile.model_dump(mode="json")
    value["parameter_rules"][0]["editable"] = False
    current = ResolvedModelProfile.model_validate(value)
    session = MagicMock()
    session.execute.return_value.mappings.return_value.first.return_value = row(current)
    value["parameter_values"] = {}
    with pytest.raises(errors.ModelOutletValidationError):
        update(db, ResolvedModelProfile.model_validate(value), session)
    assert session.execute.call_count == 1


@pytest.mark.parametrize("actor", [None, "", "x" * 101, "bad\x00actor", "bad\ud800"])
def test_invalid_actors_never_enter_database_session(database, profile, actor):
    db, client, errors = database
    with pytest.raises(errors.ModelOutletValidationError):
        db.update_resolved_model_record(
            profile,
            1,
            actor,
            "tenant-one",
            registered_references=REGISTRY,
            db_session=MagicMock(),
        )
    assert client.sessions == []


@pytest.mark.parametrize("model_id", [None, True, 0, 2**31])
def test_invalid_model_ids_are_rejected_before_read(database, model_id):
    db, client, errors = database
    with pytest.raises(errors.ModelOutletValidationError):
        db.get_resolved_model_record(
            model_id,
            "tenant-one",
            registered_references=REGISTRY,
            db_session=MagicMock(),
        )
    assert client.sessions == []


@pytest.mark.parametrize("revision", [True, 0, 2, 2**31 - 1])
def test_invalid_revision_does_not_query(database, profile, revision):
    db, client, errors = database
    with pytest.raises(errors.ModelOutletValidationError):
        db.update_resolved_model_record(
            profile,
            revision,
            "actor",
            "tenant-one",
            registered_references=REGISTRY,
            db_session=MagicMock(),
        )
    assert client.sessions == []


def test_create_cannot_reuse_existing_identifier(database, profile):
    db, client, errors = database
    with pytest.raises(errors.ModelOutletValidationError):
        db.create_resolved_model_record(
            profile,
            "actor",
            "tenant-one",
            registered_references=REGISTRY,
            db_session=MagicMock(),
        )
    assert client.sessions == []


def test_snapshot_tenant_mismatch_is_not_silently_reassigned(database, profile):
    db, client, errors = database
    with pytest.raises(errors.ModelOutletValidationError):
        db.update_resolved_model_record(
            profile,
            1,
            "actor",
            "tenant-two",
            registered_references=REGISTRY,
            db_session=MagicMock(),
        )
    assert client.sessions == []


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d["parameter_rules"][0].update(source={"changed": True}),
        lambda d: d["connection_rules"]["headers"].update(Accept="new"),
        lambda d: d["capabilities"].update(structured_output={"status": "supported"}),
    ],
)
def test_saved_definitions_cannot_be_replaced_during_update(database, profile, change):
    db, _, errors = database
    value = profile.model_dump(mode="json")
    change(value)
    session = MagicMock()
    session.execute.return_value.mappings.return_value.first.return_value = row(profile)
    with pytest.raises(errors.ModelOutletValidationError):
        update(db, ResolvedModelProfile.model_validate(value), session)
    assert session.execute.call_count == 1


def test_nul_inside_json_is_rejected_before_postgresql_can_log_query_parameters(
    database, profile
):
    db, client, errors = database
    value = profile.model_dump(mode="json")
    value["parameter_values"]["custom"] = {"nested": ["private\x00value"]}
    with pytest.raises(errors.ModelOutletValidationError) as captured:
        update(db, ResolvedModelProfile.model_validate(value), MagicMock())
    assert "private" not in str(captured.value)
    assert client.sessions == []


@pytest.mark.parametrize(
    "name",
    [
        "create_resolved_model_record",
        "get_resolved_model_record",
        "update_resolved_model_record",
    ],
)
def test_model_management_entry_delegates_without_legacy_filter(
    database, monkeypatch, name
):
    db, client, _ = database
    constants = ModuleType("consts.const")
    constants.DEFAULT_EXPECTED_CHUNK_SIZE = 1024
    constants.DEFAULT_MAXIMUM_CHUNK_SIZE = 1536
    monkeypatch.setitem(sys.modules, "consts.const", constants)
    model_constants = ModuleType("consts.model")
    model_constants.filter_extra_params = MagicMock(
        side_effect=AssertionError("New profile must not enter legacy filter")
    )
    monkeypatch.setitem(sys.modules, "consts.model", model_constants)
    client.as_dict, client.db_client = MagicMock(), MagicMock()
    delegated = MagicMock(return_value=42)
    monkeypatch.setattr(db, name, delegated)
    facade = load(
        "_outlet_unit_db.model_management_db",
        "backend/database/model_management_db.py",
        monkeypatch,
    )
    assert getattr(facade, name)("profile-or-id", tenant_id="tenant-one") == 42
    delegated.assert_called_once_with("profile-or-id", tenant_id="tenant-one")
    model_constants.filter_extra_params.assert_not_called()
