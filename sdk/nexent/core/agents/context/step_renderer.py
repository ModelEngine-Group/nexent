"""Step rendering, text transformation, and offline compression.

StepRenderer converts ActionStep/TaskStep/pair objects into plain text
suitable for LLM input, with budget-aware truncation.

compress_history_offline is a standalone function for benchmark use.
"""

import json
import logging
from typing import List, Optional, Tuple

from smolagents.memory import ActionStep, AgentMemory, MemoryStep
from smolagents.models import ChatMessage, MessageRole

from ...utils.token_estimation import (
    _extract_text_from_messages,
    estimate_tokens_text,
)
from .budget import format_summary_output
from .config import ContextManagerConfig
from .summary_step import SummaryTaskStep


logger = logging.getLogger("agent_context.step_renderer")


class StepRenderer:
    """Renders memory steps to text and assembles chat messages with budget-aware truncation."""

    def __init__(self, config: ContextManagerConfig):
        self.config = config

    # ── Core rendering ──────────────────────────────────────────

    def render_action_step(self, action: ActionStep) -> str:
        """Render an ActionStep to plain text."""
        msgs = action.to_messages(summary_mode=False)
        return _extract_text_from_messages(msgs) or ""

    def pairs_to_text(self, pairs: List[tuple]) -> str:
        """Render (TaskStep, ActionStep) pairs as user/assistant text."""
        parts = []
        for task_step, action_step in pairs:
            task_text = task_step.task or ""
            action_text = self.render_action_step(action_step)
            parts.append(f"user: {task_text}\nassistant: {action_text}")
        return "\n\n".join(parts)

    def actions_to_text(self, actions: List[ActionStep]) -> str:
        """Render a list of ActionSteps with [Step N] headers."""
        parts = []
        for i, step in enumerate(actions):
            text = self.render_action_step(step)
            parts.append(f"[Step {step.step_number or i+1}]\n{text}")
        return "\n\n".join(parts)

    def pairs_to_steps(self, pairs: List[tuple]) -> List[MemoryStep]:
        """Convert (TaskStep, ActionStep) pairs back to a flat step list."""
        steps = []
        for task_step, action_step in pairs:
            steps.append(task_step)
            steps.append(action_step)
        return steps

    # ── Budget-aware truncation ─────────────────────────────────

    def estimate_text_tokens(self, text: str) -> int:
        return estimate_tokens_text(text)

    def truncate_text_to_tokens(self, text: str, max_tokens: int) -> str:
        """Paragraph-level truncation preserving the newest content."""
        if max_tokens <= 0:
            return ""
        if self.estimate_text_tokens(text) <= max_tokens:
            return text
        units = text.split("\n\n")
        kept, total = [], 0
        for u in reversed(units):
            u_tokens = self.estimate_text_tokens(u)
            if total + u_tokens > max_tokens and kept:
                break
            kept.append(u)
            total += u_tokens
        result = "...[Earlier content truncated]...\n\n" + "\n\n".join(reversed(kept))
        if self.estimate_text_tokens(result) > max_tokens:
            approx_chars = int(max_tokens * self.config.chars_per_token * 0.9)
            result = "...[Earlier content truncated]...\n" + result[:approx_chars]
        return result

    def render_steps_with_truncation(
        self,
        steps: List,
        fmt: str = "action",
        max_tokens: int = None,
        min_budget_chars: int = 80,
        task_budget_chars: int = 800,
        action_budget_chars: int = None,
    ) -> str:
        if max_tokens is None:
            max_tokens = self.config.max_summary_input_tokens
        if action_budget_chars is None:
            action_budget_chars = self.config.max_memory_step_length

        entries = self._build_step_entries(steps, fmt)
        raw_text = "\n\n".join(task + action for task, action in entries)
        if self.estimate_text_tokens(raw_text) <= max_tokens:
            return raw_text

        return self._truncate_entries_to_budget(entries, max_tokens, min_budget_chars, task_budget_chars, action_budget_chars)

    def _build_step_entries(self, steps: List, fmt: str) -> List[Tuple[str, str]]:
        entries = []
        for step in steps:
            if fmt == "action":
                text = f"[Step {step.step_number or '?'}]\n{self.render_action_step(step)}"
                entries.append(("", text))
            else:
                task_step, action_step = step
                task_str = f"user: {task_step.task or ''}\nassistant: "
                action_str = self.render_action_step(action_step)
                entries.append((task_str, action_str))
        return entries

    def _truncate_entries_to_budget(
        self, entries: List[Tuple[str, str]], max_tokens: int,
        min_budget_chars: int, task_budget_chars: int, action_budget_chars: int,
    ) -> str:
        t_budget = task_budget_chars
        a_budget = action_budget_chars
        all_text = ""

        while True:
            parts = [self._truncate_entry(e, t_budget, a_budget) for e in entries]
            all_text = "\n\n".join(parts)

            if self.estimate_text_tokens(all_text) <= max_tokens:
                break

            t_budget, a_budget = self._reduce_budgets(t_budget, a_budget, min_budget_chars)
            if t_budget == min_budget_chars and a_budget == min_budget_chars:
                break

        return all_text

    def _truncate_entry(self, entry: Tuple[str, str], task_budget: int, action_budget: int) -> str:
        task_str, action_str = entry
        task_trunc = self._truncate_text(task_str, task_budget) if task_str else ""
        action_trunc = self._truncate_text(action_str, action_budget)
        return task_trunc + action_trunc

    def _truncate_text(self, text: str, max_len: int, mark: str = "...[Truncated]") -> str:
        if len(text) <= max_len:
            return text
        return text[:max_len - len(mark)] + mark

    def _reduce_budgets(self, t_budget: int, a_budget: int, min_budget: int) -> Tuple[int, int]:
        if a_budget > min_budget:
            return t_budget, max(min_budget, int(a_budget * 0.8))
        if t_budget > min_budget:
            return max(min_budget, int(t_budget * 0.8)), a_budget
        return t_budget, a_budget

    def _actions_to_text_with_limit(self, actions: List[ActionStep], prefill_tokens: int = 0) -> str:
        rendered_steps = []
        for i, step in enumerate(actions):
            prefix = f"[Step {step.step_number or i+1}]\n"
            content = self.render_action_step(step)
            rendered_steps.append((prefix, content))
        budget_per_action = self.config.max_memory_step_length

        while True:
            parts = []

            for prefix, content in rendered_steps:
                if len(content) > budget_per_action:
                    text = f"{prefix}{content[:budget_per_action]}\n\n[System Note: Step content too long, partially truncated]"
                else:
                    text = f"{prefix}{content}"
                parts.append(text)

            all_text = "\n\n".join(parts)

            if self.estimate_text_tokens(all_text) + prefill_tokens <= self.config.max_summary_input_tokens:
                break
            budget_per_action = int(budget_per_action * 0.9)

            if budget_per_action < 50:
                logger.warning(
                    f"Per-step compression budget has reached minimum threshold "
                    f"(budget={budget_per_action}), possibly due to excessively long preset prompts. "
                    f"Forcing return of truncated result."
                )
                break
        return all_text

    # ── Message assembly ────────────────────────────────────────

    def build_messages(
        self, memory: AgentMemory,
        prev_summary_step: Optional[SummaryTaskStep],
        prev_tail_steps: List[MemoryStep],
        curr_kept_steps: List[MemoryStep],
    ) -> List[ChatMessage]:
        """Assemble the final chat message list from system prompt, summary, tail, and kept steps."""
        result = []
        if memory.system_prompt:
            result.extend(memory.system_prompt.to_messages())
        if prev_summary_step:
            result.extend(prev_summary_step.to_messages())
        for step in prev_tail_steps:
            result.extend(step.to_messages())
        for step in curr_kept_steps:
            result.extend(step.to_messages())
        return result


# ── Standalone offline compression ─────────────────────────────

def _build_offline_user_prompt(schema_desc: str, text: str, is_incremental: bool) -> str:
    """Build the user prompt for offline compression."""
    if is_incremental:
        return (
            f"Update the summary following this JSON structure:\n{schema_desc}\n\n"
            f"{text}"
        )
    return (
        f"Create a structured checkpoint summary following this JSON structure:\n{schema_desc}\n\n"
        f"TURNS TO SUMMARIZE:\n{text}"
    )


def _call_model_for_summary(model, messages) -> Optional[str]:
    """Call the model and extract a summary from the response. Returns None on any failure."""
    try:
        response = model(messages, stop_sequences=[])
        raw_output = response.content
        if isinstance(raw_output, list):
            raw_output = " ".join(
                block.get("text", "")
                for block in raw_output
                if isinstance(block, dict) and block.get("type") == "text"
            )
        if not isinstance(raw_output, str):
            raw_output = str(raw_output)
        return format_summary_output(raw_output)
    except Exception:
        logger.exception("Model call for offline summary failed")
        return None


def compress_history_offline(
    pairs: List[Tuple[str, str]],
    model,
    config: Optional[ContextManagerConfig] = None,
    previous_summary: Optional[str] = None,
) -> dict:
    """Compress conversation history offline, without ContextManager or AgentMemory.

    Standalone function for static compression inspection in benchmarks.
    Takes plain-text (user, assistant) pairs and produces a summary using
    the same prompts and schema as the in-agent compression path, but without
    any stateful cache, offload store, or agent runtime.
    """
    config = config or ContextManagerConfig()
    if config.max_summary_input_tokens <= 0:
        config.max_summary_input_tokens = int(config.token_threshold * 1.2)
    if not pairs and not previous_summary:
        return {
            "summary": None,
            "is_incremental": False,
            "is_fallback": False,
            "input_text": "",
            "input_chars": 0,
        }

    parts = [f"user: {u}\nassistant: {a}" for u, a in pairs]
    pairs_text = "\n\n".join(parts)
    is_incremental = previous_summary is not None

    if is_incremental:
        input_text = f"## Previous Summary\n{previous_summary}\n\n## New Conversations\n{pairs_text}"
    else:
        input_text = pairs_text

    input_tokens = estimate_tokens_text(input_text)
    if input_tokens > config.max_summary_input_tokens:
        approx_chars = int(config.max_summary_input_tokens * config.chars_per_token * 0.9)
        input_text = "...[Earlier content truncated]...\n" + input_text[-approx_chars:]

    schema_desc = json.dumps(config.summary_json_schema, ensure_ascii=False, indent=2)
    system_prompt = (
        config.incremental_summary_system_prompt if is_incremental
        else config.summary_system_prompt
    )
    user_prompt = _build_offline_user_prompt(schema_desc, input_text, is_incremental)

    messages = [
        ChatMessage(role=MessageRole.SYSTEM, content=[{"type": "text", "text": system_prompt}]),
        ChatMessage(role=MessageRole.USER, content=[{"type": "text", "text": user_prompt}]),
    ]

    is_fallback = False
    summary = _call_model_for_summary(model, messages)

    # Retry with truncated input on context-length errors
    if summary is None:
        approx_chars = int(config.max_summary_input_tokens * config.chars_per_token * 0.6)
        truncated_input = input_text[-approx_chars:] if len(input_text) > approx_chars else input_text
        user_prompt = _build_offline_user_prompt(schema_desc, truncated_input, is_incremental)
        messages[-1] = ChatMessage(
            role=MessageRole.USER, content=[{"type": "text", "text": user_prompt}],
        )
        summary = _call_model_for_summary(model, messages)

    # Final fallback: mechanical truncation
    if summary is None:
        is_fallback = True
        first_task = pairs[0][0][:200] if pairs else ""
        reduced_chars = int(config.max_summary_reduce_tokens * config.chars_per_token)
        reduced_text = pairs_text[-reduced_chars:] if len(pairs_text) > reduced_chars else pairs_text
        summary = (
            "[CONTEXT COMPACTION — REFERENCE ONLY] Earlier steps were removed to free context space. "
            "The removed content cannot be summarized. Continue based on the steps below.\n\n"
            f"Original task: {first_task}\n\n"
            f"Steps removed: {len(pairs)} of {len(pairs)}\n\n"
            "Remaining compressed history:\n"
            + reduced_text
        )

    return {
        "summary": summary,
        "is_incremental": is_incremental,
        "is_fallback": is_fallback,
        "input_text": input_text,
        "input_chars": len(input_text),
    }
