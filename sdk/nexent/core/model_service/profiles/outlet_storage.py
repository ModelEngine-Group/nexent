# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Fixed single-row storage codec; never loads source catalogs or credentials."""

from typing import Mapping, Sequence

from nexent.core.model_service.profiles.contracts import VersionedReference
from nexent.core.model_service.profiles.outlet_capabilities import (
    CAPABILITY_COLUMN_KEYS,
    restore_outlet_capabilities,
    split_outlet_capabilities,
)
from nexent.core.model_service.profiles.outlet_parameters import (
    DEDICATED_PARAMETER_KEYS,
    PARAMETER_COLUMNS,
    split_outlet_parameters,
)
from nexent.core.model_service.profiles.outlet_rules import restore_parameter_rules, store_parameter_rules
from nexent.core.model_service.profiles.parameter_bindings import validate_parameter_bindings
from nexent.core.model_service.profiles.parameter_rules import compile_parameter_rules
from nexent.core.model_service.profiles.parameter_schema import _json_copy
from nexent.core.model_service.profiles.request_parameters import apply_extra_api_parameters
from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile


_IDENTITY = {
    "tenant_id": "tenant_id",
    "display_name": "display_name",
    "model_type": "model_type",
    "provider_id": "model_factory",
    "request_model_id": "model_name",
}
_CONNECTION = ("base_url", "ssl_verify", "timeout_seconds", "concurrency_limit")
_CONTEXT = {
    "output_reserve_tokens": "default_output_reserve_tokens",
    "tokenizer_family": "tokenizer_family",
    "capacity_source": "capacity_source",
    "capability_profile_version": "capability_profile_version",
}
_REMAINDER = {
    "parameter_rules",
    "instruction_mapping",
    "capability_details",
    "bindings",
    "provenance",
    "connection_rules",
    "explicit_null_parameters",
}


class ProfileStorageError(ValueError):
    def __init__(self):
        super().__init__("PROFILE_STORAGE_INVALID")


def _validate_available(profile, registered_references, protected_paths):
    for key, reference in profile.bindings:
        if key == "role_mapping":
            continue  # The executable local instruction registry already validates this declaration.
        if reference not in registered_references.get(key, ()):
            raise ProfileStorageError()
    compiled = compile_parameter_rules(profile.parameter_rules)
    bindings = validate_parameter_bindings(
        compiled, registered_references.get("parameter_transform", ()), protected_paths=protected_paths
    )
    apply_extra_api_parameters(
        {},
        profile.extra_api_parameters,
        parameter_paths=[binding["path"] for binding in bindings.values()],
        protected_paths=protected_paths,
    )
    return compiled


def encode_resolved_model_profile(
    profile: ResolvedModelProfile,
    *,
    registered_references: Mapping[str, Sequence[VersionedReference]],
    protected_paths: Sequence[str] = (),
) -> dict:
    """Return row-owned fields; credential values and audit fields belong to the caller."""
    try:
        profile = ResolvedModelProfile.model_validate(_json_copy(profile.model_dump(mode="json")))
        compiled = _validate_available(profile, registered_references, protected_paths)
        capabilities = split_outlet_capabilities(profile.capabilities)
        parameters = split_outlet_parameters(compiled, profile.parameter_values)
        values = profile.model_dump(mode="json")
        bindings = values["bindings"]
        protocol = bindings.pop("protocol")
        bindings["protocol_version"] = protocol["version"]
        remainder = {
            "parameter_rules": store_parameter_rules(
                compiled,
                reasoning_controls=capabilities.columns["reasoning_controls"],
                saved_values=profile.parameter_values,
            ),
            "instruction_mapping": values["instruction_mapping"],
            "capability_details": capabilities.capability_details,
            "bindings": bindings,
            "provenance": values["provenance"],
            "connection_rules": values["connection_rules"],
            "explicit_null_parameters": parameters.explicit_null_parameters,
        }
        row = {column: values["identity"][field] for field, column in _IDENTITY.items()}
        row.update({key: values["connection"][key] for key in _CONNECTION})
        row.update({column: values["context_configuration"][field] for field, column in _CONTEXT.items()})
        row.update(capabilities.columns)
        row.update(parameters.columns)
        row.update(
            profile_schema_version=profile.schema_version,
            config_revision=profile.config_revision,
            protocol_id=protocol["ref"],
            resolved_profile=remainder,
            extra_params={
                "parameter_values": parameters.parameter_values,
                "api_parameters": values["extra_api_parameters"],
            },
        )
        if profile.outlet_id is not None:
            row["model_id"] = profile.outlet_id
        return _json_copy(row)
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
        raise ProfileStorageError() from None


def decode_resolved_model_profile(
    row: Mapping[str, object],
    *,
    registered_references: Mapping[str, Sequence[VersionedReference]],
    protected_paths: Sequence[str] = (),
) -> ResolvedModelProfile:
    """Restore this row only; reject incomplete migration states and unavailable versions."""
    try:
        if type(row["model_id"]) is not int or not 0 < row["model_id"] < 2**31:
            raise ProfileStorageError()
        remainder, extra = _json_copy(row["resolved_profile"]), _json_copy(row["extra_params"])
        if not isinstance(remainder, dict) or set(remainder) != _REMAINDER:
            raise ProfileStorageError()
        if not isinstance(extra, dict) or set(extra) != {"parameter_values", "api_parameters"}:
            raise ProfileStorageError()
        capability_columns = {key: row[key] for key in CAPABILITY_COLUMN_KEYS}
        capabilities = restore_outlet_capabilities(
            columns=capability_columns, capability_details=remainder["capability_details"]
        )
        # Recover presence first; the restored declaration will validate schemas and fixed constraints.
        saved = _json_copy(extra["parameter_values"])
        nulls = remainder["explicit_null_parameters"]
        if (
            not isinstance(saved, dict)
            or DEDICATED_PARAMETER_KEYS & saved.keys()
            or not isinstance(nulls, list)
            or any(type(key) is not str for key in nulls)
            or len(nulls) != len(set(nulls))
            or not set(nulls) <= DEDICATED_PARAMETER_KEYS
        ):
            raise ProfileStorageError()
        for key in DEDICATED_PARAMETER_KEYS:
            value = row[PARAMETER_COLUMNS[key]]
            if key in nulls and value is not None:
                raise ProfileStorageError()
            if value is not None or key in nulls:
                saved[key] = value
        for declaration in remainder["parameter_rules"]:
            key = declaration.get("key")
            if key not in {"temperature", "top_p"}:
                continue
            declared_type = declaration.get("schema", {}).get("type")
            integer_only = declared_type == "integer" or (
                isinstance(declared_type, list)
                and "integer" in declared_type
                and set(declared_type) <= {"integer", "null"}
            )
            value = saved.get(key)
            if integer_only and type(value) is float and value.is_integer():
                saved[key] = int(value)
        compiled = restore_parameter_rules(
            remainder["parameter_rules"],
            reasoning_controls=capability_columns["reasoning_controls"],
            saved_values=saved,
        )
        # The common parameter codec enforces SQL column types, in addition to the restored schemas.
        split_outlet_parameters(compiled, saved)
        bindings = remainder["bindings"]
        if not isinstance(bindings, dict) or "protocol" in bindings or "protocol_version" not in bindings:
            raise ProfileStorageError()
        bindings["protocol"] = {"ref": row["protocol_id"], "version": bindings.pop("protocol_version")}
        connection = {key: row[key] for key in _CONNECTION}
        connection["credential_ref"] = {
            "kind": remainder["connection_rules"]["credential_kind"],
            "model_id": row["model_id"],
        }
        identity = {key: row[column] for key, column in _IDENTITY.items()}
        for field, atom in (("provider_key", "provider"), ("model_profile_key", "model")):
            reference = remainder["provenance"]["atomic_refs"][atom]
            identity[field] = reference["key"] if reference is not None else None
        profile = ResolvedModelProfile.model_validate(
            {
                "schema_version": row["profile_schema_version"],
                "outlet_id": row["model_id"],
                "config_revision": row["config_revision"],
                "identity": identity,
                "connection": connection,
                "connection_rules": remainder["connection_rules"],
                "context_configuration": {key: row[column] for key, column in _CONTEXT.items()},
                "capabilities": capabilities.model_dump(mode="json"),
                "instruction_mapping": remainder["instruction_mapping"],
                "parameter_rules": compiled.declarations,
                "parameter_values": saved,
                "extra_api_parameters": extra["api_parameters"],
                "bindings": bindings,
                "provenance": remainder["provenance"],
            }
        )
        _validate_available(profile, registered_references, protected_paths)
        return profile
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
        raise ProfileStorageError() from None
