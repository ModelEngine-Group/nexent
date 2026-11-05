# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Resolved model-record operations using caller-owned transactions and revisions."""

from collections.abc import Mapping, Sequence

from contracts.errors.exceptions import ModelOutletConflictError, ModelOutletDatabaseError, ModelOutletValidationError
from nexent.core.model_service.profiles.contracts import VersionedReference
from nexent.core.model_service.profiles.outlet_storage import (
    decode_resolved_model_profile,
    encode_resolved_model_profile,
)
from nexent.core.model_service.profiles.parameter_rules import (
    compile_parameter_rules,
    validate_saved_parameter_values,
)
from nexent.core.model_service.profiles.parameter_schema import json_values_equal
from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile
from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import SQLAlchemyError

from management.db.client import get_db_session
from management.db.models import ModelRecord

_UNSET = object()


def _string(value, maximum=100, *, optional=False):
    if optional and value is None:
        return
    if (not isinstance(value, str) or len(value) > maximum or "\x00" in value
            or (not optional and not value.strip())):
        raise ModelOutletValidationError()
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise ModelOutletValidationError() from None


def _credential(value):
    _string(value, 500, optional=True)


def _check_json_strings(value):
    if isinstance(value, str):
        if "\x00" in value:
            raise ModelOutletValidationError()
    elif isinstance(value, dict):
        for key, child in value.items():
            _check_json_strings(key)
            _check_json_strings(child)
    elif isinstance(value, list):
        for child in value:
            _check_json_strings(child)


def _execute(session, statement):
    try:
        return session.execute(statement)
    except SQLAlchemyError:
        # Session owners handle rollback; never expose statement parameters to their logger.
        raise ModelOutletDatabaseError() from None


def _active_statement(model_id, tenant_id):
    if type(model_id) is not int or not 0 < model_id < 2**31:
        raise ModelOutletValidationError()
    _string(tenant_id)
    return select(ModelRecord.__table__).where(
        ModelRecord.model_id == model_id,
        ModelRecord.tenant_id == tenant_id,
        ModelRecord.delete_flag == "N",
    )


def create_resolved_model_record(
    profile: ResolvedModelProfile,
    user_id: str,
    tenant_id: str,
    *,
    registered_references: Mapping[str, Sequence[VersionedReference]],
    api_key: str | None = None,
    http_headers: dict | None = None,
    connect_status: str = "not_detected",
    db_session=None,
    protected_paths: Sequence[str] = (),
) -> int:
    """Insert one complete snapshot; return its assigned identifier without committing shared sessions."""
    _string(user_id)
    _string(tenant_id)
    _credential(api_key)
    from nexent.core.model_service.connection_headers import connection_headers

    headers = connection_headers(http_headers or {}, api_key=api_key)
    if connect_status not in {"not_detected", "detecting", "available", "unavailable"}:
        raise ModelOutletValidationError()
    if (
        not isinstance(profile, ResolvedModelProfile)
        or profile.outlet_id is not None
        or profile.config_revision != 1
        or profile.identity.tenant_id != tenant_id
    ):
        raise ModelOutletValidationError()
    values = encode_resolved_model_profile(
        profile,
        registered_references=registered_references,
        protected_paths=protected_paths,
    )
    _check_json_strings(values)
    values.update(
        api_key=api_key,
        http_headers=headers,
        connect_status=connect_status,
        created_by=user_id,
        updated_by=user_id,
        delete_flag="N",
        create_time=func.current_timestamp(),
        update_time=func.current_timestamp(),
    )
    with get_db_session(db_session) as session:
        return _execute(
            session, insert(ModelRecord).values(values).returning(ModelRecord.model_id)
        ).scalar_one()


def get_resolved_model_record(
    model_id: int,
    tenant_id: str,
    *,
    registered_references: Mapping[str, Sequence[VersionedReference]],
    db_session=None,
    protected_paths: Sequence[str] = (),
) -> ResolvedModelProfile | None:
    """Read active rows only; missing and other-tenant rows both return no result."""
    statement = _active_statement(model_id, tenant_id)
    with get_db_session(db_session) as session:
        row = _execute(session, statement).mappings().first()
        if row is None:
            return None
        return decode_resolved_model_profile(
            row,
            registered_references=registered_references,
            protected_paths=protected_paths,
        )


def _validate_update(current, proposed, *, api_key=_UNSET):
    from nexent.core.model_service.profiles.thinking_configuration import (
        configure_outlet_policy,
    )
    from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError

    old_metadata = current.provenance.provider_metadata
    new_metadata = proposed.provenance.provider_metadata

    def selected(key, field, reset):
        value = new_metadata.get(key)
        if value is None:
            return reset if key in old_metadata else None
        if not isinstance(value, dict) or field not in value:
            raise ModelOutletValidationError()
        return value[field]

    # Only the finite SDK transformations may change saved rules/capabilities.
    # Recompute from the trusted current row; never trust submitted originals.
    try:
        expected = configure_outlet_policy(current,
            thinking_control=selected("operator_thinking", "preset", "profile_default"),
            thinking_mode=selected("operator_thinking_degree", "mode", "default"),
            has_credential=bool(api_key and api_key.strip()) if api_key is not _UNSET else None)
    except (ParameterValidationError, ValueError, TypeError):
        raise ModelOutletValidationError() from None
    for key in (
        "provider_id",
        "request_model_id",
        "model_type",
        "tenant_id",
        "provider_key",
        "model_profile_key",
    ):
        if getattr(current.identity, key) != getattr(proposed.identity, key):
            raise ModelOutletValidationError()
    for key in (
        "schema_version",
        "bindings",
        "instruction_mapping",
        "connection_rules",
        "provenance",
        "parameter_rules",
    ):
        left, right = getattr(expected, key), getattr(proposed, key)
        if hasattr(left, "model_dump"):
            left, right = left.model_dump(mode="json"), right.model_dump(mode="json")
        if not json_values_equal(left, right):
            raise ModelOutletValidationError()
    old_caps, new_caps = (
        expected.capabilities.model_dump(),
        proposed.capabilities.model_dump(),
    )
    old_caps.pop("context")
    new_caps.pop("context")
    if not json_values_equal(old_caps, new_caps):
        raise ModelOutletValidationError()
    compiled = compile_parameter_rules(expected.parameter_rules)
    validate_saved_parameter_values(compiled, proposed.parameter_values)
    rules = {rule["key"]: rule for rule in compiled.declarations}
    old_rules = {rule["key"]: rule for rule in current.parameter_rules}
    for key in current.parameter_values.keys() | proposed.parameter_values.keys():
        unchanged = (
            key in current.parameter_values
            and key in proposed.parameter_values
            and json_values_equal(
                current.parameter_values[key], proposed.parameter_values[key]
            )
        )
        rule = rules.get(key) or old_rules.get(key)
        if not unchanged and (
            not rule or not rule["editable"] or "outlet" not in rule["allowed_scopes"]
        ):
            raise ModelOutletValidationError()


def _connectivity_request(profile):
    from nexent.core.model_service.profiles.protocol_parameters import connectivity_request

    return connectivity_request(profile)


def _connectivity_changed(current, proposed, row, *, api_key, http_headers):
    """Never persist or log the credential comparison material."""
    from nexent.core.model_service.connection_headers import connection_headers

    if api_key is not _UNSET and (api_key or "") != (row.get("api_key") or ""):
        return True
    if http_headers is not _UNSET and http_headers != connection_headers(row.get("http_headers") or {}):
        return True
    # Avoid rendering unchanged profiles and metadata-only edits.
    fields = ("connection", "connection_rules", "bindings", "parameter_rules", "parameter_values",
              "extra_api_parameters")
    old, new = current.model_dump(mode="json"), proposed.model_dump(mode="json")
    if (all(json_values_equal(old[field], new[field]) for field in fields)
            and json_values_equal(old["capabilities"]["sampling"], new["capabilities"]["sampling"])):
        return False
    return not json_values_equal(_connectivity_request(current), _connectivity_request(proposed))


def update_resolved_model_record(
    profile: ResolvedModelProfile,
    expected_revision: int,
    user_id: str,
    tenant_id: str,
    *,
    registered_references: Mapping[str, Sequence[VersionedReference]],
    api_key=_UNSET,
    http_headers=_UNSET,
    connect_status=None,
    db_session=None,
    protected_paths: Sequence[str] = (),
) -> int:
    """Atomically update a permitted snapshot; return the new revision or raise a safe conflict."""
    if connect_status not in (None, "available", "unavailable"):
        raise ModelOutletValidationError()
    _string(user_id)
    _string(tenant_id)
    if (
        not isinstance(profile, ResolvedModelProfile)
        or profile.outlet_id is None
        or profile.identity.tenant_id != tenant_id
        or type(expected_revision) is not int
        or not 0 < expected_revision < 2**31 - 1
        or profile.config_revision != expected_revision
    ):
        raise ModelOutletValidationError()
    if api_key is not _UNSET:
        _credential(api_key)
    if http_headers is not _UNSET:
        from nexent.core.model_service.connection_headers import connection_headers

        http_headers = connection_headers(http_headers, api_key=api_key if api_key is not _UNSET else None)
        if profile.bindings.auth.ref == "bearer_token_v1" and "authorization" in http_headers:
            raise ModelOutletValidationError("MODEL_HTTP_AUTH_CONFLICT", "/http_headers")
    values = encode_resolved_model_profile(
        profile,
        registered_references=registered_references,
        protected_paths=protected_paths,
    )
    _check_json_strings(values)
    with get_db_session(db_session) as session:
        row = _execute(session, _active_statement(profile.outlet_id, tenant_id)).mappings().first()
        if row is None:
            raise ModelOutletConflictError()
        current = decode_resolved_model_profile(row, registered_references=registered_references,
            protected_paths=protected_paths)
        if current.config_revision != expected_revision:
            raise ModelOutletConflictError()
        _validate_update(current, profile, api_key=api_key)
        for key in (
            "model_id",
            "tenant_id",
            "model_factory",
            "model_name",
            "model_type",
            "protocol_id",
            "profile_schema_version",
        ):
            values.pop(key)
        values.update(
            config_revision=expected_revision + 1,
            updated_by=user_id,
            update_time=func.current_timestamp(),
        )
        if api_key is not _UNSET:
            values["api_key"] = api_key
        if http_headers is not _UNSET:
            values["http_headers"] = http_headers
        if _connectivity_changed(current, profile, row, api_key=api_key, http_headers=http_headers):
            values["connect_status"] = "not_detected"
        if connect_status is not None:
            values["connect_status"] = connect_status
        statement = (
            update(ModelRecord)
            .where(
                ModelRecord.model_id == profile.outlet_id,
                ModelRecord.tenant_id == tenant_id,
                ModelRecord.delete_flag == "N",
                ModelRecord.config_revision == expected_revision,
            )
            .values(values)
            .returning(ModelRecord.config_revision)
        )
        revision = _execute(session, statement).scalar_one_or_none()
        if revision is None:
            raise ModelOutletConflictError()
        return revision


def has_model_outlet_credential(model_id, tenant_id, *, db_session=None):
    """Read a presence flag in SQL without returning credential material."""
    statement = _active_statement(model_id, tenant_id).with_only_columns(func.length(func.trim(ModelRecord.api_key)) > 0)
    with get_db_session(db_session) as session:
        return bool(_execute(session, statement).scalar_one_or_none())


def update_model_outlet_connectivity(model_id, tenant_id, expected_revision, status, *, db_session=None):
    """Reject stale checks without changing configuration revisions or credential values."""
    _active_statement(model_id, tenant_id)
    if (type(expected_revision) is not int or not 0 < expected_revision < 2**31
            or status not in ("available", "unavailable")):
        raise ModelOutletValidationError()
    statement = update(ModelRecord).where(
        ModelRecord.model_id == model_id, ModelRecord.tenant_id == tenant_id,
        ModelRecord.delete_flag == "N", ModelRecord.model_type == "llm",
        ModelRecord.config_revision == expected_revision,
    ).values(connect_status=status).returning(ModelRecord.model_id)
    with get_db_session(db_session) as session:
        if _execute(session, statement).scalar_one_or_none() is None:
            raise ModelOutletConflictError()


def migrate_legacy_model_records(builder, *, registered_references, batch_size=100,
                                 after_model_id=0, dry_run=False, db_session=None):
    """Migrate a locked batch in the caller's transaction; never commit shared sessions."""
    if (type(batch_size) is not int or not 1 <= batch_size <= 1000
            or type(after_model_id) is not int or not 0 <= after_model_id < 2**31):
        raise ModelOutletValidationError()
    statement = select(ModelRecord.__table__).where(
        ModelRecord.model_type.in_(("llm", "chat")), ModelRecord.profile_schema_version.is_(None),
        ModelRecord.model_id > after_model_id,
    ).order_by(ModelRecord.model_id).limit(batch_size)
    if not dry_run:
        statement = statement.with_for_update()
    report = []
    with get_db_session(db_session) as session:
        rows = _execute(session, statement).mappings().all()
        for row in rows:
            result = {"model_id": row["model_id"], "tenant_id": row["tenant_id"]}
            try:
                profile = builder(row)
                if (profile.outlet_id != row["model_id"] or profile.identity.tenant_id != row["tenant_id"]
                        or profile.identity.model_type != "llm"):
                    raise ModelOutletValidationError(category="LEGACY_MIGRATION_IDENTITY_INVALID")
                values = encode_resolved_model_profile(profile, registered_references=registered_references,
                    protected_paths=("/api_key", "/authorization", "/headers", "/credentials", "/base_url"))
                _check_json_strings(values)
                values.pop("model_id")
                values.pop("tenant_id")
                values.update(model_repo=None, max_tokens=None)
                result.update(status="ready" if dry_run else "migrated", category=None)
            except ModelOutletValidationError as error:
                result.update(status="failed", category=error.category)
                values = {"resolved_profile": {"migration_error": {"category": error.category,
                          "field": error.path}}}
            if not dry_run:
                _execute(session, update(ModelRecord).where(
                    ModelRecord.model_id == row["model_id"], ModelRecord.tenant_id == row["tenant_id"],
                    ModelRecord.profile_schema_version.is_(None),
                ).values(values))
            report.append(result)
    return report


def confirm_model_outlet_migration(model_id, tenant_id, user_id, expected_revision, *,
                                   registered_references, db_session=None):
    """Confirm exactly one configuration revision without changing model parameters."""
    from datetime import datetime, timezone

    _string(user_id)
    if type(expected_revision) is not int or not 0 < expected_revision < 2**31:
        raise ModelOutletValidationError()
    with get_db_session(db_session) as session:
        row = _execute(session, _active_statement(model_id, tenant_id).with_for_update()).mappings().first()
        if row is None:
            return None
        profile = decode_resolved_model_profile(row, registered_references=registered_references)
        if profile.config_revision != expected_revision:
            raise ModelOutletConflictError()
        data = profile.model_dump(mode="json")
        migration = data["provenance"]["provider_metadata"].get("migration")
        if profile.identity.model_type != "llm" or not isinstance(migration, dict):
            raise ModelOutletValidationError(category="MIGRATION_NOT_APPLICABLE")
        migration.update(reviewed_revision=expected_revision, reviewed_by=user_id,
                         reviewed_at=datetime.now(timezone.utc).isoformat())
        reviewed = ResolvedModelProfile.model_validate(data)
        remainder = encode_resolved_model_profile(reviewed, registered_references=registered_references)["resolved_profile"]
        statement = update(ModelRecord).where(ModelRecord.model_id == model_id, ModelRecord.tenant_id == tenant_id,
            ModelRecord.delete_flag == "N", ModelRecord.config_revision == expected_revision).values(
                resolved_profile=remainder, updated_by=user_id, update_time=func.current_timestamp()
            ).returning(ModelRecord.model_id)
        if _execute(session, statement).scalar_one_or_none() is None:
            raise ModelOutletConflictError()
        return {"model_id": model_id, "config_revision": expected_revision, "migration_review_required": False}


def repair_legacy_model_record(model_id, tenant_id, user_id, expected_revision, builder, *,
                               registered_references, db_session=None):
    """Repair a failed legacy migration under the same row lock without changing its ID."""
    _string(user_id)
    with get_db_session(db_session) as session:
        row = _execute(session, _active_statement(model_id, tenant_id).with_for_update()).mappings().first()
        if row is None:
            raise LookupError("MODEL_OUTLET_NOT_FOUND")
        if (row["profile_schema_version"] is not None or type(expected_revision) is not int
                or row["config_revision"] != expected_revision):
            raise ModelOutletConflictError()
        if row["model_type"] not in {"llm", "chat"}:
            raise ModelOutletValidationError()
        profile, api_key = builder(dict(row))
        if profile.outlet_id != model_id or profile.identity.tenant_id != tenant_id:
            raise ModelOutletValidationError()
        _credential(api_key)
        values = encode_resolved_model_profile(profile, registered_references=registered_references,
            protected_paths=("/api_key", "/authorization", "/headers", "/credentials", "/base_url"))
        _check_json_strings(values)
        for field in ("model_id", "tenant_id"):
            values.pop(field)
        values.update(model_repo=None, max_tokens=None, api_key=api_key, config_revision=expected_revision + 1,
                      updated_by=user_id, update_time=func.current_timestamp())
        _execute(session, update(ModelRecord).where(ModelRecord.model_id == model_id,
            ModelRecord.tenant_id == tenant_id, ModelRecord.profile_schema_version.is_(None),
            ModelRecord.config_revision == expected_revision).values(values))
        return {"model_id": model_id, "config_revision": expected_revision + 1}
