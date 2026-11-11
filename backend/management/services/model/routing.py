# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Task routing for multi-model agent runs.

Classifies each run (intent, risk, size) and selects the best matching
model from the agent's configured model pool.  Designed for deployments
where different tiers of model capacity (quick QA / long context / deep
reasoning) serve different request classes, while keeping every routing
decision auditable.

Design contract:
1. Opt-in: routing runs only when ``MODEL_ROUTING_ENABLED`` is true.
2. Explicit request-level model selection always wins; routing never
   overrides a caller-pinned model.
3. Routing only selects from the agent's own configured model pool that
   the tenant already validated.
4. Domain knowledge (medical terms, task tags) lives in a configurable
   rules JSON; this module is domain-agnostic.
5. When routing has no usable signal or no capable candidate, it returns
   None and the caller keeps the pre-routing selection behavior.

Layers:
1. classify  - rule engine over the user query and run parameters.
2. rank      - capability-based scoring of candidate model records.
3. fallback  - tier relaxation when a tier has no available model.
"""

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RouteTier(str, Enum):
    """Model service tiers a run can be routed to."""

    QUICK_QA = "quick_qa"
    LONG_CONTEXT = "long_context"
    DEEP_REASONING = "deep_reasoning"


class IntentSource(str, Enum):
    """Where the routing intent came from - the audit trail anchor."""

    EXPLICIT_TAG = "explicit_tag"  # rules file task-tag vocabulary
    RULE = "rule"                  # rule engine matched the query
    DEFAULT = "default"            # no signal matched


class RiskLevel(str, Enum):
    """Risk classes; high-risk runs are flagged for downstream review."""

    ROUTINE = "routine"
    HIGH = "high"


# Relaxation order when a tier has no capable model: quick QA falls up to
# long context first (capacity is a superset), everything else falls up to
# deep reasoning (strongest model absorbs).
_TIER_RELAXATION = {
    RouteTier.QUICK_QA: RouteTier.LONG_CONTEXT,
    RouteTier.LONG_CONTEXT: RouteTier.DEEP_REASONING,
    RouteTier.DEEP_REASONING: None,
}

_DEFAULT_RULES: Dict[str, Any] = {
    "long_context": {"token_threshold": 24000, "char_threshold": 8000, "terms": []},
    "quick_qa": {"char_limit": 120, "terms": []},
    "deep_reasoning": {"terms": []},
    "risk": {"high_terms": [], "review_terms": []},
    "task_tags": {},
    "history_tokens_per_turn": 200,
    "attachment_tokens": 800,
}

# ---------------------------------------------------------------------------
# Rules loading (file-based, thread-safe, degrade gracefully)
# ---------------------------------------------------------------------------

_rules_lock = threading.Lock()
_rules_cache: Optional[Dict[str, Any]] = None
_rules_loaded_from: Optional[str] = None


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge override into base (new dicts, no input mutation)."""

    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_rules(force_reload: bool = False) -> Dict[str, Any]:
    """Load routing rules from ``MODEL_ROUTING_RULES_JSON_PATH``.

    Missing or malformed files degrade to built-in defaults (empty
    vocabularies); loading never raises so the run path stays safe.
    """

    global _rules_cache, _rules_loaded_from
    with _rules_lock:
        if _rules_cache is not None and not force_reload:
            return _rules_cache
        from contracts.constants.environment import MODEL_ROUTING_RULES_JSON_PATH

        rules = _DEFAULT_RULES
        path = MODEL_ROUTING_RULES_JSON_PATH
        try:
            if path and os.path.exists(path):
                with open(path, encoding="utf-8") as handle:
                    raw = json.load(handle)
                if isinstance(raw, dict):
                    rules = _deep_merge(_DEFAULT_RULES, raw)
                    _rules_loaded_from = path
        except (OSError, ValueError) as exc:
            logger.warning("Model routing rules unavailable (%s); using defaults", exc)
            rules = _DEFAULT_RULES
        _rules_cache = rules
        return rules


def reset_rules_cache() -> None:
    """Drop the cached rules (used by tests and config reloads)."""

    global _rules_cache, _rules_loaded_from
    with _rules_lock:
        _rules_cache = None
        _rules_loaded_from = None


# ---------------------------------------------------------------------------
# Data carriers
# ---------------------------------------------------------------------------


@dataclass
class ClassificationResult:
    """Outcome of the rule engine; every field lands in the audit log."""

    tier: RouteTier
    source: IntentSource
    risk: RiskLevel
    review_required: bool
    est_tokens: int
    matched_rules: List[str] = field(default_factory=list)
    features: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RoutingDecision:
    """Full routing decision for one run - the audit record itself."""

    agent_id: Optional[int]
    tier: RouteTier
    source: IntentSource
    risk: RiskLevel
    review_required: bool
    est_tokens: int
    matched_rules: List[str]
    selected_model_id: Optional[int]
    selected_display_name: str
    candidates: List[Dict[str, Any]]
    reason: str
    fallback_from: Optional[RouteTier] = None

    def to_audit_dict(self) -> Dict[str, Any]:
        """Serialize for structured logging (no secrets)."""

        return {
            "agent_id": self.agent_id,
            "tier": self.tier.value,
            "source": self.source.value,
            "risk": self.risk.value,
            "review_required": self.review_required,
            "est_tokens": self.est_tokens,
            "matched_rules": list(self.matched_rules),
            "selected_model_id": self.selected_model_id,
            "selected_display_name": self.selected_display_name,
            "candidates": [dict(candidate) for candidate in self.candidates],
            "reason": self.reason,
            "fallback_from": self.fallback_from.value if self.fallback_from else None,
        }


# ---------------------------------------------------------------------------
# Classification (rule engine)
# ---------------------------------------------------------------------------


def estimate_tokens(
    text: str,
    history_length: int = 0,
    has_attachments: bool = False,
    rules: Optional[Dict[str, Any]] = None,
) -> int:
    """Cheap conservative token estimate.

    CJK ~1 token/char, other ~4 chars/token; history and attachments add
    configured per-turn / per-attachment overhead.
    """

    rules = rules or load_rules()
    if not text:
        text = ""
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
    other = len(text) - cjk
    base = cjk + (other + 3) // 4
    per_turn = rules.get("history_tokens_per_turn", 200)
    per_attachment = rules.get("attachment_tokens", 800)
    return base + history_length * per_turn + (per_attachment if has_attachments else 0)


def _contains_term(text: str, terms) -> List[str]:
    """Return terms present in the text (case-insensitive substring)."""

    lowered = text.lower()
    return [term for term in terms if term in lowered]


def _tier_terms(rules: Dict[str, Any], tier: RouteTier) -> List[str]:
    section = rules.get(tier.value) or {}
    terms = section.get("terms") or []
    return [str(term) for term in terms if term]


def classify_run(
    query: str,
    history_length: int = 0,
    agent_meta: Optional[Dict[str, Any]] = None,
    has_attachments: bool = False,
    rules: Optional[Dict[str, Any]] = None,
) -> ClassificationResult:
    """Classify a run into a service tier using auditable rules.

    Priority: explicit task tag > risk-escalated analysis > long context >
    deep reasoning > quick QA > default.  Long context wins over deep
    reasoning when both match, because truncation is a harder failure than
    a weaker reasoning model.  With empty vocabularies every query lands
    on the default branch, which callers treat as "keep existing selection".
    """

    rules = rules or load_rules()
    text = query or ""
    features: Dict[str, Any] = {}
    matched: List[str] = []
    est_tokens = estimate_tokens(
        text, history_length=history_length, has_attachments=has_attachments, rules=rules
    )
    features["est_tokens"] = est_tokens
    features["query_chars"] = len(text)
    features["history_length"] = history_length
    features["has_attachments"] = has_attachments

    meta = agent_meta or {}
    task_tag = str(meta.get("task_tag") or "").strip().lower()
    if task_tag:
        features["task_tag"] = task_tag

    # 1. Explicit task tag wins outright (vocabulary from the rules file).
    tag_map = rules.get("task_tags") or {}
    if task_tag and task_tag in tag_map:
        try:
            tier = RouteTier(tag_map[task_tag])
        except ValueError:
            tier = None
        if tier is not None:
            matched.append(f"task_tag:{task_tag}")
            risk, review = _assess_risk(text, rules)
            return ClassificationResult(
                tier=tier,
                source=IntentSource.EXPLICIT_TAG,
                risk=risk,
                review_required=review,
                est_tokens=est_tokens,
                matched_rules=matched,
                features=features,
            )

    # 2. Rule engine over query vocabulary and size.
    long_section = rules.get("long_context") or {}
    quick_section = rules.get("quick_qa") or {}
    long_hits = _contains_term(text, _tier_terms(rules, RouteTier.LONG_CONTEXT))
    deep_hits = _contains_term(text, _tier_terms(rules, RouteTier.DEEP_REASONING))
    quick_hits = _contains_term(text, _tier_terms(rules, RouteTier.QUICK_QA))
    risk, review = _assess_risk(text, rules)

    token_threshold = int(long_section.get("token_threshold") or 0)
    char_threshold = int(long_section.get("char_threshold") or 0)
    quick_char_limit = int(quick_section.get("char_limit") or 0)
    is_long = (
        (token_threshold and est_tokens >= token_threshold)
        or (char_threshold and len(text) >= char_threshold)
    )
    if is_long:
        matched.append("long_context:size")
    matched.extend(f"long_context:{term}" for term in long_hits)
    matched.extend(f"deep:{term}" for term in deep_hits)
    matched.extend(f"quick:{term}" for term in quick_hits)

    if risk is RiskLevel.HIGH and deep_hits:
        # High risk + analysis -> strongest tier, always review.
        matched.append("risk:escalate_deep")
        return ClassificationResult(
            tier=RouteTier.DEEP_REASONING,
            source=IntentSource.RULE,
            risk=risk,
            review_required=True,
            est_tokens=est_tokens,
            matched_rules=matched,
            features=features,
        )

    if is_long or long_hits:
        return ClassificationResult(
            tier=RouteTier.LONG_CONTEXT,
            source=IntentSource.RULE,
            risk=risk,
            review_required=review,
            est_tokens=est_tokens,
            matched_rules=matched,
            features=features,
        )

    if deep_hits:
        return ClassificationResult(
            tier=RouteTier.DEEP_REASONING,
            source=IntentSource.RULE,
            risk=risk,
            review_required=review,
            est_tokens=est_tokens,
            matched_rules=matched,
            features=features,
        )

    if text.strip() and (quick_hits or (quick_char_limit and len(text) <= quick_char_limit)):
        matched.append("quick:short_or_lookup")
        return ClassificationResult(
            tier=RouteTier.QUICK_QA,
            source=IntentSource.RULE,
            risk=risk,
            review_required=review,
            est_tokens=est_tokens,
            matched_rules=matched,
            features=features,
        )

    # 3. No signal matched - explicitly signal "no routing decision" so the
    # caller keeps the pre-routing selection (contract: routing never
    # silently changes the model when it has no evidence).
    return ClassificationResult(
        tier=RouteTier.QUICK_QA,
        source=IntentSource.DEFAULT,
        risk=risk,
        review_required=review,
        est_tokens=est_tokens,
        matched_rules=matched,
        features=features,
    )


def _assess_risk(text: str, rules: Dict[str, Any]) -> Tuple[RiskLevel, bool]:
    """Risk assessment from configured vocabularies."""

    risk_section = rules.get("risk") or {}
    hits = _contains_term(text, risk_section.get("high_terms") or [])
    if not hits:
        return RiskLevel.ROUTINE, False
    review = bool(_contains_term(text, risk_section.get("review_terms") or []))
    return RiskLevel.HIGH, review


# ---------------------------------------------------------------------------
# Candidate ranking
# ---------------------------------------------------------------------------


def _record_bool(record: Dict[str, Any], key: str) -> bool:
    value = record.get(key)
    return bool(value) if value is not None else False


def _record_int(record: Dict[str, Any], key: str) -> Optional[int]:
    value = record.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def record_capacity(record: Dict[str, Any]) -> int:
    """Input capacity of a record (0 = unknown/unlimited).

    Uses the provider's hard input limit first and the combined window as
    a fallback; output reserve is handled by the existing context budget
    module, so routing only guards the input side.
    """

    input_limit = _record_int(record, "max_input_tokens") or 0
    if input_limit:
        return input_limit
    return _record_int(record, "context_window_tokens") or 0


def record_tier(record: Dict[str, Any]) -> RouteTier:
    """Derive a record's tier from saved capability columns.

    Uses operator-verified facts already stored on ``model_record_t``
    (reasoning flags, context capacity, name) so routing needs no extra
    configuration.  Priority: reasoning capability -> context capacity ->
    name heuristics -> quick QA.
    """

    if _record_bool(record, "reasoning_supported") or _record_bool(record, "enable_thinking"):
        return RouteTier.DEEP_REASONING
    if record_capacity(record) >= 48000:
        return RouteTier.LONG_CONTEXT
    name = str(record.get("model_name") or record.get("display_name") or "").lower()
    if (
        "reason" in name
        or "think" in name
        or "-r1" in name
        or "o1" in name
        or "o3" in name
        or "r1" in name.split("-")
    ):
        return RouteTier.DEEP_REASONING
    if "long" in name or "long-context" in name:
        return RouteTier.LONG_CONTEXT
    return RouteTier.QUICK_QA


def score_candidate(record: Dict[str, Any], result: ClassificationResult) -> float:
    """Score one candidate record for the classified tier; higher is better.

    Records of a different tier score -1 (ineligible).  Records whose
    known capacity cannot hold the estimated tokens are hard-rejected so
    routing never selects a model that would truncate the request.
    """

    if record_tier(record) is not result.tier:
        return -1.0
    capacity = record_capacity(record)
    if capacity and result.est_tokens > capacity:
        return -1.0
    score = 1.0
    if capacity and result.est_tokens:
        headroom = capacity / max(result.est_tokens, 1)
        score += min(headroom / 8.0, 0.5)
    if result.tier is RouteTier.DEEP_REASONING and _record_bool(record, "enable_thinking"):
        score += 0.2
    return score


def rank_candidates(
    records: List[Dict[str, Any]],
    result: ClassificationResult,
) -> Tuple[List[Tuple[Dict[str, Any], float]], Optional[RouteTier]]:
    """Rank records for the classified tier, best first.

    Returns ``(ranked, fallback_from)``.  Only positive scores qualify.
    When no record matches the tier, relax along ``_TIER_RELAXATION``;
    ``fallback_from`` records the tier the request was demoted from
    (None when the primary tier was served).
    """

    ranked = _rank_for_tier(records, result.tier, result)
    if ranked:
        return ranked, None

    relaxed = _TIER_RELAXATION.get(result.tier)
    if relaxed is None:
        return [], None
    relaxed_ranked = _rank_for_tier(records, relaxed, result)
    if relaxed_ranked:
        return relaxed_ranked, result.tier
    return [], None


def _rank_for_tier(
    records: List[Dict[str, Any]],
    tier: RouteTier,
    result: ClassificationResult,
) -> List[Tuple[Dict[str, Any], float]]:
    """Score records against one explicit tier, positives only, desc."""

    tier_result = ClassificationResult(
        tier=tier,
        source=result.source,
        risk=result.risk,
        review_required=result.review_required,
        est_tokens=result.est_tokens,
        matched_rules=result.matched_rules,
        features=result.features,
    )
    scored = sorted(
        ((record, score_candidate(record, tier_result)) for record in records),
        key=lambda pair: pair[1],
        reverse=True,
    )
    return [pair for pair in scored if pair[1] > 0]


# ---------------------------------------------------------------------------
# Entry point used by run preparation
# ---------------------------------------------------------------------------


def route_model_selection(
    records: List[Dict[str, Any]],
    query: str,
    history_length: int = 0,
    agent_meta: Optional[Dict[str, Any]] = None,
    has_attachments: bool = False,
    agent_id: Optional[int] = None,
) -> Optional[Tuple[Dict[str, Any], RoutingDecision]]:
    """Pick the best record for this run from the agent's model pool.

    ``records`` are agent-configured, availability-validated model records.
    Returns ``(record, decision)`` or None when routing has no usable
    signal (default-tier classification, no capable candidate, exhausted
    relaxation) - callers keep their existing selection behavior then.
    """

    if not records:
        return None
    result = classify_run(
        query=query,
        history_length=history_length,
        agent_meta=agent_meta,
        has_attachments=has_attachments,
    )
    # Contract: no routing evidence -> keep the existing selection.
    if result.source is IntentSource.DEFAULT:
        return None
    ranked, fallback_from = rank_candidates(records, result)
    if not ranked:
        logger.info(
            "Model routing found no capable candidate (tier=%s rules=%s); keeping default selection",
            result.tier.value,
            result.matched_rules,
        )
        return None
    best_record = ranked[0][0]
    decision = RoutingDecision(
        agent_id=agent_id,
        tier=result.tier,
        source=result.source,
        risk=result.risk,
        review_required=result.review_required,
        est_tokens=result.est_tokens,
        matched_rules=list(result.matched_rules) + (
            [f"relax:{fallback_from.value}"] if fallback_from else []
        ),
        selected_model_id=_record_int(best_record, "model_id"),
        selected_display_name=str(
            best_record.get("display_name") or best_record.get("model_name") or ""
        ),
        candidates=[
            {
                "model_id": _record_int(record, "model_id"),
                "display_name": str(
                    record.get("display_name") or record.get("model_name") or ""
                ),
                "tier": record_tier(record).value,
                "score": round(score, 3),
            }
            for record, score in ranked
        ],
        reason=f"tier={result.tier.value} source={result.source.value}",
        fallback_from=fallback_from,
    )
    logger.info("Model routing decision: %s", decision.to_audit_dict())
    return best_record, decision


__all__ = [
    "ClassificationResult",
    "IntentSource",
    "RiskLevel",
    "RouteTier",
    "RoutingDecision",
    "classify_run",
    "estimate_tokens",
    "load_rules",
    "rank_candidates",
    "record_capacity",
    "record_tier",
    "reset_rules_cache",
    "route_model_selection",
    "score_candidate",
]
