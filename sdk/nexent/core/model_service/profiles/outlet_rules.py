# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Store rule constraints as explicit references to same-row control domains."""

import json
from typing import Mapping

from pydantic import ValidationError

from nexent.core.model_service.profiles.contracts import ReasoningCapabilities
from nexent.core.model_service.profiles.parameter_rules import (
    CompiledParameterRules,
    compile_parameter_rules,
    validate_saved_parameter_values,
)
from nexent.core.model_service.profiles.parameter_schema import _json_copy, json_values_equal


class RuleStorageError(ValueError):
    """A fixed storage diagnostic that never includes private constraint values."""

    def __init__(self):
        super().__init__("PROFILE_STORAGE_INVALID")


def _clone(value):
    try:
        copied = _json_copy(value)
        encoded = json.dumps(copied, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > 1024 * 1024:
            raise RuleStorageError()
        return copied
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise RuleStorageError() from None


def _domains(controls):
    try:
        reasoning = ReasoningCapabilities.model_validate({"controls": _clone(controls)})
    except (ValidationError, ValueError, TypeError):
        raise RuleStorageError() from None
    domains = {}
    for control in reasoning.controls or []:
        value = control.model_dump(mode="json")
        if control.mode in {"toggle", "effort"}:
            keywords = {"enum": value["values"]}
        else:
            keywords = {
                keyword: value[field]
                for keyword, field in (("minimum", "min"), ("maximum", "max"))
                if value[field] is not None
            }
        domains[control.parameter_key] = (control.mode, keywords)
    return domains


def store_parameter_rules(
    compiled: CompiledParameterRules,
    *,
    reasoning_controls: object,
    saved_values: Mapping[str, object],
) -> list[dict]:
    """Remove only exact duplicate domain/fixed values, preserving extra constraints."""
    try:
        saved = validate_saved_parameter_values(compiled, saved_values)
        rules = _clone(compiled.declarations)
        domains = _domains(reasoning_controls)
        for rule in rules:
            key = rule["key"]
            if key in domains:
                mode, domain = domains[key]
                keywords = sorted(
                    keyword
                    for keyword, value in domain.items()
                    if keyword in rule["schema"] and json_values_equal(rule["schema"][keyword], value)
                )
                if keywords:
                    rule["value_domain_ref"] = {"mode": mode, "keywords": keywords}
                    for keyword in keywords:
                        del rule["schema"][keyword]
            if "fixed_value" in rule and key in saved:
                rule.pop("fixed_value")
                rule["fixed_to_saved_value"] = True
        return _clone(rules)
    except (ValueError, TypeError, KeyError, AttributeError):
        raise RuleStorageError() from None


def restore_parameter_rules(
    declarations: object,
    *,
    reasoning_controls: object,
    saved_values: Mapping[str, object],
) -> CompiledParameterRules:
    """Restore constraints from row-owned domains; never apply creation defaults."""
    try:
        rules, saved = _clone(declarations), _clone(saved_values)
        if not isinstance(rules, list) or not isinstance(saved, dict):
            raise RuleStorageError()
        domains = _domains(reasoning_controls)
        for rule in rules:
            if not isinstance(rule, dict) or not isinstance(rule.get("schema"), dict):
                raise RuleStorageError()
            key = rule.get("key")
            has_reference = "value_domain_ref" in rule
            reference = rule.pop("value_domain_ref", None)
            if has_reference:
                if not isinstance(reference, dict) or set(reference) != {"mode", "keywords"} or key not in domains:
                    raise RuleStorageError()
                mode, domain = domains[key]
                keywords = reference["keywords"]
                if (
                    reference["mode"] != mode
                    or not isinstance(keywords, list)
                    or not keywords
                    or any(type(word) is not str for word in keywords)
                    or len(set(keywords)) != len(keywords)
                    or not set(keywords) <= domain.keys()
                    or set(keywords) & rule["schema"].keys()
                ):
                    raise RuleStorageError()
                for keyword in keywords:
                    rule["schema"][keyword] = domain[keyword]
            if "fixed_to_saved_value" in rule:
                if rule.pop("fixed_to_saved_value") is not True or "fixed_value" in rule or key not in saved:
                    raise RuleStorageError()
                rule["fixed_value"] = saved[key]
        compiled = compile_parameter_rules(_clone(rules))
        validate_saved_parameter_values(compiled, saved)
        return compiled
    except (ValueError, TypeError, KeyError):
        raise RuleStorageError() from None
