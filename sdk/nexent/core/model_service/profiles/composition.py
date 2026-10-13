"""Immutable atomic views and exact provider-model policy composition."""

import json
from dataclasses import dataclass
from typing import Mapping, Sequence

from pydantic import ValidationError

from nexent.core.model_service.profiles._models_dev.reader import _freeze
from nexent.core.model_service.profiles.contracts import ProfileCapabilities, VersionedReference
from nexent.core.model_service.profiles.instruction_mapping import resolve_instruction_mapping
from nexent.core.model_service.profiles.parameter_rules import (
    CompiledParameterRules,
    apply_parameter_values,
    compile_parameter_rules,
)
from nexent.core.model_service.profiles.parameter_schema import _json_copy, json_values_equal
from nexent.core.model_service.profiles.resolver import SourceCatalog, SourceCatalogEntry, _revision
from nexent.core.model_service.profiles.supplements import SupplementCatalog


COMPOSER_REF = "profile_policy_composer_v1"
_CAPABILITY_PATHS = frozenset(
    f"/{group}/{field}"
    for group, fields in {
        "context": ("combined_window", "input_limit", "output_limit"),
        "reasoning": ("status", "controls", "response_paths"),
        "tools": ("status", "schema_constraints", "result_format"),
        "sampling": ("temperature",),
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
    parameter_values: Mapping[str, object]
    overrides: tuple[Mapping[str, object], ...]
    catalog_revision: str
    revision: str


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


def _compose_declarations(base: Mapping, model: Mapping, provider: Mapping, combination: Mapping, path: str) -> dict:
    """Equal-priority atom conflicts require an explicit combination declaration."""
    conflicts = {
        key
        for key in model.keys() & provider.keys()
        if not json_values_equal(model[key], provider[key]) and key not in combination
    }
    if conflicts:
        raise ProfileCompositionError("PROFILE_CONFLICT", path + "/" + min(conflicts))
    result = _json_copy(base)
    for declarations in (model, provider, combination):
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
            reference = VersionedReference.model_validate(reference) if reference else None
            parts = {
                "composer": COMPOSER_REF,
                "source": source.profile_revision,
                "supplement_schema": supplements.schema_ref,
            }
            if supplement:
                parts[supplement.file_path] = supplement.content_sha256
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
    capabilities = _json_copy(model.capabilities) if model else _capabilities({})
    overrides = list(model.overrides) if model else []
    # Provider rules precede exact hosted-model facts and combination overrides.
    for atom in (provider, combo):
        if atom is None:
            continue
        if atom is combo:
            _merge_capability_facts(capabilities, atom.source.capabilities)
        for override in atom.overrides:
            group, field = override["path"][1:].split("/")
            overrides.append(
                _apply_override(
                    capabilities,
                    {
                        **override,
                        "value": atom.capabilities[group][field],
                    },
                    override["source"],
                )
            )
    capabilities = _capabilities(capabilities)
    parameters, conflicts = {}, set()
    for atom in (model, provider):
        for parameter in atom.parameters if atom else ():
            key = parameter["key"]
            if key in parameters and not json_values_equal(parameters[key], parameter):
                conflicts.add(key)
            else:
                parameters[key] = _json_copy(parameter)
    for parameter in combo.parameters if combo else ():
        parameters[parameter["key"]] = _json_copy(parameter)
        conflicts.discard(parameter["key"])
    if conflicts:
        raise ProfileCompositionError("PROFILE_CONFLICT", "/parameter_rules/" + min(conflicts))
    compiled = compile_parameter_rules(list(parameters.values()))
    values = apply_parameter_values(compiled, submitted_values, scope="outlet", saved_values={})
    atomic_bindings = [atom.bindings if atom else {} for atom in (model, provider)]
    explicit_bindings = combo.bindings if combo else {}
    bindings = _compose_declarations(base_bindings, *atomic_bindings, explicit_bindings, "/bindings")
    instruction_declarations = [
        {"strategy": atom.instruction_reference.model_dump(mode="json")} if atom and atom.instruction_reference else {}
        for atom in (model, provider, combo)
    ]
    instruction = VersionedReference.model_validate(
        _compose_declarations(
            {"strategy": base_instruction.model_dump(mode="json")},
            *instruction_declarations,
            "/instruction_mapping",
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
    mapping = resolve_instruction_mapping(instruction).model_dump(mode="json")
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
        _freeze(values),
        _freeze(overrides),
        catalog.revision,
        _revision(parts),
    )
