# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Code-owned source conversion; submission checks live outside the runtime path."""

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Mapping

from nexent.core.model_service.profiles._models_dev.inheritance import EffectiveSourceModel, FieldOrigin
from nexent.core.model_service.profiles._models_dev.reader import SourceDocument, _freeze


@dataclass(frozen=True)
class SourceMappingRule:
    source_kind: str
    source_path: str
    target_path: str
    transform_ref: str = "identity_v1"
    missing_policy: str = "omit"

    @property
    def rule_id(self):
        return self.source_kind + "." + self.source_path

    rule_version = 1


@dataclass(frozen=True)
class SourceMappingRegistry:
    rules: tuple[SourceMappingRule, ...]
    mapping_id: str = "models_dev_source_v1"
    mapping_version: int = 1


# Common model facts are shared by base and hosted model definitions.
_COMMON = (
    ('name', '/identity/name'),
    ('description', '/identity/description'),
    ('family', '/identity/family'),
    ('attachment', '/reference_metadata/attachment'),
    ('reasoning', '/reasoning/status', 'boolean_capability_v1', 'unknown'),
    ('tool_call', '/tools/status', 'boolean_capability_v1', 'unknown'),
    ('structured_output', '/structured_output/status', 'boolean_capability_v1', 'unknown'),
    ('temperature', '/sampling/temperature/status', 'boolean_capability_v1', 'unknown'),
    ('open_weights', '/reference_metadata/open_weights'),
    ('knowledge', '/reference_metadata/knowledge'),
    ('release_date', '/reference_metadata/release_date'),
    ('last_updated', '/reference_metadata/last_updated'),
    ('modalities', '/modalities'),
    ('modalities.input', '/modalities/input'),
    ('modalities.input[]', '/modalities/input[]'),
    ('modalities.output', '/modalities/output'),
    ('modalities.output[]', '/modalities/output[]'),
    ('limit', '/reference_metadata/limit'),
    ('limit.context', '/context/combined_window', 'zero_unknown_tokens_v1', 'unknown'),
    ('limit.input', '/context/input_limit', 'zero_unknown_tokens_v1', 'unknown'),
    ('limit.output', '/context/output_limit', 'zero_unknown_tokens_v1', 'unknown'),
)


def _rules():
    for kind in ("model", "provider_model"):
        for fields in _COMMON:
            yield SourceMappingRule(kind, *fields)
    yield SourceMappingRule('provider', 'name', '/identity/name')
    yield SourceMappingRule('provider', 'api', '/connection_suggestions/base_url')
    yield SourceMappingRule('provider_model', 'reasoning_options', '/reasoning/control_candidates')
    yield SourceMappingRule('provider_model', 'reasoning_options[]', '/reasoning/control_candidates[]')
    yield SourceMappingRule('provider_model', 'reasoning_options[].type', '/reasoning/control_candidates[]/type')
    yield SourceMappingRule('provider_model', 'reasoning_options[].values', '/reasoning/control_candidates[]/values')
    yield SourceMappingRule('provider_model', 'reasoning_options[].values[]', '/reasoning/control_candidates[]/values[]')
    yield SourceMappingRule('provider_model', 'reasoning_options[].min', '/reasoning/control_candidates[]/min')
    yield SourceMappingRule('provider_model', 'reasoning_options[].max', '/reasoning/control_candidates[]/max')


SOURCE_MAPPING = SourceMappingRegistry(tuple(_rules()))


def mapping_fingerprint(registry):
    return hashlib.sha256(json.dumps(asdict(registry), sort_keys=True).encode()).hexdigest()


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



def _leaves(value: object, path: str = ""):
    if isinstance(value, Mapping) and value:
        for key, item in value.items():
            yield from _leaves(item, f"{path}.{key}" if path else key)
    elif isinstance(value, (tuple, list)) and value:
        for index, item in enumerate(value):
            yield from _leaves(item, f"{path}[{index}]")
    elif path:
        yield path, value



def map_source_fields(source, registry=SOURCE_MAPPING) -> MappedSourceFields:
    """Convert checked source facts; unconsumed fields stay isolated as reference data."""
    document = source.document if isinstance(source, EffectiveSourceModel) else source
    rules = {rule.source_path: rule for rule in registry.rules if rule.source_kind == document.kind}
    values, origins = {}, {}
    for path, value in _leaves(source.data):
        pattern = re.sub(r"\[\d+\]", "[]", path)
        rule = rules.get(pattern)
        if rule is None:
            target = "/reference_metadata/" + re.sub(r"\[(\d+)\]", r"/\1", path).replace(".", "/")
            rule = SourceMappingRule(document.kind, pattern, target)
        indexes = iter(re.findall(r"\[(\d+)\]", path))
        target = re.sub(r"\[\]", lambda _: "/" + next(indexes), rule.target_path)
        if rule.transform_ref == "boolean_capability_v1":
            value = "supported" if value else "unsupported"
        elif rule.transform_ref == "zero_unknown_tokens_v1" and value == 0:
            value = None
        values[target] = value
        origins[target] = MappedFieldOrigin(
            source.field_origins[path] if isinstance(source, EffectiveSourceModel)
            else FieldOrigin(document.kind, document.file_path, path, document.content_sha256),
            rule.rule_id, rule.rule_version, target,
        )
    for rule in rules.values():
        if "[]" not in rule.source_path and rule.missing_policy == "unknown" and rule.target_path not in values:
            values[rule.target_path] = "unknown" if rule.transform_ref == "boolean_capability_v1" else None
    return MappedSourceFields(source, registry.mapping_id, registry.mapping_version, _freeze(values), _freeze(origins))
