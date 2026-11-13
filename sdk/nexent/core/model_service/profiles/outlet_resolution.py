# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Construct complete outlet snapshots from trusted save-time composition."""

from collections.abc import Mapping, Sequence

from pydantic import ValidationError

from nexent.core.model_service.profiles.composition import COMPOSER_REF, ProfileCatalog, ProviderModelPolicy
from nexent.core.model_service.profiles.contracts import InstructionMappingDefinition, VersionedReference
from nexent.core.model_service.profiles.instruction_mapping import (
    InstructionMappingError,
    validate_instruction_mapping,
)
from nexent.core.model_service.profiles.outlet_storage import ProfileStorageError, encode_resolved_model_profile
from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError, _json_copy
from nexent.core.model_service.profiles.resolved_profile import (
    ConnectionRules,
    ContextConfiguration,
    OutletConnection,
    OutletIdentity,
    ResolvedModelProfile,
)
from nexent.core.model_service.profiles.resolver import PARSER_REF
from nexent.core.model_service.profiles.supplements import SUPPLEMENT_SCHEMA_REF


class OutletResolutionError(ValueError):
    """A construction diagnostic contains categories, never submitted values."""

    def __init__(self, category):
        self.category = category
        super().__init__(category)


def _selected_atoms(policy, catalog):
    if policy.catalog_revision != catalog.revision:
        raise OutletResolutionError("PROFILE_CATALOG_REVISION_MISMATCH")
    model = catalog.models.get(policy.model_profile_key) if policy.model_profile_key else None
    provider = catalog.providers.get(policy.provider_key) if policy.provider_key else None
    if (policy.model_profile_key and model is None) or (policy.provider_key and provider is None):
        raise OutletResolutionError("PROFILE_SELECTION_INVALID")
    combination = catalog.provider_models.get(f"{policy.provider_key}/{policy.request_model_id}") if provider else None
    if combination and combination.model_profile_key and combination.model_profile_key != policy.model_profile_key:
        raise OutletResolutionError("PROFILE_SELECTION_INVALID")
    return {"model": model, "provider": provider, "provider_model": combination}


def _provenance(policy, atoms):
    references, origins, metadata = {}, [], {}
    for kind, atom in atoms.items():
        references[kind] = None
        if atom is None:
            continue
        candidates = [reference for reference in atom.source.source_refs if reference.key == atom.key]
        if len(candidates) != 1:
            raise OutletResolutionError("PROFILE_SOURCE_REFERENCE_INVALID")
        references[kind] = candidates[0].model_dump(mode="json")
        for origin in atom.source.field_origins.values():
            mapped = origin.mapping
            origins.append({
                "target_path": origin.target_path,
                "source_path": mapped.source.file_path + "#" + mapped.source.source_path,
                "atom_kind": mapped.source.source_kind,
                "rule_id": mapped.rule_id,
                "rule_version": mapped.rule_version,
            })
        if atom.source.reference_metadata:
            metadata[kind] = _json_copy(atom.source.reference_metadata)
    return {
        "atomic_refs": references,
        "interpretation_versions": {
            "source_parser": {"ref": PARSER_REF, "version": 1},
            "source_mapping": {"ref": "models_dev_source_v1", "version": 1},
            "supplement_schema": {"ref": SUPPLEMENT_SCHEMA_REF, "version": 1},
            "composer": {"ref": COMPOSER_REF, "version": 4},
        },
        "overrides": _json_copy(policy.overrides),
        "field_sources": origins,
        "provider_metadata": metadata,
    }


def construct_resolved_model_profile(
    policy: ProviderModelPolicy,
    catalog: ProfileCatalog,
    *,
    tenant_id: str,
    display_name: str,
    model_type: str,
    provider_id: str,
    connection: OutletConnection,
    connection_rules: ConnectionRules,
    context_configuration: ContextConfiguration,
    registered_references: Mapping[str, Sequence[VersionedReference]],
    extra_api_parameters: Sequence[Mapping] = (),
    protected_paths: Sequence[str] = (),
) -> ResolvedModelProfile:
    """Build a new outlet from a server-composed draft; never accept a frontend-authored policy.

    No defaults are applied here. The caller provides registry/connection policy
    and owns the subsequent database transaction and credential assignment.
    """
    if not isinstance(policy, ProviderModelPolicy) or not isinstance(catalog, ProfileCatalog):
        raise OutletResolutionError("PROFILE_SELECTION_INVALID")
    atoms = _selected_atoms(policy, catalog)
    try:
        snapshot = ResolvedModelProfile(
            schema_version=1,
            outlet_id=None,
            config_revision=1,
            identity=OutletIdentity(
                tenant_id=tenant_id,
                display_name=display_name,
                model_type=model_type,
                provider_id=provider_id,
                request_model_id=policy.request_model_id,
                provider_key=policy.provider_key,
                model_profile_key=policy.model_profile_key,
            ),
            connection=connection.model_dump(mode="json"),
            connection_rules=connection_rules.model_dump(mode="json"),
            context_configuration=context_configuration.model_dump(mode="json"),
            capabilities=_json_copy(policy.capabilities),
            instruction_mapping=_json_copy(policy.instruction_mapping),
            parameter_rules=_json_copy(policy.parameter_rules.declarations),
            parameter_values=_json_copy(policy.parameter_values),
            extra_api_parameters=_json_copy(extra_api_parameters),
            bindings={
                **_json_copy(policy.bindings),
                "role_mapping": validate_instruction_mapping(
                    InstructionMappingDefinition.model_validate(_json_copy(policy.instruction_mapping))
                ).model_dump(mode="json"),
            },
            provenance=_provenance(policy, atoms),
        )
        # Reuse the save boundary for availability, column and ownership checks.
        encode_resolved_model_profile(
            snapshot, registered_references=registered_references, protected_paths=protected_paths
        )
        return snapshot
    except (ValidationError, ProfileStorageError, InstructionMappingError, ParameterValidationError, TypeError, AttributeError):
        raise OutletResolutionError("PROFILE_RESOLUTION_INVALID") from None
