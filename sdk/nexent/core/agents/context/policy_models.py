"""Policy models and validation for non-memory context selection."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import reason_codes
from .context_item import AuthorityTier, ContextItemType, RepresentationTier


DEFAULT_POLICY_VERSION = "1.0"


def _default_enabled_item_types() -> Tuple[ContextItemType, ...]:
    """Return all context item types enabled by default.

    Memory remains enabled for backward compatibility, but the current policy
    phase does not add memory-specific routing, scoring, or reduction behavior.
    """

    return tuple(ContextItemType)


def _default_mandatory_item_types() -> Tuple[ContextItemType, ...]:
    """Return item types that must be preserved when present."""

    return (ContextItemType.SYSTEM_PROMPT,)


def _default_minimum_fidelity_by_type() -> Dict[ContextItemType, RepresentationTier]:
    """Return conservative minimum fidelity defaults for each item type."""

    return {
        ContextItemType.SYSTEM_PROMPT: RepresentationTier.FULL,
        ContextItemType.TOOL: RepresentationTier.STRUCTURED,
        ContextItemType.SKILL: RepresentationTier.STRUCTURED,
        ContextItemType.MEMORY: RepresentationTier.STRUCTURED,
        ContextItemType.KNOWLEDGE_BASE: RepresentationTier.COMPRESSED,
        ContextItemType.MANAGED_AGENT: RepresentationTier.STRUCTURED,
        ContextItemType.EXTERNAL_AGENT: RepresentationTier.STRUCTURED,
        ContextItemType.HISTORY_TURN: RepresentationTier.STRUCTURED,
        ContextItemType.TOOL_CALL_RESULT: RepresentationTier.STRUCTURED,
        ContextItemType.WORKING_MEMORY: RepresentationTier.STRUCTURED,
    }


def _default_authority_order() -> Tuple[AuthorityTier, ...]:
    """Return authority tiers from highest to lowest priority."""

    return (
        AuthorityTier.PLATFORM,
        AuthorityTier.TENANT,
        AuthorityTier.USER,
        AuthorityTier.WORKING_MEMORY,
        AuthorityTier.TOOL_RESULT,
        AuthorityTier.RETRIEVED_MEMORY,
        AuthorityTier.SUMMARY,
        AuthorityTier.AGENT_INFERENCE,
    )


@dataclass(frozen=True)
class ContextPolicy:
    """Immutable policy configuration for context item selection.

    This model intentionally excludes memory-operation routing. Memory-specific
    policy remains deferred until the memory module refactor lands.
    """

    policy_version: str = DEFAULT_POLICY_VERSION
    max_input_budget: Optional[int] = None
    mandatory_reserve_tokens: int = 0
    enabled_item_types: Tuple[ContextItemType, ...] = field(default_factory=_default_enabled_item_types)
    mandatory_item_types: Tuple[ContextItemType, ...] = field(default_factory=_default_mandatory_item_types)
    minimum_fidelity_by_type: Dict[ContextItemType, RepresentationTier] = field(
        default_factory=_default_minimum_fidelity_by_type
    )
    type_budget_allocations: Dict[ContextItemType, int] = field(default_factory=dict)
    authority_order: Tuple[AuthorityTier, ...] = field(default_factory=_default_authority_order)


class PolicyInvalidError(ValueError):
    """Raised when context policy configuration is invalid."""

    def __init__(self, message: str, reason_codes: Sequence[str]):
        super().__init__(message)
        self.reason_codes = list(reason_codes)


PolicyLayer = Optional[ContextPolicy | Mapping[str, Any]]


def resolve_policy(
    platform_default: PolicyLayer = None,
    tenant_config: PolicyLayer = None,
    agent_config: PolicyLayer = None,
    request_override: PolicyLayer = None,
) -> ContextPolicy:
    """Resolve layered policy configuration and validate the result.

    Later layers override earlier ones in this order: platform defaults, tenant
    config, agent config, request override.
    """

    merged: Dict[str, Any] = _policy_to_dict(ContextPolicy())
    for layer in (platform_default, tenant_config, agent_config, request_override):
        _merge_policy_layer(merged, _policy_to_dict(layer))

    policy = ContextPolicy(**_normalize_policy_values(merged))
    validate_policy(policy)
    return policy


def validate_policy(policy: ContextPolicy) -> None:
    """Validate policy consistency and raise PolicyInvalidError on failure."""

    failures: List[str] = []

    if policy.max_input_budget is not None and policy.max_input_budget < 0:
        failures.append(reason_codes.POLICY_BUDGET_INVALID)

    if policy.mandatory_reserve_tokens < 0:
        failures.append(reason_codes.POLICY_BUDGET_INVALID)

    if any(budget < 0 for budget in policy.type_budget_allocations.values()):
        failures.append(reason_codes.POLICY_BUDGET_INVALID)

    if policy.max_input_budget is not None:
        allocated_budget = sum(policy.type_budget_allocations.values()) + policy.mandatory_reserve_tokens
        if allocated_budget > policy.max_input_budget:
            failures.append(reason_codes.POLICY_BUDGET_INVALID)

    enabled_types = set(policy.enabled_item_types)
    if any(not isinstance(item_type, ContextItemType) for item_type in policy.enabled_item_types):
        failures.append(reason_codes.POLICY_INVALID)

    if any(not isinstance(item_type, ContextItemType) for item_type in policy.mandatory_item_types):
        failures.append(reason_codes.POLICY_INVALID)

    if any(not isinstance(authority, AuthorityTier) for authority in policy.authority_order):
        failures.append(reason_codes.POLICY_INVALID)

    if any(item_type not in enabled_types for item_type in policy.mandatory_item_types):
        failures.append(reason_codes.POLICY_DISABLED_MANDATORY)

    if any(not isinstance(tier, RepresentationTier) for tier in policy.minimum_fidelity_by_type.values()):
        failures.append(reason_codes.POLICY_INVALID_REPRESENTATION)

    invalid_minimum_keys = [item_type for item_type in policy.minimum_fidelity_by_type if not isinstance(item_type, ContextItemType)]
    if invalid_minimum_keys:
        failures.append(reason_codes.POLICY_INVALID)

    if failures:
        unique_failures = list(dict.fromkeys(failures))
        raise PolicyInvalidError("Invalid context policy", unique_failures)


def _policy_to_dict(policy: PolicyLayer) -> Dict[str, Any]:
    """Convert a policy layer into a partial policy dictionary."""

    if policy is None:
        return {}

    if isinstance(policy, ContextPolicy):
        return {
            "policy_version": policy.policy_version,
            "max_input_budget": policy.max_input_budget,
            "mandatory_reserve_tokens": policy.mandatory_reserve_tokens,
            "enabled_item_types": policy.enabled_item_types,
            "mandatory_item_types": policy.mandatory_item_types,
            "minimum_fidelity_by_type": policy.minimum_fidelity_by_type,
            "type_budget_allocations": policy.type_budget_allocations,
            "authority_order": policy.authority_order,
        }

    return dict(policy)


def _merge_policy_layer(target: Dict[str, Any], layer: Mapping[str, Any]) -> None:
    """Merge one policy layer into the accumulated policy dictionary."""

    mapping_fields = {"minimum_fidelity_by_type", "type_budget_allocations"}
    for key, value in layer.items():
        if key in mapping_fields and isinstance(target.get(key), Mapping) and isinstance(value, Mapping):
            target[key] = {**target[key], **value}
        else:
            target[key] = value


def _normalize_policy_values(values: Mapping[str, Any]) -> Dict[str, Any]:
    """Normalize string enum values in a partial policy dictionary."""

    normalized = dict(values)

    if "enabled_item_types" in normalized:
        normalized["enabled_item_types"] = tuple(
            _coerce_enum(ContextItemType, item_type) for item_type in normalized["enabled_item_types"]
        )

    if "mandatory_item_types" in normalized:
        normalized["mandatory_item_types"] = tuple(
            _coerce_enum(ContextItemType, item_type) for item_type in normalized["mandatory_item_types"]
        )

    if "minimum_fidelity_by_type" in normalized:
        normalized["minimum_fidelity_by_type"] = {
            _coerce_enum(ContextItemType, item_type): _coerce_enum(RepresentationTier, tier)
            for item_type, tier in normalized["minimum_fidelity_by_type"].items()
        }

    if "type_budget_allocations" in normalized:
        normalized["type_budget_allocations"] = {
            _coerce_enum(ContextItemType, item_type): budget
            for item_type, budget in normalized["type_budget_allocations"].items()
        }

    if "authority_order" in normalized:
        normalized["authority_order"] = tuple(
            _coerce_enum(AuthorityTier, authority) for authority in normalized["authority_order"]
        )

    return normalized


def _coerce_enum(enum_type: type, value: Any) -> Any:
    """Coerce enum names or values into enum members."""

    if isinstance(value, enum_type):
        return value

    if isinstance(value, str):
        try:
            return enum_type[value]
        except KeyError:
            try:
                return enum_type(value)
            except ValueError:
                return value

    return value


@dataclass(frozen=True)
class SelectionDecision:
    """Immutable record of a context selection policy decision.

    Captures which items were selected or excluded, their representation
    requirements, budget allocations, and the reason codes explaining
    each decision.
    """

    selected_item_ids: List[str]
    excluded_item_ids: List[str]
    representation_requirements: Dict[str, RepresentationTier]
    budget_allocations: Dict[str, int]
    remaining_budget: int
    conflicts: List[Dict[str, Any]]
    reason_codes: List[str]
    policy_version: str
    decision_fingerprint: str


@dataclass(frozen=True)
class MemoryDecision:
    """Immutable record of a memory operation policy decision.

    Captures the allowed operation, scopes, excluded candidates,
    conflict resolutions, and any confirmation requirements.
    """

    operation: str
    allowed_scopes: List[str]
    excluded_candidates: List[str]
    conflict_decisions: List[Dict[str, Any]]
    confirmation_required: Optional[Dict[str, Any]]
    reason_codes: List[str]
