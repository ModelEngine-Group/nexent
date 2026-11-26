# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Legacy call options validated against the saved outlet's declarations."""

from dataclasses import dataclass
from typing import Mapping

from nexent.core.model_service.profiles.parameter_rules import overlay_profile_parameters
from nexent.core.model_service.profiles.parameter_schema import ParameterValidationError, json_values_equal, validate_sampling_parameters
from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile
from nexent.core.models.sampling import without_unset_sampling
from nexent.core.models.capacity_budget import (
    CallerMaxTokensOverrideForbidden as CallerMaxTokensOverrideForbidden,
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
        from nexent.core.model_service.profiles.outlet_controls import ensure_outlet_parameter_rules

        profile = ensure_outlet_parameter_rules(profile)
        submitted = {key: value for key, value in self.parameters.items()
                     if key not in {"max_tokens", "max_completion_tokens", "max_output_tokens"}}
        submitted = without_unset_sampling(submitted)
        validate_sampling_parameters(submitted)
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
        if self.context_budget_snapshot is not None:
            if not isinstance(self.context_budget_snapshot, (dict, ContextBudgetSnapshot)):
                raise TypeError("context_budget_snapshot must be a ContextBudgetSnapshot or dict")
            budget = parse_context_budget_snapshot(self.context_budget_snapshot)
            verify_context_budget_capacity(budget_snapshot=budget, capacity_snapshot=self.capacity_snapshot)
            verify_context_budget_capacity(budget_snapshot=budget, capacity_snapshot={
                "provider": profile.identity.provider_id, "model_name": profile.identity.request_model_id,
            })
        resolved = overlay_profile_parameters(profile, submitted, scope="outlet") if submitted else profile
        if self.custom_overrides is not None:
            from nexent.core.model_service.profiles.request_parameters import overlay_extra_api_parameters
            snapshot = resolved.model_dump(mode="json")
            snapshot["extra_api_parameters"] = overlay_extra_api_parameters(resolved, self.custom_overrides)
            return ResolvedModelProfile.model_validate(snapshot)
        return resolved
