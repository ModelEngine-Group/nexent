# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Atomic loading of pinned source profiles before Nexent supplements and API bindings."""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from pydantic import ValidationError

from nexent.core.model_service.profiles._models_dev.inheritance import EffectiveSourceModel, resolve_source_model
from nexent.core.model_service.profiles._models_dev.mapping import (
    MappedFieldOrigin,
    map_source_fields,
    SOURCE_MAPPING,
    mapping_fingerprint,
)
from nexent.core.model_service.profiles._models_dev.reader import (
    SourceDocument,
    SourceReadError,
    _freeze,
    read_inventory,
)
from nexent.core.model_service.profiles.contracts import (
    AtomicProfileReference,
    ContextCapabilities,
    ReasoningCapabilities,
)


PARSER_REF = "models_dev_source_catalog_v3"
SUPPORTED_UPSTREAM_REVISION = "e69e1844210e5cfe7c7e7f68d57328bc7451a51c"


@dataclass(frozen=True)
class CatalogFieldOrigin:
    mapping: MappedFieldOrigin
    target_path: str
    normalization_ref: str = PARSER_REF


@dataclass(frozen=True)
class SourceCatalogEntry:
    """Source-only declaration, not a complete ModelProfile or usable outlet."""

    kind: str
    key: str
    identity: Mapping[str, object]
    capabilities: Mapping[str, object]
    reference_metadata: Mapping[str, object]
    connection_suggestions: Mapping[str, object]
    field_origins: Mapping[str, CatalogFieldOrigin]
    source_refs: tuple[AtomicProfileReference, ...]
    profile_revision: str


@dataclass(frozen=True)
class SourceCatalog:
    revision: str
    upstream_revision: str
    parser_ref: str
    mapping_id: str
    mapping_version: int
    models: Mapping[str, SourceCatalogEntry]
    providers: Mapping[str, SourceCatalogEntry]
    provider_models: Mapping[str, SourceCatalogEntry]


def _error(category: str, document: SourceDocument, path: str = "") -> SourceReadError:
    error = SourceReadError(category, document.file_path, document.kind)
    error.source_path = path
    error.rule_id = PARSER_REF
    return error


def _revision(parts: Mapping[str, str]) -> str:
    digest = hashlib.sha256()
    for key, value in sorted(parts.items()):
        for item in (key, value):
            data = item.encode("utf-8")
            digest.update(len(data).to_bytes(8, "big"))
            digest.update(data)
    return digest.hexdigest()


def _tree(values: Mapping[str, object]) -> dict:
    """Materialize canonical pointer fields, preserving explicit arrays and nulls."""
    root = {}
    for pointer, value in values.items():
        parts = pointer.split("/")[1:]
        current = root
        for index, part in enumerate(parts):
            last = index == len(parts) - 1
            key = int(part) if isinstance(current, list) else part
            if isinstance(current, list):
                while len(current) <= key:
                    current.append(None)
            if last:
                current[key] = value
            else:
                next_value = [] if parts[index + 1].isdigit() else {}
                if isinstance(current, list):
                    if current[key] is None:
                        current[key] = next_value
                elif key not in current:
                    current[key] = next_value
                current = current[key]
    return root


def _controls(reasoning: dict) -> list | None:
    if "control_candidates" not in reasoning:
        return None
    controls = []
    for option in reasoning["control_candidates"]:
        mode = option["type"]
        if mode == "toggle":
            controls.append({"mode": "toggle", "values": [True, False]})
        elif mode == "effort":
            controls.append(
                {"mode": "effort", "values": [None if value == "null" else value for value in option["values"]]}
            )
        else:
            lower = option.get("min")
            controls.append(
                {
                    "mode": "budget_tokens",
                    "min": None if lower == -1 else lower,
                    "max": option.get("max"),
                    "special_values": [-1] if lower == -1 else [],
                }
            )
    return controls


def _normalized_origins(mapped, controls) -> dict:
    origins = {}
    for path, origin in mapped.field_origins.items():
        target = path
        if path.startswith("/reasoning/control_candidates"):
            target = path.replace("/reasoning/control_candidates", "/capabilities/reasoning/controls", 1)
            target = re.sub(r"/type$", "/mode", target)
            if path.endswith("/min") and mapped.values[path] == -1:
                target = target[: -len("min")] + "special_values/0"
        elif path.split("/")[1] in {"context", "reasoning", "tools", "sampling", "structured_output", "modalities"}:
            target = "/capabilities" + path
        origins[target] = CatalogFieldOrigin(origin, target)
    for index, control in enumerate(controls or ()):
        prefix = f"/capabilities/reasoning/controls/{index}"
        type_origin = origins[prefix + "/mode"].mapping
        origins[prefix + "/parameter_key"] = CatalogFieldOrigin(type_origin, prefix + "/parameter_key")
        if control["mode"] == "toggle":
            for value_index in range(2):
                path = prefix + f"/values/{value_index}"
                origins[path] = CatalogFieldOrigin(type_origin, path)
    return origins


def _entry(
    document: SourceDocument, source, registry, providers: Mapping, revision: str, version_parts: dict
) -> SourceCatalogEntry:
    mapped = map_source_fields(source, registry)
    tree = _tree(mapped.values)
    unexpected = set(tree) - {
        "identity",
        "context",
        "reasoning",
        "tools",
        "sampling",
        "structured_output",
        "modalities",
        "reference_metadata",
        "connection_suggestions",
    }
    if unexpected:
        raise _error("SOURCE_TARGET_UNHANDLED", document)
    reasoning = tree.get("reasoning", {})
    controls = _controls(reasoning)
    try:
        context = ContextCapabilities.model_validate(tree.get("context", {}))
    except ValidationError:
        raise _error("SOURCE_NORMALIZATION_INVALID", document, "limit") from None
    try:
        thinking = ReasoningCapabilities(status=reasoning.get("status", "unknown"), controls=controls)
    except ValidationError:
        raise _error("SOURCE_NORMALIZATION_INVALID", document, "reasoning_options") from None
    capabilities = {
        "context": context.model_dump(),
        "reasoning": thinking.model_dump(),
        "tools": tree.get("tools", {"status": "unknown"}),
        "sampling": tree.get("sampling", {}),
        "structured_output": tree.get("structured_output", {"status": "unknown"}),
        "modalities": tree.get("modalities", {"input": None, "output": None}),
    }
    if document.kind == "provider":
        capabilities = {}
    dependencies = source.dependencies if isinstance(source, EffectiveSourceModel) else (document,)
    if document.kind == "provider_model":
        provider_key = document.key.split("/", 1)[0]
        if provider_key not in providers:
            raise _error("SOURCE_PROVIDER_MISSING", document)
        dependencies = (*dependencies, providers[provider_key])
    profile_parts = dict(version_parts)
    refs = []
    for dependency in dependencies:
        profile_parts[dependency.file_path] = dependency.content_sha256
        refs.append(
            AtomicProfileReference(
                key=dependency.key,
                catalog_revision=dependency.source_revision or revision,
                file_path=dependency.file_path,
                content_sha256=dependency.content_sha256,
            )
        )
    metadata = dict(tree.get("reference_metadata", {}))
    if document.origin == "nexent":
        origin = {"kind": document.origin, "revision": document.source_revision, "url": document.source_url}
        metadata["source_origin"] = origin
        profile_parts.update({"origin_" + key: value for key, value in origin.items()})
    return SourceCatalogEntry(
        document.kind,
        document.key,
        _freeze(tree.get("identity", {})),
        _freeze(capabilities),
        _freeze(metadata),
        _freeze(tree.get("connection_suggestions", {})),
        _freeze(_normalized_origins(mapped, controls)),
        tuple(refs),
        _revision(profile_parts),
    )


def load_source_catalog(root: Path | None = None) -> SourceCatalog:
    """Convert the submission-checked immutable source catalog without repeating source validation."""
    root = (root if root is not None else Path(__file__).parent).resolve()
    inventory = read_inventory(root)
    if inventory.upstream_revision != SUPPORTED_UPSTREAM_REVISION:
        error = SourceReadError("SOURCE_SCHEMA_UNSUPPORTED", "manifest.toml", "manifest")
        error.source_path = "upstream_revision"
        error.rule_id = PARSER_REF
        raise error
    registry = SOURCE_MAPPING
    version_parts = {
        "parser_ref": PARSER_REF,
        "source_schema_ref": inventory.source_schema_ref,
        "mapping_ref": registry.mapping_id,
        "mapping_version": str(registry.mapping_version),
        "mapping_sha256": mapping_fingerprint(registry),
        "upstream_revision": inventory.upstream_revision,
    }
    catalog_parts = {
        **version_parts,
        "manifest_sha256": inventory.manifest_sha256,
        **{document.file_path: document.content_sha256 for document in inventory.documents},
    }
    revision = _revision(catalog_parts)
    providers = {document.key: document for document in inventory.documents if document.kind == "provider"}
    entries = {"model": {}, "provider": {}, "provider_model": {}}
    for document in inventory.documents:
        source = document
        if document.kind != "provider":
            source = resolve_source_model(document, inventory.documents)
        entries[document.kind][document.key] = _entry(document, source, registry, providers, revision, version_parts)
    return SourceCatalog(
        revision,
        inventory.upstream_revision,
        PARSER_REF,
        registry.mapping_id,
        registry.mapping_version,
        _freeze(entries["model"]),
        _freeze(entries["provider"]),
        _freeze(entries["provider_model"]),
    )


def load_profile_catalog(root: Path | None = None):
    """Load source facts and explicit Nexent policy through one atomic entry point."""
    from nexent.core.model_service.profiles.composition import build_profile_catalog
    from nexent.core.model_service.profiles.supplements import load_supplements

    root = (root if root is not None else Path(__file__).parent).resolve()
    sources = load_source_catalog(root)
    supplements = load_supplements(root, sources)
    return build_profile_catalog(sources, supplements)
