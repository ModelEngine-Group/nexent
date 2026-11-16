# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Pinned authored base_model inheritance with per-field source ownership."""

from dataclasses import dataclass
from typing import Mapping

from nexent.core.model_service.profiles._models_dev.reader import SourceDocument, SourceReadError, _freeze


_EXCLUDED_BASE_FIELDS = frozenset({"id", "license", "links", "weights", "benchmarks"})


@dataclass(frozen=True)
class FieldOrigin:
    """Source ownership before the versioned semantic mapping is applied."""

    source_kind: str
    file_path: str
    source_path: str
    content_sha256: str


@dataclass(frozen=True)
class EffectiveSourceModel:
    """Read-only source result, distinct from a resolved Nexent outlet."""

    document: SourceDocument
    data: Mapping[str, object]
    field_origins: Mapping[str, FieldOrigin]
    dependencies: tuple[SourceDocument, ...]
    omitted_paths: tuple[str, ...]


def _error(category: str, document: SourceDocument, source_path: str) -> SourceReadError:
    error = SourceReadError(category, document.file_path, document.kind)
    error.source_path = source_path
    error.rule_id = "source_inheritance_v1"
    return error


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_thaw(item) for item in value]
    return value


def _collect_origins(value: object, path: str, document: SourceDocument, origins: dict) -> None:
    if isinstance(value, Mapping) and value:
        for key, item in value.items():
            _collect_origins(item, f"{path}.{key}" if path else key, document, origins)
    elif isinstance(value, (tuple, list)) and value:
        for index, item in enumerate(value):
            _collect_origins(item, f"{path}[{index}]", document, origins)
    elif path:
        origins[path] = FieldOrigin(document.kind, document.file_path, path, document.content_sha256)


def _clear_origins(origins: dict, path: str) -> None:
    for key in tuple(origins):
        if key == path or key.startswith(path + ".") or key.startswith(path + "["):
            del origins[key]


def _overlay(target: dict, updates: Mapping, path: str, document: SourceDocument, origins: dict) -> None:
    for key, value in updates.items():
        field_path = f"{path}.{key}" if path else key
        if isinstance(target.get(key), dict) and isinstance(value, Mapping):
            if value:
                origins.pop(field_path, None)
            _overlay(target[key], value, field_path, document, origins)
        else:
            _clear_origins(origins, field_path)
            target[key] = _thaw(value)
            _collect_origins(value, field_path, document, origins)


def _omit(target: dict, path: str, origins: dict) -> None:
    parts = path.split(".")
    current = target
    parents = []
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            return
        parents.append((current, part))
        current = child
    if parts[-1] not in current:
        return
    del current[parts[-1]]
    _clear_origins(origins, path)
    for parent, key in reversed(parents):
        if parent[key]:
            break
        del parent[key]


def resolve_source_model(document: SourceDocument, sources: tuple[SourceDocument, ...]) -> EffectiveSourceModel:
    """Use only explicit base references; never infer a model from its name."""
    if document.kind not in ("model", "provider_model"):
        raise _error("SOURCE_MODEL_KIND_INVALID", document, "")
    models = {}
    for source in sources:
        if source.kind == "model":
            if source.key in models:
                raise _error("SOURCE_DUPLICATE", source, "")
            models[source.key] = source

    origins = {}
    dependencies = (document,)
    data = {}
    if "base_model" in document.data:
        base_key = document.data["base_model"]
        if document.kind != "provider_model" or not isinstance(base_key, str) or not base_key.strip():
            raise _error("SOURCE_BASE_REFERENCE_INVALID", document, "base_model")
        base = models.get(base_key)
        if base is None:
            raise _error("SOURCE_BASE_MODEL_MISSING", document, "base_model")
        if "base_model" in base.data:
            raise _error("SOURCE_BASE_REFERENCE_INVALID", base, "base_model")
        data = _thaw({key: value for key, value in base.data.items() if key not in _EXCLUDED_BASE_FIELDS})
        _collect_origins(data, "", base, origins)
        dependencies = (base, document)
    elif "base_model_omit" in document.data:
        raise _error("SOURCE_OMIT_WITHOUT_BASE", document, "base_model_omit")

    omissions = document.data.get("base_model_omit", ())
    if not isinstance(omissions, (tuple, list)) or any(
        not isinstance(path, str) or any(not part for part in path.split(".")) for path in omissions
    ):
        raise _error("SOURCE_OMIT_INVALID", document, "base_model_omit")
    updates = {key: value for key, value in document.data.items() if key not in ("base_model", "base_model_omit")}
    _overlay(data, updates, "", document, origins)
    for path in omissions:
        _omit(data, path, origins)
    return EffectiveSourceModel(document, _freeze(data), _freeze(origins), dependencies, tuple(omissions))
