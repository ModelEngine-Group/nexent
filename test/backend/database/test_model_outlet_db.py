# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Resolved outlet persistence and immutable update guards."""

import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest
from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile
from sqlalchemy.exc import SQLAlchemyError
from test.backend.database.model_outlet_helpers import (
    REGISTRY, database, load, profile, row, statement, update,
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
    database, profile, api_key, monkeypatch
):
    db, client, _ = database
    monkeypatch.setattr(db, "_connectivity_request", lambda p: p.parameter_values)
    from nexent.core.model_service.profiles.contracts import VersionedReference
    monkeypatch.setitem(REGISTRY, "auth", [*REGISTRY["auth"],
        VersionedReference(ref="bearer_token_v1", version=1), VersionedReference(ref="no_auth_v1", version=1)])
    session = MagicMock()
    read_result, write_result = MagicMock(), MagicMock()
    read_result.mappings.return_value.first.return_value = row(profile)
    write_result.scalar_one_or_none.return_value = 2
    session.execute.side_effect = [read_result, write_result]
    value = profile.model_dump(mode="json")
    value["parameter_values"]["custom"] = 0
    value["bindings"]["auth"] = {"ref": "bearer_token_v1" if api_key else "no_auth_v1", "version": 1}
    value["connection"]["credential_ref"]["kind"] = "model_record" if api_key else "none"
    value["connection_rules"]["credential_kind"] = "model_record" if api_key else "none"
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
    assert client.sessions == [session]
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




def test_registered_thinking_edits_pass_row_guard_and_arbitrary_binding_edits_do_not(database, profile):
    from copy import deepcopy
    from nexent.core.model_service.profiles.thinking_configuration import configure_thinking, configure_thinking_degree

    db, _, errors = database
    changed = configure_thinking_degree(configure_thinking(profile, "enable_thinking"), "effort")
    db._validate_update(profile, changed)
    budget = configure_thinking_degree(changed, "budget_tokens")
    db._validate_update(changed, budget)
    restored = configure_thinking_degree(budget, "default")
    db._validate_update(budget, restored)
    altered = deepcopy(changed.parameter_rules)
    next(rule for rule in altered if rule["key"] == "reasoning_effort")["api_binding"]["path"] = "/unregistered_effort"
    with pytest.raises(errors.ModelOutletValidationError):
        db._validate_update(profile, changed.model_copy(update={"parameter_rules": altered}))
    metadata = changed.provenance.model_dump()
    metadata["provider_metadata"]["operator_thinking_degree"]["rules"] = []
    metadata["provider_metadata"]["unexpected_rule_source"] = "forged"
    forged = changed.model_copy(update={"provenance": changed.provenance.model_validate(metadata)})
    with pytest.raises(errors.ModelOutletValidationError):
        db._validate_update(profile, forged)


def test_registered_sampling_upgrade_passes_guard_without_accepting_wire_edits(database, profile):
    """UI-SESSION-15: permit only the registered v1 protocol normalization."""
    from copy import deepcopy
    from nexent.core.model_service.profiles.protocol_parameters import (
        ensure_outlet_sampling_rules, openai_chat_parameter_rules,
    )

    db, _, errors = database
    data = profile.model_dump(mode="json")
    data["bindings"]["protocol"] = {"ref": "openai_chat_completions", "version": 1}
    rule = next(item for item in openai_chat_parameter_rules() if item["key"] == "temperature")
    rule.update(source={"ref": "openai_chat_protocol_parameters_v1", "version": 1}, visible=False, allowed_scopes=["outlet"])
    data["parameter_rules"].append(rule)
    old = ResolvedModelProfile.model_validate(data)
    normalized = ensure_outlet_sampling_rules(old)
    db._validate_update(old, normalized)
    forged = deepcopy(normalized.parameter_rules)
    next(item for item in forged if item["key"] == "temperature")["api_binding"]["path"] = "/unregistered"
    with pytest.raises(errors.ModelOutletValidationError):
        db._validate_update(old, normalized.model_copy(update={"parameter_rules": forged}))
