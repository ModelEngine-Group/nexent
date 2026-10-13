"""Resolved model-record operations using caller-owned transactions and revisions."""

from collections.abc import Mapping, Sequence

from consts.exceptions import (
    ModelOutletConflictError,
    ModelOutletDatabaseError,
    ModelOutletValidationError,
)
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

from .client import get_db_session
from .db_models import ModelRecord

_UNSET = object()


def _string(value, maximum=100):
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or "\x00" in value
    ):
        raise ModelOutletValidationError()
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise ModelOutletValidationError() from None


def _credential(value):
    if value is None:
        return
    if not isinstance(value, str) or len(value) > 500 or "\x00" in value:
        raise ModelOutletValidationError()
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise ModelOutletValidationError() from None


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
    db_session=None,
    protected_paths: Sequence[str] = (),
) -> int:
    """Insert one complete snapshot; return its assigned identifier without committing shared sessions."""
    _string(user_id)
    _string(tenant_id)
    _credential(api_key)
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


def _validate_update(current, proposed):
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
        left, right = getattr(current, key), getattr(proposed, key)
        if hasattr(left, "model_dump"):
            left, right = left.model_dump(mode="json"), right.model_dump(mode="json")
        if not json_values_equal(left, right):
            raise ModelOutletValidationError()
    old_caps, new_caps = (
        current.capabilities.model_dump(),
        proposed.capabilities.model_dump(),
    )
    old_caps.pop("context")
    new_caps.pop("context")
    if not json_values_equal(old_caps, new_caps):
        raise ModelOutletValidationError()
    compiled = compile_parameter_rules(current.parameter_rules)
    validate_saved_parameter_values(compiled, proposed.parameter_values)
    rules = {rule["key"]: rule for rule in compiled.declarations}
    for key in current.parameter_values.keys() | proposed.parameter_values.keys():
        unchanged = (
            key in current.parameter_values
            and key in proposed.parameter_values
            and json_values_equal(
                current.parameter_values[key], proposed.parameter_values[key]
            )
        )
        if not unchanged and (
            not rules[key]["editable"] or "outlet" not in rules[key]["allowed_scopes"]
        ):
            raise ModelOutletValidationError()


def update_resolved_model_record(
    profile: ResolvedModelProfile,
    expected_revision: int,
    user_id: str,
    tenant_id: str,
    *,
    registered_references: Mapping[str, Sequence[VersionedReference]],
    api_key=_UNSET,
    db_session=None,
    protected_paths: Sequence[str] = (),
) -> int:
    """Atomically update a permitted snapshot; return the new revision or raise a safe conflict."""
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
    values = encode_resolved_model_profile(
        profile,
        registered_references=registered_references,
        protected_paths=protected_paths,
    )
    _check_json_strings(values)
    with get_db_session(db_session) as session:
        current = get_resolved_model_record(
            profile.outlet_id,
            tenant_id,
            registered_references=registered_references,
            db_session=session,
            protected_paths=protected_paths,
        )
        if current is None or current.config_revision != expected_revision:
            raise ModelOutletConflictError()
        _validate_update(current, profile)
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
