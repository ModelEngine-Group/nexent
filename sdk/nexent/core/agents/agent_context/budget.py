"""Pure data helpers: fingerprinting, cache validation, token-budget trimming,
and message utilities. No classes — entirely standalone functions."""

import hashlib
import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from smolagents.memory import ActionStep, TaskStep

from ..summary_cache import CurrentSummaryCache, PreviousSummaryCache
from ..summary_config import ContextManagerConfig
from ...utils.token_estimation import estimate_tokens_text

from .summary_step import SummaryTaskStep

logger = logging.getLogger("agent_context.budget")


# ── Output formatting ──────────────────────────────────────────

def format_summary_output(raw_output: str) -> Optional[str]:
    """Clean and validate LLM summary output.

    Strips markdown code fences, attempts JSON parse for normalization,
    falls back to plain text if not valid JSON.
    """
    cleaned = raw_output.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)
    if not cleaned:
        return None
    try:
        parsed = json.loads(cleaned)
        return json.dumps(parsed, ensure_ascii=False, indent=2)
    except json.JSONDecodeError:
        logger.warning("Summary output is not valid JSON; using as plain text")
        return cleaned


def _is_context_length_error(err: Exception) -> bool:
    """Check if an exception indicates a context length / token limit error."""
    msg = str(err).lower()
    return any(k in msg for k in (
        "context_length", "context length", "maximum context", "maximum context length",
        "prompt is too long", "reduce the length", "too many tokens",
        "token limit", "exceeds the maximum", "input is too long",
        "input length", "exceeds context", "context window",
    ))


# ── Pair extraction ────────────────────────────────────────────

def extract_pairs(steps) -> List[tuple]:
    """Walk a step list and extract (TaskStep, ActionStep) tuples, skipping SummaryTaskStep."""
    pairs = []
    i = 0
    while i < len(steps):
        if isinstance(steps[i], TaskStep) and not isinstance(steps[i], SummaryTaskStep):
            if i + 1 < len(steps) and isinstance(steps[i + 1], ActionStep):
                pairs.append((steps[i], steps[i + 1]))
                i += 2
                continue
        i += 1
    return pairs


# ── Content and fingerprinting ─────────────────────────────────

def action_content(action: ActionStep) -> str:
    """Extract the output text from an ActionStep."""
    return action.action_output or getattr(action, "output", "") or ""


def pair_fingerprint(task_content: str, action_content_text: str) -> str:
    """MD5 fingerprint for a (task, action) pair, used as cache anchor."""
    raw = (task_content[-200:] + action_content_text[-200:])
    return hashlib.md5(raw.encode()).hexdigest()


def action_fingerprint(action: ActionStep) -> str:
    """MD5 fingerprint for an ActionStep, used as cache anchor."""
    raw = (
        str(action.step_number or "")
        + (action.model_output or "")[-200:]
        + (
            action.action_output if isinstance(action.action_output, str)
            else str(action.action_output) if action.action_output else ""
        )[-200:]
    )
    return hashlib.md5(raw.encode()).hexdigest()


# ── Step type predicates ───────────────────────────────────────

def has_invoked_tools(action: ActionStep) -> bool:
    """Check whether an ActionStep has actual registered tool usage."""
    return action is not None and hasattr(action, 'invoked_tools') and action.invoked_tools is not None


def is_observation_step(action: ActionStep) -> bool:
    """Check whether an ActionStep is an observation step."""
    return action is not None and hasattr(action, 'observations') and action.observations is not None


def is_tool_call_step(action: ActionStep) -> bool:
    """Check whether an ActionStep is a tool call step."""
    return action is not None and hasattr(action, 'tool_calls') and action.tool_calls is not None


# ── Cache validation ───────────────────────────────────────────

def is_prev_cache_valid(
    prev_pairs: List[tuple],
    cache: Optional[PreviousSummaryCache],
) -> Tuple[bool, int]:
    """Check whether the previous cache covers a prefix of prev_pairs.

    Returns (is_valid, covered_idx). When is_valid is True, prev_pairs[0:covered_idx]
    can be replaced by cache.summary_text.
    """
    if cache is None or not prev_pairs:
        return False, 0
    if cache.covered_pairs == 0 or cache.covered_pairs > len(prev_pairs):
        return False, 0
    anchor_t, anchor_a = prev_pairs[cache.covered_pairs - 1]
    fp = pair_fingerprint(anchor_t.task or "", action_content(anchor_a))
    if fp != cache.anchor_fingerprint:
        return False, 0
    return True, cache.covered_pairs


def is_curr_cache_valid(
    action_steps: List[ActionStep],
    cache: Optional[CurrentSummaryCache],
) -> Tuple[bool, int]:
    """Check whether the current cache covers a prefix of action_steps.

    Returns (is_valid, covered_idx).
    """
    if cache is None or not action_steps:
        return False, 0
    if cache.end_steps == 0 or cache.end_steps > len(action_steps):
        return False, 0
    anchor = action_steps[cache.end_steps - 1]
    if action_fingerprint(anchor) != cache.anchor_fingerprint:
        return False, 0
    return True, cache.end_steps


# ── Budget trimming ────────────────────────────────────────────

def trim_pairs_to_budget(
    pairs: List[tuple],
    max_tokens: int,
    render_fn: Callable,
    keep_first: bool = True,
) -> List[tuple]:
    """Drop oldest pairs to fit a token budget, optionally always keeping the first pair.

    Args:
        render_fn: Callable that takes a list of pairs and returns text,
                   e.g. StepRenderer.pairs_to_text.
    """
    if not pairs:
        return []
    pair_tokens = [estimate_tokens_text(render_fn([p])) for p in pairs]
    sep = estimate_tokens_text("\n\n")
    total = sum(pair_tokens) + sep * max(0, len(pairs) - 1)
    if total <= max_tokens:
        return list(pairs)

    if keep_first and len(pairs) > 1:
        budget = max_tokens - pair_tokens[0] - sep
        kept_tail = []
        for i in range(len(pairs) - 1, 0, -1):
            cost = pair_tokens[i] + (sep if kept_tail else 0)
            if cost > budget:
                break
            kept_tail.append(pairs[i])
            budget -= cost
        return [pairs[0]] + list(reversed(kept_tail))

    budget = max_tokens
    kept = []
    for i in range(len(pairs) - 1, -1, -1):
        cost = pair_tokens[i] + (sep if kept else 0)
        if cost > budget:
            break
        kept.append(pairs[i])
        budget -= cost
    return list(reversed(kept)) if kept else [pairs[-1]]


def trim_actions_to_budget(
    actions: List[ActionStep],
    task_text: str,
    max_tokens: int,
    render_fn: Callable,
) -> List[ActionStep]:
    """Trim actions from the front, preserving complete tool-call/observation pairs.

    Args:
        render_fn: Callable that takes a list of actions and returns text,
                   e.g. StepRenderer.actions_to_text.
    """
    if not actions:
        return []

    def _total_tokens(acts):
        return estimate_tokens_text(task_text + render_fn(acts))

    if _total_tokens(actions) <= max_tokens:
        return list(actions)

    for drop in range(1, len(actions) + 1):
        remaining = actions[drop:]
        if not remaining:
            break
        if is_observation_step(remaining[0]) and is_tool_call_step(actions[drop - 1]):
            continue
        if _total_tokens(remaining) <= max_tokens:
            return list(remaining)

    return _fallback_trim_actions(actions)


def _fallback_trim_actions(actions: List[ActionStep]) -> List[ActionStep]:
    """Last-resort trim: keep the last complete ToolCall + Observation pair."""
    last_action = actions[-1]
    if len(actions) >= 2 and is_observation_step(last_action):
        prev_action = actions[-2]
        if is_tool_call_step(prev_action):
            logger.warning(
                "Fallback limit triggered: Retaining the last complete ToolCall + Observation pair intact. "
                "This may exceed the token budget, and downstream truncation will be relied upon."
            )
            return [prev_action, last_action]
    return [last_action]


# ── Message utilities ──────────────────────────────────────────

def extract_message_text(message: Any) -> str:
    """Extract plain text from a message dict or ChatMessage."""
    content = (
        message.get("content", "")
        if isinstance(message, dict)
        else getattr(message, "content", "")
    )
    if isinstance(content, list):
        return "".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict)
        )
    return "" if content is None else str(content)


def message_role(message: Any) -> Optional[str]:
    """Extract role from a message dict or ChatMessage."""
    if isinstance(message, dict):
        return message.get("role")
    role = getattr(message, "role", None)
    return getattr(role, "value", role)
