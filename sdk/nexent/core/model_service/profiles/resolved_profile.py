# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Strict complete outlet snapshot, with safe credential references only."""

import json
from typing import Annotated, Literal, Self

from pydantic import Field, JsonValue, StringConstraints, field_validator, model_validator

from nexent.core.model_service.profiles.contracts import (
    AtomicProfileReference,
    InstructionMappingDefinition,
    NonBlankString,
    ProfileCapabilities,
    ProfileContract,
    VersionedReference,
)
from nexent.core.model_service.profiles.instruction_mapping import validate_instruction_mapping
from nexent.core.model_service.profiles.parameter_bindings import validate_parameter_bindings
from nexent.core.model_service.profiles.parameter_rules import compile_parameter_rules, validate_saved_parameter_values
from nexent.core.model_service.profiles.parameter_schema import _json_copy, json_values_equal
from nexent.core.model_service.profiles.request_parameters import apply_extra_api_parameters


PositiveInt4 = Annotated[int, Field(gt=0, lt=2**31)]
Name = Annotated[str, StringConstraints(min_length=1, max_length=100, pattern=r"\S")]


class OutletIdentity(ProfileContract):
    tenant_id: Name
    display_name: Name
    model_type: Name
    provider_id: Name
    request_model_id: Name
    provider_key: NonBlankString | None
    model_profile_key: NonBlankString | None


class CredentialReference(ProfileContract):
    kind: Literal["model_record", "none"]
    model_id: PositiveInt4 | None


class OutletConnection(ProfileContract):
    base_url: Annotated[str, StringConstraints(min_length=1, max_length=500, pattern=r"\S")]
    ssl_verify: bool
    timeout_seconds: PositiveInt4
    concurrency_limit: PositiveInt4 | None
    credential_ref: CredentialReference


class ConnectionRules(ProfileContract):
    credential_kind: Literal["model_record", "none"]
    relative_path: NonBlankString
    method: Literal["POST", "GET"]
    headers: dict[NonBlankString, str]


class OutletBindings(ProfileContract):
    protocol: VersionedReference
    auth: VersionedReference
    adapter: VersionedReference
    code_converter: VersionedReference
    native_converter: VersionedReference
    role_mapping: VersionedReference


class AtomicReferences(ProfileContract):
    model: AtomicProfileReference | None
    provider: AtomicProfileReference | None
    provider_model: AtomicProfileReference | None


class InterpretationVersions(ProfileContract):
    source_parser: VersionedReference | None
    source_mapping: VersionedReference | None
    supplement_schema: VersionedReference | None
    composer: VersionedReference | None


class OverrideRecord(ProfileContract):
    path: NonBlankString
    source: NonBlankString
    original_value: JsonValue = Field(repr=False)
    reason: NonBlankString
    evidence: NonBlankString | list[NonBlankString]


class FieldSourceRecord(ProfileContract):
    target_path: NonBlankString
    source_path: NonBlankString
    atom_kind: Literal["model", "provider", "provider_model"]
    rule_id: NonBlankString
    rule_version: PositiveInt4


class OutletProvenance(ProfileContract):
    atomic_refs: AtomicReferences
    interpretation_versions: InterpretationVersions
    overrides: list[OverrideRecord]
    field_sources: list[FieldSourceRecord]
    provider_metadata: dict[str, JsonValue] = Field(repr=False)


class ContextConfiguration(ProfileContract):
    output_reserve_tokens: PositiveInt4 | None
    tokenizer_family: Name | None
    capacity_source: Name | None
    capability_profile_version: Name | None


class ResolvedModelProfile(ProfileContract):
    """A configuration snapshot; declarations do not prove registry availability."""

    schema_version: Literal[1]
    outlet_id: PositiveInt4 | None
    config_revision: PositiveInt4
    identity: OutletIdentity
    connection: OutletConnection
    connection_rules: ConnectionRules
    context_configuration: ContextConfiguration
    capabilities: ProfileCapabilities
    instruction_mapping: InstructionMappingDefinition
    parameter_rules: list[dict] = Field(repr=False)
    parameter_values: dict[str, JsonValue] = Field(repr=False)
    extra_api_parameters: list[dict] = Field(repr=False)
    bindings: OutletBindings
    provenance: OutletProvenance

    @field_validator("schema_version", mode="before")
    @classmethod
    def validate_schema_version(cls, value):
        if type(value) is not int:
            raise ValueError("Schema version must be a strict integer")
        return value

    @property
    def provider_key(self) -> str | None:
        reference = self.provenance.atomic_refs.provider
        return reference.key if reference else None

    @property
    def model_profile_key(self) -> str | None:
        reference = self.provenance.atomic_refs.model
        return reference.key if reference else None

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        credential = self.connection.credential_ref
        if credential.model_id != self.outlet_id or credential.kind != self.connection_rules.credential_kind:
            raise ValueError("Credential reference does not belong to this outlet")
        if (
            self.identity.provider_key != self.provider_key
            or self.identity.model_profile_key != self.model_profile_key
        ):
            raise ValueError("Atomic identity does not match its provenance")
        if len(self.bindings.protocol.ref) > 30:
            raise ValueError("Protocol reference exceeds its database column")
        if validate_instruction_mapping(self.instruction_mapping) != self.bindings.role_mapping:
            raise ValueError("Instruction mapping reference does not match its definition")
        compiled = compile_parameter_rules(self.parameter_rules)
        validate_saved_parameter_values(compiled, self.parameter_values)
        declarations = {rule["key"]: rule for rule in compiled.declarations}
        for control in self.capabilities.reasoning.controls or []:
            key = control.parameter_key
            if key not in declarations:
                raise ValueError("Reasoning control has no parameter declaration")
            if key not in self.parameter_values:
                continue
            value = self.parameter_values[key]
            if control.mode in {"toggle", "effort"}:
                valid = any(json_values_equal(value, candidate) for candidate in control.values)
            else:
                valid = type(value) is int and (
                    value in control.special_values
                    or (
                        (control.min is None or value >= control.min) and (control.max is None or value <= control.max)
                    )
                )
            if not valid:
                raise ValueError("Saved value contradicts its reasoning control domain")
        transforms = []
        for rule in self.parameter_rules:
            binding = rule.get("api_binding")
            if binding is not None:
                if not isinstance(binding, dict) or set(binding) != {"path", "transform_ref", "transform_version"}:
                    raise ValueError("Invalid parameter binding declaration")
                transforms.append(
                    VersionedReference.model_validate(
                        {"ref": binding["transform_ref"], "version": binding["transform_version"]}
                    )
                )
        # This checks declaration syntax only; storage also requires a trusted availability snapshot.
        bound = validate_parameter_bindings(compiled, transforms)
        parameter_paths = [binding["path"] for binding in bound.values()]
        apply_extra_api_parameters({}, self.extra_api_parameters, parameter_paths=parameter_paths)
        encoded = json.dumps(_json_copy(self.model_dump(mode="json")), ensure_ascii=False, allow_nan=False).encode(
            "utf-8"
        )
        if len(encoded) > 1024 * 1024:
            raise ValueError("Profile exceeds the 1 MiB configuration limit")
        return self
