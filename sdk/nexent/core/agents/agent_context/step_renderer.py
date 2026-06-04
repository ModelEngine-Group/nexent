"""Step rendering and text transformation for ContextManager."""

import logging
from typing import Dict, List, Optional, Tuple

from smolagents.memory import ActionStep, AgentMemory, MemoryStep, TaskStep
from smolagents.models import ChatMessage

from ..summary_config import ContextManagerConfig
from ...utils.token_estimation import (
    _extract_text_from_messages,
    estimate_tokens_text,
)
from .offload_store import OffloadStore
from .summary_step import SummaryTaskStep

logger = logging.getLogger("agent_context.step_renderer")


# ============================================================
#  Standalone offline compression (no ContextManager state)
# ============================================================

def compress_history_offline(
    pairs: List[Tuple[str, str]],
    model,
    config: Optional[ContextManagerConfig] = None,
    previous_summary: Optional[str] = None,
) -> dict:
    """Compress conversation history offline, without ContextManager or AgentMemory.

    This is a standalone function for **Static compression Inspection** in
    benchmarks. It takes plain-text (user, assistant) pairs and produces a
    summary using the same prompts and schema as the in-agent compression path,
    but without any stateful cache, offload store, or agent runtime.

    Args:
        pairs: List of (user_text, assistant_text) tuples representing
               conversation turns to compress.
        model: An LLM model object compatible with smolagents' call interface.
        config: ContextManagerConfig providing prompts, schema, and token budgets.
                Defaults to a fresh ContextManagerConfig() if not provided.
        previous_summary: Optional existing summary text for incremental
                          compression. If provided, uses the incremental prompt
                          to update rather than create from scratch.

    Returns:
        dict with:
          - "summary": the compressed summary text (str or None on failure)
          - "is_incremental": whether incremental compression was used
          - "is_fallback": whether the LLM failed and fallback truncation was used
          - "input_text": the raw text that was fed to the LLM (for debugging)
          - "input_chars": character count of the input text
    """
    import json

    from smolagents.models import MessageRole

    from .llm_summary import format_summary_output, _is_context_length_error

    config = config or ContextManagerConfig()
    # Same compensation as ContextManager.__init__: when max_summary_input_tokens
    # is left at the default 0, derive it from token_threshold so that truncation
    # logic doesn't accidentally chop all input.
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

    # Build input text from pairs
    parts = []
    for user_text, assistant_text in pairs:
        parts.append(f"user: {user_text}\nassistant: {assistant_text}")
    pairs_text = "\n\n".join(parts)

    # Determine compression mode
    is_incremental = previous_summary is not None

    if is_incremental:
        input_text = (
            f"## Previous Summary\n{previous_summary}\n\n"
            f"## New Conversations\n{pairs_text}"
        )
    else:
        input_text = pairs_text

    # Truncate if exceeds budget (tail-truncation: preserve newest content)
    input_tokens = estimate_tokens_text(input_text)
    if input_tokens > config.max_summary_input_tokens:
        approx_chars = int(config.max_summary_input_tokens * config.chars_per_token * 0.9)
        input_text = "...[Earlier content truncated]...\n" + input_text[-approx_chars:]

    # Build prompt
    schema_desc = json.dumps(config.summary_json_schema, ensure_ascii=False, indent=2)
    if is_incremental:
        system_prompt = config.incremental_summary_system_prompt
        user_prompt = (
            f"Update the summary following this JSON structure:\n{schema_desc}\n\n"
            f"{input_text}"
        )
    else:
        system_prompt = config.summary_system_prompt
        user_prompt = (
            f"Create a structured checkpoint summary following this JSON structure:\n{schema_desc}\n\n"
            f"TURNS TO SUMMARIZE:\n{input_text}"
        )

    messages = [
        ChatMessage(role=MessageRole.SYSTEM,
                    content=[{"type": "text", "text": system_prompt}]),
        ChatMessage(role=MessageRole.USER,
                    content=[{"type": "text", "text": user_prompt}]),
    ]

    # Call LLM with error handling
    is_fallback = False
    summary = None

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
        summary = format_summary_output(raw_output)
    except Exception as e:
        if _is_context_length_error(e):
            logger.warning("Offline compression exceeds context limit; retrying with 2/3 budget")
            approx_chars = int(config.max_summary_input_tokens * config.chars_per_token * 0.6)
            truncated_input = input_text[-approx_chars:] if len(input_text) > approx_chars else input_text
            if is_incremental:
                user_prompt = (
                    f"Update the summary following this JSON structure:\n{schema_desc}\n\n"
                    f"{truncated_input}"
                )
            else:
                user_prompt = (
                    f"Create a structured checkpoint summary following this JSON structure:\n{schema_desc}\n\n"
                    f"TURNS TO SUMMARIZE:\n{truncated_input}"
                )
            messages[-1] = ChatMessage(
                role=MessageRole.USER,
                content=[{"type": "text", "text": user_prompt}],
            )
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
                summary = format_summary_output(raw_output)
            except Exception as e2:
                logger.error(f"Offline compression retry still failed: {e2}")

        if summary is None:
            # L3 fallback: hard truncation
            is_fallback = True
            first_task = pairs[0][0][:200] if pairs else ""
            reduced_chars = int(config.max_summary_reduce_tokens * config.chars_per_token)
            reduced_text = pairs_text[-reduced_chars:] if len(pairs_text) > reduced_chars else pairs_text
            summary = (
                "[CONTEXT COMPACTION \u2014 REFERENCE ONLY] Earlier steps were removed to free context space. "
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


# ============================================================
#  StepRenderer (standalone class, owns config + offload_store)
# ============================================================

class StepRenderer:
    """Step rendering and text transformation.

    Owns its config and offload_store references, with no cross-mixin
    dependencies. All methods are pure computation on the provided inputs.
    """

    def __init__(self, config: ContextManagerConfig, offload_store: OffloadStore):
        self._config = config
        self._offload_store = offload_store

    def render_action_step(self, action: ActionStep, offload_store: Optional[OffloadStore] = None) -> str:
        """Render an ActionStep to text, with per-segment offload.

        Each message segment (model_output, tool_call, observation) is independently
        checked against the offload threshold. Only oversized segments are offloaded;
        short segments remain intact, giving the compression LLM sufficient context
        to produce a high-quality summary.
        """
        msgs = action.to_messages(summary_mode=False)

        # Fast path: no offload configured — simple concatenation
        if offload_store is None or self._config.per_step_render_limit <= 0:
            return _extract_text_from_messages(msgs) or ""

        # Per-segment rendering with offload
        parts = []
        for msg in msgs:
            text = _extract_text_from_messages([msg]) or ""
            if text.startswith("Calling tools:"):
                # Tool call is always short — keep verbatim
                parts.append(text)
            else:
                # Per-segment offload: observation or model_output
                parts.append(self._render_segment(text, action, offload_store))
        return "\n".join(parts)

    def _render_segment(self, text: str, action: ActionStep, offload_store: Optional[OffloadStore] = None) -> str:
        """Render a single message segment, offloading if oversized.

        When the segment exceeds ``per_step_render_limit``, the full text is archived
        in ``offload_store`` and replaced with a self-describing marker so the
        compression LLM knows what was offloaded and how to retrieve it.

        If the action has a ``_raw_observation`` attribute (preserved before
        ``max_observation_length`` truncation), the original text is used for
        offload so that ``reload`` can retrieve the truly original content.

        Args:
            text: The display segment text (possibly already truncated by
                  ``max_observation_length``).
            action: The ActionStep being rendered; may carry ``_raw_observation``.
            offload_store: OffloadStore for archiving oversized segments.

        Returns:
            Rendered segment — either the full text, or a truncated version ending
            with a self-describing offload marker.
        """
        limit = self._config.per_step_render_limit
        if offload_store is None or limit <= 0:
            return text

        # Determine the source text for offload decisions and archiving.
        # For observations, prefer the pre-truncation raw content if available.
        source_text = text
        if text.startswith("Observation:") and hasattr(action, '_raw_observation'):
            source_text = action._raw_observation

        # If the source (original) content is within limit, no offload needed.
        if len(source_text) <= limit:
            return text

        # Build the human/LLM-readable description first, so the same hint
        # is stored alongside the content (for list_active inventory)
        # and embedded in the inline marker. Preview is based on *display*
        # text (``text``) because that is what the LLM already sees.
        char_count = len(source_text)
        if text.startswith("Observation:"):
            first_line = text.split("\n")[0] if "\n" in text else text[:100]
            description = f"{first_line[:80]} ({char_count} chars)"
        else:
            preview = text[:80].replace("\n", " ").strip()
            description = f"{preview}... ({char_count} chars)"

        # Offload triggered — archive the original (or raw) content together
        # with its description.
        handle = offload_store.store(source_text, description=description)
        if handle is None:
            # Content too large even for offload store; fall back to plain truncation.
            return text[:limit] + "\n...[CONTENT_TOO_LARGE_TO_OFFLOAD]"

        # Build a self-describing marker so the LLM understands what was offloaded.
        if text.startswith("Observation:"):
            marker = f"\n...[[OBS_OFFLOAD: {description}, handle={handle}]]"
        else:
            marker = f"\n...[[CONTENT_OFFLOAD: {description}, handle={handle}]]"

        return text[:limit] + marker

    def truncate_text_to_tokens(self, text: str, max_tokens: int) -> str:
        if max_tokens <= 0:
            return ""
        if estimate_tokens_text(text) <= max_tokens:
            return text
        units = text.split("\n\n")
        kept, total = [], 0
        for u in reversed(units):
            u_tokens = estimate_tokens_text(u)
            if total + u_tokens > max_tokens and kept:
                break
            kept.append(u)
            total += u_tokens
        result = "...[Earlier content truncated]...\n\n" + "\n\n".join(reversed(kept))
        if estimate_tokens_text(result) > max_tokens:
            approx_chars = int(max_tokens * self._config.chars_per_token * 0.9)
            result = "...[Earlier content truncated]...\n" + result[:approx_chars]
        return result

    def pairs_to_text(self, pairs: List[tuple], offload_store: Optional[OffloadStore] = None) -> str:
        parts = []
        for i, (task_step, action_step) in enumerate(pairs):
            task_text = task_step.task or ""
            action_text = self.render_action_step(action_step, offload_store=offload_store)
            parts.append(f"user: {task_text}\nassistant: {action_text}")
        return "\n\n".join(parts)

    def pairs_to_steps(self, pairs: List[tuple]) -> List[MemoryStep]:
        steps = []
        for task_step, action_step in pairs:
            steps.append(task_step)
            steps.append(action_step)
        return steps

    def build_messages(
        self, memory: AgentMemory,
        prev_summary_step: Optional[SummaryTaskStep],
        prev_tail_steps: List[MemoryStep],
        curr_kept_steps: List[MemoryStep],
    ) -> List[ChatMessage]:
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

    def actions_to_text(self, actions: List[ActionStep], offload_store: Optional[OffloadStore] = None) -> str:
        parts = []
        for i, step in enumerate(actions):
            text = self.render_action_step(step, offload_store=offload_store)
            parts.append(f"[Step {step.step_number or i+1}]\n{text}")
        return "\n\n".join(parts)

    def render_steps_with_truncation(
        self,
        steps: List,
        fmt: str = "action",
        max_tokens: int = None,
        min_budget_chars: int = 80,
        task_budget_chars: int = 800,
        action_budget_chars: int = None,
        offload_store: Optional[OffloadStore] = None,
    ) -> str:
        if max_tokens is None:
            max_tokens = self._config.max_summary_input_tokens
        if action_budget_chars is None:
            action_budget_chars = self._config.max_memory_step_length

        entries = self._build_step_entries(steps, fmt, offload_store=offload_store)
        raw_text = "\n\n".join(task + action for task, action in entries)
        if estimate_tokens_text(raw_text) <= max_tokens:
            return raw_text

        return self._truncate_entries_to_budget(entries, max_tokens, min_budget_chars, task_budget_chars, action_budget_chars)

    def _build_step_entries(self, steps: List, fmt: str, offload_store: Optional[OffloadStore] = None) -> List[Tuple[str, str]]:
        entries = []
        for step in steps:
            if fmt == "action":
                text = f"[Step {step.step_number or '?'}]\n{self.render_action_step(step, offload_store=offload_store)}"
                entries.append(("", text))
            else:
                task_step, action_step = step
                task_str = f"user: {task_step.task or ''}\nassistant: "
                action_str = self.render_action_step(action_step, offload_store=offload_store)
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

            if estimate_tokens_text(all_text) <= max_tokens:
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