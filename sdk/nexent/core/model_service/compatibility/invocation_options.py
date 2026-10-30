# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Legacy call options validated against the saved outlet's declarations."""

from dataclasses import dataclass
from typing import Mapping

from nexent.core.model_service.profiles.parameter_rules import overlay_profile_parameters
from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError, json_values_equal
from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile
from nexent.core.models.capacity_budget import (
    CallerMaxTokensOverrideForbidden,
    ContextBudgetSnapshot,
    parse_context_budget_snapshot,
    verify_context_budget_capacity,
)


@dataclass(frozen=True)
class LegacyInvocationOptions:
    """Interface aliases only; no provider defaults or unregistered API fields."""

    parameters: Mapping[str, object]
    stop_sequences: object = None
    response_format: object = None
    context_budget_snapshot: object = None
    capacity_snapshot: object = None
    custom_overrides: Mapping[str, object] | None = None

    def resolve(self, profile: ResolvedModelProfile) -> ResolvedModelProfile:
        submitted = dict(self.parameters)
        for key, value in (("stop", self.stop_sequences), ("response_format", self.response_format)):
            if value is None:
                continue
            if key in submitted and not json_values_equal(submitted[key], value):
                raise ParameterValidationError("LEGACY_PARAMETER_CONFLICT", "/" + key)
            submitted[key] = value
        declared = {rule["key"] for rule in profile.parameter_rules}
        # Old clients use these values to express omission, not new API fields.
        if submitted.get("enable_thinking") is False and "enable_thinking" not in declared:
            submitted.pop("enable_thinking")
        if submitted.get("reasoning_effort") == "auto" and "reasoning_effort" not in declared:
            submitted.pop("reasoning_effort")
        output_keys = {rule["key"] for rule in profile.parameter_rules if rule.get("api_binding")} & {
            "max_tokens", "max_output_tokens",
        }
        if "max_tokens" in submitted and output_keys == {"max_output_tokens"}:
            value = submitted.pop("max_tokens")
            if "max_output_tokens" in submitted and not json_values_equal(submitted["max_output_tokens"], value):
                raise ParameterValidationError("LEGACY_PARAMETER_CONFLICT", "/max_output_tokens")
            submitted["max_output_tokens"] = value
        if self.context_budget_snapshot is not None:
            if not isinstance(self.context_budget_snapshot, (dict, ContextBudgetSnapshot)):
                raise TypeError("context_budget_snapshot must be a ContextBudgetSnapshot or dict")
            budget = parse_context_budget_snapshot(self.context_budget_snapshot)
            verify_context_budget_capacity(budget_snapshot=budget, capacity_snapshot=self.capacity_snapshot)
            verify_context_budget_capacity(budget_snapshot=budget, capacity_snapshot={
                "provider": profile.identity.provider_id, "model_name": profile.identity.request_model_id,
            })
            if len(output_keys) != 1:
                raise ParameterValidationError("LEGACY_OUTPUT_BINDING_REQUIRED")
            key = next(iter(output_keys))
            if submitted.get(key) is not None and not json_values_equal(submitted[key], budget.requested_output_tokens):
                raise CallerMaxTokensOverrideForbidden(
                    snapshot_value=budget.requested_output_tokens, caller_value=submitted[key],
                )
            submitted[key] = budget.requested_output_tokens
        resolved = overlay_profile_parameters(profile, submitted, scope="outlet") if submitted else profile
        if self.custom_overrides is not None:
            from nexent.core.model_service.profiles.request_parameters import overlay_extra_api_parameters
            snapshot = resolved.model_dump(mode="json")
            snapshot["extra_api_parameters"] = overlay_extra_api_parameters(resolved, self.custom_overrides)
            return ResolvedModelProfile.model_validate(snapshot)
        return resolved
