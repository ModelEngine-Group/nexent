"""Versioned source dispositions, separate from runtime API field bindings."""

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping

from pydantic import Field, ValidationError

from nexent.core.model_service.profiles._models_dev.inheritance import EffectiveSourceModel, FieldOrigin
from nexent.core.model_service.profiles._models_dev.reader import SourceDocument, SourceReadError, _freeze
from nexent.core.model_service.profiles.contracts import NonBlankString, ProfileContract


class SourceMappingRule(ProfileContract):
    """One explicitly scoped authored field disposition."""

    rule_id: NonBlankString
    rule_version: int = Field(ge=1, le=1)
    source_schema_ref: Literal["models_dev_authored_v1"]
    source_kind: Literal["model", "provider", "provider_model"]
    source_path: NonBlankString
    source_type: Literal["boolean", "string", "integer", "number", "number_or_string", "object", "array"]
    target_path: NonBlankString
    transform_ref: Literal["identity_v1", "boolean_capability_v1", "zero_unknown_tokens_v1"]
    missing_policy: Literal["omit", "unknown"]
    special_value_policy: Literal["preserve", "zero_is_unknown", "strict_boolean"]
    disposition: Literal["map", "reference"]
    evidence: NonBlankString


class SourceMappingRegistry(ProfileContract):
    mapping_id: Literal["models_dev_source_v1"]
    mapping_version: int = Field(ge=1, le=1)
    rules: tuple[SourceMappingRule, ...] = Field(min_length=1)


@dataclass(frozen=True)
class MappedFieldOrigin:
    source: FieldOrigin
    rule_id: str
    rule_version: int
    target_path: str


@dataclass(frozen=True)
class MappedSourceFields:
    """Canonical fields before supplements and runtime profile composition."""

    source: EffectiveSourceModel | SourceDocument
    mapping_id: str
    mapping_version: int
    values: Mapping[str, object]
    field_origins: Mapping[str, MappedFieldOrigin]


def _error(category: str, file_path: str, kind: str, path: str = "") -> SourceReadError:
    error = SourceReadError(category, file_path, kind)
    error.source_path = path
    error.rule_id = "models_dev_source_v1"
    return error


def load_mapping_rules(path: Path) -> SourceMappingRegistry:
    """Load the explicitly selected local registry; unknown rules fail closed."""
    try:
        data = path.read_bytes()
    except OSError:
        raise _error("SOURCE_MAPPING_INVALID", path.name, "mapping") from None
    return parse_mapping_rules(data, path.name)


def parse_mapping_rules(data: bytes, file_path: str) -> SourceMappingRegistry:
    """Parse a captured rule snapshot; revision hashing uses these same bytes."""
    try:
        raw = tomllib.loads(data.decode("utf-8"))
        if isinstance(raw.get("rules"), list):
            raw["rules"] = tuple(raw["rules"])
        registry = SourceMappingRegistry.model_validate(raw)
    except (UnicodeDecodeError, tomllib.TOMLDecodeError, ValidationError):
        raise _error("SOURCE_MAPPING_INVALID", file_path, "mapping") from None
    identities = set()
    rule_ids = set()
    targets = set()
    for rule in registry.rules:
        identity = (rule.source_kind, rule.source_path)
        if identity in identities or rule.rule_id in rule_ids:
            raise _error("SOURCE_MAPPING_DUPLICATE", file_path, "mapping", rule.source_path)
        identities.add(identity)
        rule_ids.add(rule.rule_id)
        target_identity = (rule.source_kind, rule.target_path)
        if target_identity in targets:
            raise _error("SOURCE_TARGET_CONFLICT", file_path, "mapping", rule.source_path)
        targets.add(target_identity)
        if (
            not re.fullmatch(
                r"/[a-zA-Z_][a-zA-Z0-9_]*(?:\[\])?(?:/[a-zA-Z_][a-zA-Z0-9_]*(?:\[\])?)*", rule.target_path
            )
            or not re.fullmatch(
                r"[a-zA-Z_][a-zA-Z0-9_]*(?:\[\])?(?:\.[a-zA-Z_][a-zA-Z0-9_]*(?:\[\])?)*", rule.source_path
            )
            or rule.source_path.count("[]") != rule.target_path.count("[]")
        ):
            raise _error("SOURCE_MAPPING_INVALID", file_path, "mapping", rule.source_path)
        if (rule.transform_ref == "boolean_capability_v1" and rule.source_type != "boolean") or (
            rule.transform_ref == "zero_unknown_tokens_v1" and rule.source_type != "integer"
        ):
            raise _error("SOURCE_MAPPING_INVALID", file_path, "mapping", rule.source_path)
        expected_policy = {
            "identity_v1": "preserve",
            "boolean_capability_v1": "strict_boolean",
            "zero_unknown_tokens_v1": "zero_is_unknown",
        }[rule.transform_ref]
        if rule.special_value_policy != expected_policy:
            raise _error("SOURCE_MAPPING_INVALID", file_path, "mapping", rule.source_path)
    for parent in registry.rules:
        if parent.source_type in ("object", "array"):
            continue
        for child in registry.rules:
            if (
                parent.source_kind == "provider_model"
                and parent.source_path == "interleaved"
                and child.source_kind == parent.source_kind
                and child.source_path == "interleaved.field"
            ):
                continue
            if child.source_kind == parent.source_kind and child.target_path.startswith(parent.target_path + "/"):
                raise _error("SOURCE_TARGET_CONFLICT", file_path, "mapping", child.source_path)
    return registry


def _leaves(value: object, path: str = ""):
    if isinstance(value, Mapping) and value:
        for key, item in value.items():
            yield from _leaves(item, f"{path}.{key}" if path else key)
    elif isinstance(value, (tuple, list)) and value:
        for index, item in enumerate(value):
            yield from _leaves(item, f"{path}[{index}]")
    elif path:
        yield path, value


def _typed(value: object, source_type: str) -> bool:
    return {
        "boolean": type(value) is bool,
        "string": isinstance(value, str),
        "integer": type(value) is int,
        "number": type(value) in (int, float),
        "number_or_string": type(value) in (int, float) or isinstance(value, str),
        "object": isinstance(value, Mapping),
        "array": isinstance(value, (tuple, list)),
    }[source_type]


def map_source_fields(
    source: EffectiveSourceModel | SourceDocument, registry: SourceMappingRegistry
) -> MappedSourceFields:
    """Map every validated leaf explicitly; no field-name aliases or API paths."""
    document = source.document if isinstance(source, EffectiveSourceModel) else source
    rules = {rule.source_path: rule for rule in registry.rules if rule.source_kind == document.kind}
    values = {}
    origins = {}
    for path, value in _leaves(source.data):
        pattern = re.sub(r"\[\d+\]", "[]", path)
        rule = rules.get(pattern)
        if rule is None:
            raise _error("SOURCE_FIELD_UNHANDLED", document.file_path, document.kind, path)
        if not _typed(value, rule.source_type):
            raise _error("SOURCE_VALUE_INVALID", document.file_path, document.kind, path)
        indexes = iter(re.findall(r"\[(\d+)\]", path))
        target = re.sub(r"\[\]", lambda _: "/" + next(indexes), rule.target_path)
        if target in values:
            raise _error("SOURCE_TARGET_CONFLICT", document.file_path, document.kind, path)
        if rule.transform_ref == "boolean_capability_v1":
            value = "supported" if value else "unsupported"
        elif rule.transform_ref == "zero_unknown_tokens_v1" and value == 0:
            value = None
        values[target] = value
        origins[target] = MappedFieldOrigin(
            source.field_origins[path]
            if isinstance(source, EffectiveSourceModel)
            else FieldOrigin(document.kind, document.file_path, path, document.content_sha256),
            rule.rule_id,
            rule.rule_version,
            target,
        )
    for path, rule in rules.items():
        if "[]" not in path and rule.missing_policy == "unknown" and rule.target_path not in values:
            values[rule.target_path] = "unknown" if rule.transform_ref == "boolean_capability_v1" else None
    return MappedSourceFields(source, registry.mapping_id, registry.mapping_version, _freeze(values), _freeze(origins))
