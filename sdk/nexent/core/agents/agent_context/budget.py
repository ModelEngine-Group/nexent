"""Budget estimation, trimming, and pure data helpers for ContextManager."""

import hashlib
import logging
from typing import Callable, List, Optional, Tuple

from smolagents.memory import ActionStep, MemoryStep, TaskStep

from ...utils.token_estimation import estimate_tokens_text
from ..summary_cache import PreviousSummaryCache, CurrentSummaryCache
from .summary_step import SummaryTaskStep

logger = logging.getLogger("agent_context.budget")


# ============================================================
#  Pure data helpers (no dependencies beyond stdlib + types)
# ============================================================

def extract_pairs(steps: List[MemoryStep]) -> List[tuple]:
    """Extract (TaskStep, ActionStep) pairs from a step list."""
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


def action_content(action: ActionStep) -> str:
    """Extract the output text from an ActionStep."""
    return action.action_output or getattr(action, "output", "") or ""


def pair_fingerprint(task_content: str, action_content: str) -> str:
    """Compute a fingerprint hash for a (task, action) pair."""
    raw = (task_content[-200:] + action_content[-200:])
    return hashlib.md5(raw.encode()).hexdigest()


def action_fingerprint(action: ActionStep) -> str:
    """Compute a fingerprint hash for an ActionStep."""
    raw = (
        str(action.step_number or "")
        + (action.model_output or "")[-200:]
        + (
            action.action_output if isinstance(action.action_output, str)
            else str(action.action_output) if action.action_output else ""
        )[-200:]
    )
    return hashlib.md5(raw.encode()).hexdigest()


def has_invoked_tools(action: ActionStep) -> bool:
    """Check whether an ActionStep invokes any registered tool.

    Unlike ``is_tool_call_step()`` which only checks for the generic
    ``tool_calls is not None`` (always True for CodeAgent steps), this
    function checks the ``invoked_tools`` list for actual tool names.

    Returns True only when the step's code called at least one tool
    that is registered in the agent's ``self.tools`` dict.
    """
    invoked = getattr(action, "invoked_tools", None)
    return bool(invoked)


def is_observation_step(action: ActionStep) -> bool:
    """Check if an ActionStep is an observation step."""
    return action is not None and hasattr(action, 'observations') and action.observations is not None


def is_tool_call_step(action: ActionStep) -> bool:
    """Check if an ActionStep is a tool call step."""
    return action is not None and hasattr(action, 'tool_calls') and action.tool_calls is not None


# ============================================================
#  Cache validation (depends on fingerprint functions, pure)
# ============================================================

def is_prev_cache_valid(
    prev_pairs: List[tuple], cache: Optional[PreviousSummaryCache],
) -> Tuple[bool, int]:
    """Check whether the previous cache covers a prefix of prev_pairs.

    Returns (is_valid, covered_idx). When is_valid is True,
    prev_pairs[0:covered_idx] can be replaced by cache.summary_text,
    and prev_pairs[covered_idx:] represents the uncovered incremental portion.
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
    action_steps: List[ActionStep], cache: Optional[CurrentSummaryCache],
) -> Tuple[bool, int]:
    """Check whether the current cache covers a prefix of action_steps."""
    if cache is None or not action_steps:
        return False, 0
    if cache.end_steps == 0 or cache.end_steps > len(action_steps):
        return False, 0
    anchor = action_steps[cache.end_steps - 1]
    if action_fingerprint(anchor) != cache.anchor_fingerprint:
        return False, 0
    return True, cache.end_steps


# ============================================================
#  Budget trimming (depends on render_fn for text conversion)
# ============================================================

def trim_pairs_to_budget(
    pairs: List[tuple], max_tokens: int,
    render_fn: Callable[[List[tuple]], str],
    keep_first: bool = True,
) -> List[tuple]:
    """Trim pairs to fit within a token budget.

    Args:
        pairs: List of (TaskStep, ActionStep) tuples.
        max_tokens: Maximum token budget.
        render_fn: Function to convert pairs to text (e.g. renderer.pairs_to_text).
        keep_first: If True, always keep the first pair.
    """
    if not pairs:
        return []
    pair_tokens = [
        estimate_tokens_text(render_fn([p])) for p in pairs
    ]
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
    actions: List[ActionStep], task_text: str, max_tokens: int,
    render_fn: Callable[[List[ActionStep]], str],
) -> List[ActionStep]:
    """Trim actions to fit within a token budget.

    Args:
        actions: List of ActionStep instances.
        task_text: Task description text.
        max_tokens: Maximum token budget.
        render_fn: Function to convert actions to text (e.g. renderer.actions_to_text).
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
    """Fallback trimming that preserves the last complete tool call pair."""
    if not actions:
        return []
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
