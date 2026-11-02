# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Read explicit Nexent supplement declarations separately from upstream TOML."""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping

from pydantic import Field, JsonValue, ValidationError, model_validator

from nexent.core.model_service.profiles._models_dev.reader import SourceReadError, _freeze, _parse, _read
from nexent.core.model_service.profiles.contracts import (
    AtomicProfileReference,
    NonBlankString,
    ProfileContract,
    VersionedReference,
)
from nexent.core.model_service.profiles.instruction_mapping import InstructionMappingError, resolve_instruction_mapping
from nexent.core.model_service.profiles.parameter_rules import ParameterRule, compile_parameter_rules
from nexent.core.model_service.profiles.parameter_schema import (
    ParameterValidationError,
    compile_parameter_schema,
    validate_parameter_value,
)
from nexent.core.model_service.profiles.resolver import SourceCatalog, _revision


MANIFEST_PATH = "rules/manifest.toml"
SUPPLEMENT_SCHEMA_REF = "nexent_supplements_v1"


class CapabilityOverride(ProfileContract):
    """An explicit changed fact, accompanied by human-readable evidence."""

    path: NonBlankString
    value: JsonValue
    reason: NonBlankString
    evidence: NonBlankString


class SupplementBindings(ProfileContract):
    """Declared versioned dependencies; availability is checked during composition."""

    protocol: VersionedReference | None = None
    auth: VersionedReference | None = None
    adapter: VersionedReference | None = None
    code_converter: VersionedReference | None = None
    native_converter: VersionedReference | None = None


class SupplementRule(ProfileContract):
    """One exact source target; no regex, dynamic imports or implicit name matching."""

    schema_version: int = Field(ge=1, le=1)
    rule_id: NonBlankString
    version: int = Field(gt=0)
    target_kind: Literal["model", "provider", "provider_model"]
    target_key: NonBlankString
    reason: NonBlankString
    evidence: NonBlankString
    model_profile_key: NonBlankString | None = None
    aliases: list[NonBlankString] = Field(default_factory=list)
    endpoint_hints: list[NonBlankString] = Field(default_factory=list)
    instruction_mapping: VersionedReference | None = None
    bindings: SupplementBindings | None = None
    parameters: list[ParameterRule] = Field(default_factory=list)
    capability_overrides: list[CapabilityOverride] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_ownership(self):
        if len(set(self.aliases)) != len(self.aliases) or len(set(self.endpoint_hints)) != len(self.endpoint_hints):
            raise ValueError("Supplement hints must be unique")
        if self.model_profile_key is not None and self.target_kind != "provider_model":
            raise ValueError("Only provider-model rules can link a model profile")
        if self.aliases and self.target_kind != "model":
            raise ValueError("Model aliases require model ownership")
        if self.endpoint_hints and self.target_kind != "provider":
            raise ValueError("Endpoint hints require provider ownership")
        return self


class SupplementFile(ProfileContract):
    path: NonBlankString
    content_sha256: NonBlankString


class SupplementManifest(ProfileContract):
    schema_version: int = Field(ge=1, le=1)
    rules: list[SupplementFile]


class SupplementReadError(ValueError):
    """Do not expose file contents, fixed values or operating system details."""

    def __init__(self, category: str, file_path: str, field_path: str = ""):
        self.category, self.file_path, self.field_path = category, file_path, field_path
        super().__init__(f"{category}: {file_path}: {field_path}")


@dataclass(frozen=True)
class SupplementEntry:
    file_path: str
    content_sha256: str
    rule: Mapping[str, object]


@dataclass(frozen=True)
class SupplementCatalog:
    revision: str
    schema_ref: str
    entries: Mapping[str, SupplementEntry]
    source_revision: str


def _document(root: Path, path: str) -> tuple[dict, bytes]:
    try:
        data = _read(root, path, "supplement")
        return _parse(data, path, "supplement"), data
    except SourceReadError:
        raise SupplementReadError("SUPPLEMENT_FILE_INVALID", path) from None


def _decode_json_fields(authored: dict, file_path: str) -> dict:
    """Explicitly encode JSON-only values; ordinary TOML strings keep their meaning."""
    copied = dict(authored)
    directives = copied.pop("json_fields", {})
    if not isinstance(directives, dict):
        raise SupplementReadError("SUPPLEMENT_JSON_FIELD_INVALID", file_path, "json_fields")

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON field")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError("Nonfinite JSON value")

    for pointer, encoded in directives.items():
        match = re.fullmatch(
            r"/(parameters|capability_overrides)/(0|[1-9][0-9]*)/(schema|default_value|fixed_value|condition|value)",
            pointer,
        )
        if match is None or not isinstance(encoded, str):
            raise SupplementReadError("SUPPLEMENT_JSON_FIELD_INVALID", file_path, "json_fields")
        group, index_text, field = match.groups()
        allowed = {
            "parameters": {"schema", "default_value", "fixed_value", "condition"},
            "capability_overrides": {"value"},
        }
        items = copied.get(group)
        if (
            field not in allowed[group]
            or not isinstance(items, list)
            or len(index_text) > len(str(len(items)))
            or int(index_text) >= len(items)
            or not isinstance(items[int(index_text)], dict)
        ):
            raise SupplementReadError("SUPPLEMENT_JSON_FIELD_INVALID", file_path, pointer)
        item = items[int(index_text)]
        if field in item:
            raise SupplementReadError("SUPPLEMENT_JSON_FIELD_CONFLICT", file_path, pointer)
        try:
            value = json.loads(encoded, object_pairs_hook=unique_object, parse_constant=invalid_constant)
            validate_parameter_value(compile_parameter_schema({}), value)
        except (ValueError, RecursionError):
            raise SupplementReadError("SUPPLEMENT_JSON_FIELD_INVALID", file_path, pointer) from None
        # Copy the touched container rather than mutating the authored declaration.
        items = [dict(entry) if isinstance(entry, dict) else entry for entry in items]
        items[int(index_text)][field] = value
        copied[group] = items
    return copied


def load_supplements(root: Path, sources: SourceCatalog) -> SupplementCatalog:
    """Read a complete immutable declaration catalog; final policy composition follows."""
    root = root.resolve()
    authored, manifest_bytes = _document(root, MANIFEST_PATH)
    try:
        manifest = SupplementManifest.model_validate(authored)
    except ValidationError as error:
        location = "/".join(str(part) for part in error.errors(include_input=False)[0]["loc"])
        raise SupplementReadError("SUPPLEMENT_MANIFEST_INVALID", MANIFEST_PATH, location) from None
    entries, paths, targets = {}, set(), set()
    parts = {
        "schema_ref": SUPPLEMENT_SCHEMA_REF,
        "source_catalog": sources.revision,
        "manifest": hashlib.sha256(manifest_bytes).hexdigest(),
    }
    available = {"model": sources.models, "provider": sources.providers, "provider_model": sources.provider_models}
    for declared in manifest.rules:
        path = declared.path
        try:
            AtomicProfileReference(
                key="supplement",
                catalog_revision=sources.revision,
                file_path=path,
                content_sha256=declared.content_sha256,
            )
        except ValidationError:
            raise SupplementReadError("SUPPLEMENT_PATH_INVALID", path) from None
        if not path.startswith(("rules/models/", "rules/providers/")) or not path.endswith(".toml") or path in paths:
            raise SupplementReadError("SUPPLEMENT_PATH_INVALID", path)
        paths.add(path)
        authored, data = _document(root, path)
        digest = hashlib.sha256(data).hexdigest()
        if digest != declared.content_sha256:
            raise SupplementReadError("SUPPLEMENT_HASH_MISMATCH", path)
        try:
            validate_parameter_value(compile_parameter_schema({}), authored)
        except ParameterValidationError as error:
            raise SupplementReadError("SUPPLEMENT_RULE_INVALID", path, error.path) from None
        authored = _decode_json_fields(authored, path)
        try:
            rule = SupplementRule.model_validate(authored)
            # Conditions can refer to parameters in another participating atom.
            # Compile the combined dependency graph only after profile composition.
            declarations = [parameter.model_dump(by_alias=True, exclude_unset=True) for parameter in rule.parameters]
            compile_parameter_rules([{**declaration, "condition": None} for declaration in declarations])
            if rule.instruction_mapping is not None:
                resolve_instruction_mapping(rule.instruction_mapping)
        except ValidationError as error:
            location = "/".join(str(part) for part in error.errors(include_input=False)[0]["loc"])
            raise SupplementReadError("SUPPLEMENT_RULE_INVALID", path, location) from None
        except ParameterValidationError as error:
            raise SupplementReadError("SUPPLEMENT_RULE_INVALID", path, "parameters" + error.path) from None
        except InstructionMappingError:
            raise SupplementReadError("SUPPLEMENT_RULE_INVALID", path, "instruction_mapping") from None
        target = (rule.target_kind, rule.target_key)
        expected_directory = "rules/models/" if rule.target_kind == "model" else "rules/providers/"
        if not path.startswith(expected_directory):
            raise SupplementReadError("SUPPLEMENT_PATH_OWNERSHIP", path)
        if target in targets or rule.rule_id in entries:
            raise SupplementReadError("SUPPLEMENT_DUPLICATE", path)
        if rule.target_key not in available[rule.target_kind]:
            raise SupplementReadError("SUPPLEMENT_TARGET_MISSING", path)
        if rule.model_profile_key is not None and rule.model_profile_key not in sources.models:
            raise SupplementReadError("SUPPLEMENT_MODEL_MISSING", path)
        targets.add(target)
        normalized = rule.model_dump(mode="json", by_alias=True, exclude_unset=True)
        entries[rule.rule_id] = SupplementEntry(path, digest, _freeze(normalized))
        parts[path] = digest
    return SupplementCatalog(_revision(parts), SUPPLEMENT_SCHEMA_REF, _freeze(entries), sources.revision)
