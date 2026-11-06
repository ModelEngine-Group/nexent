# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Immutable atomic views and exact provider-model policy composition."""

import json
from dataclasses import dataclass
from typing import Mapping, Sequence

from pydantic import ValidationError

from nexent.core.model_service.profiles._models_dev.reader import _freeze
from nexent.core.model_service.profiles.contracts import ProfileCapabilities, VersionedReference
from nexent.core.model_service.profiles.instruction_mapping import resolve_instruction_mapping
from nexent.core.model_service.profiles.parameter_bindings import validate_parameter_bindings
from nexent.core.model_service.profiles.parameter_rules import (
    CompiledParameterRules,
    apply_parameter_values,
    compile_parameter_rules,
)
from nexent.core.model_service.profiles.parameter_schema import (
    ParameterValidationError,
    _json_copy,
    compile_parameter_schema,
    json_values_equal,
    validate_parameter_value,
)
from nexent.core.model_service.profiles.resolver import SourceCatalog, SourceCatalogEntry, _revision
from nexent.core.model_service.profiles.supplements import SupplementCatalog


COMPOSER_REF = "profile_policy_composer_v6"
_CAPABILITY_PATHS = frozenset(
    f"/{group}/{field}"
    for group, fields in {
        "context": ("combined_window", "input_limit", "output_limit"),
        "reasoning": ("status", "controls", "response_paths"),
        "tools": ("status", "schema_constraints", "result_format"),
        "sampling": ("temperature", "top_p"),
        "structured_output": ("status",),
        "modalities": ("input", "output"),
        "response": ("supported_finish_reasons", "stream_format"),
        "usage": ("semantics_id", "input_includes_cached", "output_includes_reasoning"),
    }.items()
    for field in fields
)


class ProfileCompositionError(ValueError):
    """A conflict diagnostic never includes parameter or credential values."""

    def __init__(self, category: str, path: str = ""):
        self.category, self.path = category, path
        super().__init__(f"{category}: {path}")


@dataclass(frozen=True)
class AtomicProfileDefinition:
    kind: str
    key: str
    source: SourceCatalogEntry
    capabilities: Mapping[str, object]
    parameters: tuple[Mapping[str, object], ...]
    bindings: Mapping[str, object]
    instruction_reference: VersionedReference | None
    model_profile_key: str | None
    aliases: tuple[str, ...]
    endpoint_hints: tuple[str, ...]
    overrides: tuple[Mapping[str, object], ...]
    revision: str


@dataclass(frozen=True)
class ProfileCatalog:
    revision: str
    models: Mapping[str, AtomicProfileDefinition]
    providers: Mapping[str, AtomicProfileDefinition]
    provider_models: Mapping[str, AtomicProfileDefinition]


@dataclass(frozen=True)
class ProviderModelPolicy:
    """A validated policy draft, not a saved outlet or a transport implementation."""

    request_model_id: str
    model_profile_key: str | None
    provider_key: str | None
    capabilities: Mapping[str, object]
    instruction_mapping: Mapping[str, object]
    bindings: Mapping[str, object]
    parameter_rules: CompiledParameterRules
    parameter_bindings: Mapping[str, Mapping[str, object]]
    parameter_values: Mapping[str, object]
    overrides: tuple[Mapping[str, object], ...]
    catalog_revision: str
    revision: str


def _check_profile_size(document: Mapping) -> None:
    try:
        encoded = json.dumps(_json_copy(document), ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode(
            "utf-8"
        )
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise ProfileCompositionError("PROFILE_JSON_INVALID") from None
    if len(encoded) > 1024 * 1024:
        raise ProfileCompositionError("PROFILE_SIZE_LIMIT")


def _capabilities(value: Mapping) -> dict:
    try:
        return ProfileCapabilities.model_validate(_json_copy(value)).model_dump(mode="json")
    except ValidationError:
        raise ProfileCompositionError("PROFILE_CAPABILITIES_INVALID") from None


def _apply_override(capabilities: dict, override: Mapping, source: str) -> dict:
    path = override["path"]
    if path not in _CAPABILITY_PATHS:
        raise ProfileCompositionError("PROFILE_OVERRIDE_PATH_INVALID", path)
    group, key = path[1:].split("/")
    previous = capabilities[group][key]
    capabilities[group][key] = _json_copy(override["value"])
    return {
        "path": path,
        "source": source,
        "original_value": previous,
        "reason": override["reason"],
        "evidence": override["evidence"],
    }


def _merge_capability_facts(target: dict, facts: Mapping) -> None:
    """Overlay authored source facts only; absent fields preserve the base."""
    for key, value in facts.items():
        if isinstance(value, Mapping) and isinstance(target.get(key), dict):
            _merge_capability_facts(target[key], value)
        else:
            target[key] = _json_copy(value)


def _compose_declarations(base: Mapping, *layers: Mapping) -> dict:
    """Overlay complete declarations in explicit model/provider/combination order."""
    result = _json_copy(base)
    for declarations in layers:
        result.update(_json_copy(declarations))
    return result


def build_profile_catalog(sources: SourceCatalog, supplements: SupplementCatalog) -> ProfileCatalog:
    """Publish all atomic views together; unsupported bindings are checked at selection."""
    if supplements.source_revision != sources.revision:
        raise ProfileCompositionError("PROFILE_SOURCE_REVISION_MISMATCH")
    rules = {(entry.rule["target_kind"], entry.rule["target_key"]): entry for entry in supplements.entries.values()}
    collections = {"model": {}, "provider": {}, "provider_model": {}}
    for kind, entries in (
        ("model", sources.models),
        ("provider", sources.providers),
        ("provider_model", sources.provider_models),
    ):
        for key, source in entries.items():
            supplement = rules.get((kind, key))
            rule = supplement.rule if supplement else {}
            capabilities = _capabilities(source.capabilities)
            overrides, seen = [], {}
            for override in rule.get("capability_overrides", ()):
                path = override["path"]
                if path in seen:
                    if not json_values_equal(seen[path], override["value"]):
                        raise ProfileCompositionError("PROFILE_CONFLICT", path)
                    continue
                seen[path] = override["value"]
                overrides.append(_apply_override(capabilities, override, supplement.file_path))
            capabilities = _capabilities(capabilities)
            reference = rule.get("instruction_mapping")
            reference = VersionedReference.model_validate(_json_copy(reference)) if reference else None
            parts = {
                "composer": COMPOSER_REF,
                "source": source.profile_revision,
                "supplement_schema": supplements.schema_ref,
            }
            if supplement:
                parts[supplement.file_path] = supplement.content_sha256
            _check_profile_size(
                {
                    "identity": source.identity,
                    "capabilities": capabilities,
                    "reference_metadata": source.reference_metadata,
                    "connection_suggestions": source.connection_suggestions,
                    "supplement": rule,
                }
            )
            collections[kind][key] = AtomicProfileDefinition(
                kind,
                key,
                source,
                _freeze(capabilities),
                _freeze(_json_copy(rule.get("parameters", ()))),
                _freeze(_json_copy(rule.get("bindings", {}))),
                reference,
                rule.get("model_profile_key"),
                tuple(rule.get("aliases", ())),
                tuple(rule.get("endpoint_hints", ())),
                _freeze(overrides),
                _revision(parts),
            )
    return ProfileCatalog(
        _revision({"source": sources.revision, "supplements": supplements.revision, "composer": COMPOSER_REF}),
        _freeze(collections["model"]),
        _freeze(collections["provider"]),
        _freeze(collections["provider_model"]),
    )


def compose_provider_model_policy(
    catalog: ProfileCatalog,
    *,
    provider_key: str | None,
    request_model_id: str,
    model_profile_key: str | None,
    base_bindings: Mapping[str, object],
    base_instruction: VersionedReference,
    registered_references: Mapping[str, Sequence[VersionedReference]],
    submitted_values: Mapping[str, object],
    protected_api_paths: Sequence[str] = (),
    protocol_parameter_rules: Sequence[Mapping[str, object]] = (),
) -> ProviderModelPolicy:
    """Compose exact selections against a trusted implementation-availability snapshot."""
    if not isinstance(request_model_id, str) or not request_model_id.strip() or len(request_model_id) > 100:
        raise ProfileCompositionError("REQUEST_MODEL_ID_INVALID")
    provider = catalog.providers.get(provider_key) if provider_key is not None else None
    if provider_key is not None and provider is None:
        raise ProfileCompositionError("PROVIDER_PROFILE_NOT_FOUND")
    combo = catalog.provider_models.get(f"{provider_key}/{request_model_id}") if provider else None
    linked_model = combo.model_profile_key if combo else None
    if model_profile_key is not None and linked_model is not None and model_profile_key != linked_model:
        raise ProfileCompositionError("PROFILE_CONFLICT", "/selection/model_profile_key")
    model_profile_key = model_profile_key if model_profile_key is not None else linked_model
    model = catalog.models.get(model_profile_key) if model_profile_key is not None else None
    if model_profile_key is not None and model is None:
        raise ProfileCompositionError("MODEL_PROFILE_NOT_FOUND")
    # Complete the upstream baseline before applying any Nexent experience rule.
    capabilities = _capabilities({})
    for atom in (model, provider, combo):
        if atom is not None:
            _merge_capability_facts(capabilities, atom.source.capabilities)
    overrides = []
    parameters = {}
    for atom in (model, provider, combo):
        if atom is None:
            continue
        for override in atom.overrides:
            group, field = override["path"][1:].split("/")
            overrides.append(
                _apply_override(
                    capabilities,
                    {**override, "value": atom.capabilities[group][field]},
                    override["source"],
                )
            )
        for parameter in atom.parameters:
            parameters[parameter["key"]] = _json_copy(parameter)
    capabilities = _capabilities(capabilities)
    for rule in protocol_parameter_rules:
        declaration = _json_copy(rule)
        parameters.setdefault(rule["key"], declaration)
    compiled = compile_parameter_rules(list(parameters.values()))
    values = apply_parameter_values(compiled, submitted_values, scope="outlet", saved_values={})
    atomic_bindings = [atom.bindings if atom else {} for atom in (model, provider)]
    explicit_bindings = combo.bindings if combo else {}
    bindings = _compose_declarations(base_bindings, *atomic_bindings, explicit_bindings)
    instruction_declarations = [
        {"strategy": atom.instruction_reference.model_dump(mode="json")} if atom and atom.instruction_reference else {}
        for atom in (model, provider, combo)
    ]
    instruction = VersionedReference.model_validate(
        _compose_declarations(
            {"strategy": base_instruction.model_dump(mode="json")},
            *instruction_declarations,
        )["strategy"]
    )
    for name in ("protocol", "auth", "adapter", "code_converter", "native_converter"):
        if name not in bindings:
            raise ProfileCompositionError("PROFILE_BINDING_MISSING", "/bindings/" + name)
        try:
            reference = VersionedReference.model_validate(bindings[name])
        except ValidationError:
            raise ProfileCompositionError("PROFILE_BINDING_INVALID", "/bindings/" + name) from None
        if reference not in registered_references.get(name, ()):
            raise ProfileCompositionError("PROFILE_BINDING_UNREGISTERED", "/bindings/" + name)
    parameter_bindings = validate_parameter_bindings(
        compiled,
        registered_references.get("parameter_transform", ()),
        protected_paths=protected_api_paths,
    )
    parameter_schemas = {rule["key"]: compile_parameter_schema(rule["schema"]) for rule in compiled.declarations}
    for control in capabilities["reasoning"]["controls"] or ():
        if control["parameter_key"] not in parameter_bindings:
            raise ProfileCompositionError("REASONING_PARAMETER_BINDING_MISSING", "/capabilities/reasoning/controls")
        candidates = list(control.get("values", ())) + list(control.get("special_values", ()))
        for bound in ("min", "max"):
            if control.get(bound) is not None:
                candidates.append(control[bound])
        try:
            for candidate in candidates:
                validate_parameter_value(parameter_schemas[control["parameter_key"]], candidate)
        except ParameterValidationError:
            raise ProfileCompositionError(
                "REASONING_PARAMETER_SCHEMA_CONFLICT", "/capabilities/reasoning/controls"
            ) from None
    mapping = resolve_instruction_mapping(instruction).model_dump(mode="json")
    _check_profile_size(
        {
            "request_model_id": request_model_id,
            "capabilities": capabilities,
            "instruction_mapping": mapping,
            "bindings": bindings,
            "parameter_rules": compiled.declarations,
            "parameter_values": values,
            "overrides": overrides,
        }
    )
    parts = {
        "composer": COMPOSER_REF,
        "request_model_id": request_model_id,
        "bindings": json.dumps(bindings, sort_keys=True),
        "instruction": instruction.model_dump_json(),
    }
    for atom in (model, provider, combo):
        if atom:
            parts[f"{atom.kind}:{atom.key}"] = atom.revision
    return ProviderModelPolicy(
        request_model_id,
        model_profile_key,
        provider_key,
        _freeze(capabilities),
        _freeze(mapping),
        _freeze(bindings),
        compiled,
        parameter_bindings,
        _freeze(values),
        _freeze(overrides),
        catalog.revision,
        _revision(parts),
    )
