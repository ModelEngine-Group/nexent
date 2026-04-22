import hashlib
import json
import logging
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

from smolagents.memory import ActionStep, AgentMemory, MemoryStep, TaskStep
from smolagents.models import ChatMessage, MessageRole

logger = logging.getLogger("agent_context")

from ..utils.token_estimation import (
    _extract_text_from_messages,
    estimate_tokens,
    estimate_tokens_for_steps,
    msg_char_count,
    msg_token_count,
    estimate_tokens_for_system_prompt
)


@dataclass
class PreviousSummaryCache:
    """Caches the compressed summary from the previous run."""
    summary_text: str
    covered_pairs: int
    anchor_fingerprint: str


@dataclass
class CurrentSummaryCache:
    summary_text: str
    end_steps: int
    anchor_fingerprint: str


@dataclass
class ContextManagerConfig:
    enabled: bool = False
    token_threshold: int = 10000
    keep_recent_steps: int = 4
    keep_recent_pairs: int = 2
    max_chunk_count: int = 0
    max_memory_step_length: int = 2000 # all kinds of MemoryStep dataclass

    summary_system_prompt: str = (
        "你是一个对话摘要助手。请将以下对话历史压缩为结构化摘要，"
        "保留所有关键信息：用户的核心需求、已完成的工作、重要发现和决策、"
        "待办事项、需要保留的上下文。输出严格 JSON 格式，不要包含 markdown 代码块标记。"
    )

    summary_json_schema: Dict[str, Any] = field(default_factory=lambda: {
        "task_overview": "用户的核心请求与成功标准（≤150字）",
        "completed_work": "已完成的工作、产出的文件或结果（≤200字）",
        "key_decisions": "重要发现、做出的决策及其理由（≤200字）",
        "pending_items": "待完成的具体步骤、阻塞项（≤150字）",
        "context_to_preserve": "用户偏好、领域细节、做出的承诺（≤150字）",
    })

    max_summary_input_tokens: int = 0
    max_summary_reduce_tokens: int = 0
    estimated_chunk_summary_tokens: int = 400
    chars_per_token: float = 1.5


@dataclass
class CompressionCallRecord:
    call_type: str
    input_tokens: int = 0
    output_tokens: int = 0
    input_chars: int = 0
    output_chars: int = 0
    cache_hit: bool = False
    details: dict = field(default_factory=dict)


@dataclass
class SummaryTaskStep(TaskStep):
    is_summary: bool = True
    prefix: str = "Summary of earlier steps in this task:" # default prefix

    def to_messages(self, summary_mode: bool = False) -> list:
        content = [{"type": "text", "text": f"{self.prefix}:\n{self.task}"}]
        return [ChatMessage(role=MessageRole.USER, content=content)]


class ContextManager:
    def __init__(self, config: Optional[ContextManagerConfig] = None, max_steps: Optional[int] = None):
        self.config = config or ContextManagerConfig()
        self._previous_summary_cache: Optional[PreviousSummaryCache] = None
        self._current_summary_cache: Optional[CurrentSummaryCache] = None

        # Run boundary self-detection. The current cache fingerprint is only reused
        # within the current run and must be explicitly cleared at the start of a new run.
        # The previous cache is managed and updated across runs.
        self._last_run_start_idx: Optional[int] = None

        if max_steps is not None and self.config.keep_recent_steps >= max_steps:
            self.config.keep_recent_steps = max_steps

        self.compression_calls_log: List[CompressionCallRecord] = []
        self._step_local_log: List[CompressionCallRecord] = []
        self._lock = threading.Lock()

        if self.config.max_summary_input_tokens <= 0:
            self.config.max_summary_input_tokens = int(self.config.token_threshold * 1.2)
        if self.config.max_summary_reduce_tokens <= 0:
            self.config.max_summary_reduce_tokens = int(self.config.token_threshold * 0.2)

    # ============================================================
    #  Cache validation
    # ============================================================

    def _is_prev_cache_valid(self, prev_pairs: List[tuple]) -> Tuple[bool, int]:
        """Checks whether the previous cache covers a prefix of prev_pairs.

        Returns (is_valid, covered_idx). When is_valid is True, prev_pairs[0:covered_idx]
        can be replaced by cache.summary_text, and prev_pairs[covered_idx:] represents
        the uncovered incremental portion.
        """
        cache = self._previous_summary_cache
        if cache is None or not prev_pairs:
            return False, 0
        if cache.covered_pairs == 0 or cache.covered_pairs > len(prev_pairs):
            return False, 0
        anchor_t, anchor_a = prev_pairs[cache.covered_pairs - 1]
        fp = self._pair_fingerprint(anchor_t.task or "", self._action_content(anchor_a))
        if fp != cache.anchor_fingerprint:
            return False, 0
        return True, cache.covered_pairs

    def _is_curr_cache_valid(self, action_steps: List[ActionStep]) -> Tuple[bool, int]:
        cache = self._current_summary_cache
        if cache is None or not action_steps:
            return False, 0
        if cache.end_steps == 0 or cache.end_steps > len(action_steps):
            return False, 0
        anchor = action_steps[cache.end_steps - 1]
        if self._action_fingerprint(anchor) != cache.anchor_fingerprint:
            return False, 0
        return True, cache.end_steps

    # ============================================================
    #  Effective token estimation
    # ============================================================

    def _effective_tokens(self, memory: AgentMemory, current_run_start_idx: int) -> int:
        """Estimates the actual token burden of the upcoming _build_messages call.
        Uses summary_text for the covered prefix when cache is valid; falls back to raw otherwise.
        """
        system_prompt_tokens = estimate_tokens_for_system_prompt(memory)
        prev_steps = memory.steps[:current_run_start_idx]
        curr_steps = memory.steps[current_run_start_idx:]
        return (system_prompt_tokens + self._effective_prev_tokens(prev_steps)
                + self._effective_curr_tokens(curr_steps))

    def _effective_prev_tokens(self, prev_steps: List[MemoryStep]) -> int:
        if not prev_steps:
            return 0
        prev_pairs = self._extract_pairs(prev_steps)
        is_valid, covered_idx = self._is_prev_cache_valid(prev_pairs)
        if not is_valid:
            return self._estimate_tokens_for_steps(prev_steps)
        uncovered = prev_pairs[covered_idx:]
        uncovered_tokens = (
            self._estimate_text_tokens(self._pairs_to_text(uncovered))
            if uncovered else 0
        )
        return (self._estimate_text_tokens(self._previous_summary_cache.summary_text)
                + uncovered_tokens)

    def _effective_curr_tokens(self, curr_steps: List[MemoryStep]) -> int:
        if not curr_steps:
            return 0
        curr_task = curr_steps[0] if isinstance(curr_steps[0], TaskStep) else None
        action_steps = [s for s in curr_steps if isinstance(s, ActionStep)]
        is_valid, covered_idx = self._is_curr_cache_valid(action_steps)
        if not is_valid:
            return self._estimate_tokens_for_steps(curr_steps)
        task_tokens = (
            self._estimate_text_tokens(curr_task.task or "") if curr_task else 0
        )
        uncovered = action_steps[covered_idx:]
        uncovered_tokens = (
            self._estimate_text_tokens(self._actions_to_text(uncovered))
            if uncovered else 0
        )
        return (task_tokens
                + self._estimate_text_tokens(self._current_summary_cache.summary_text)
                + uncovered_tokens)

    # ============================================================
    #  Budget helpers
    # ============================================================

    def _estimate_text_tokens(self, text: str) -> int:
        from ..utils.token_estimation import estimate_tokens_text
        return estimate_tokens_text(text)

    def _trim_pairs_to_budget(
        self, pairs: List[tuple], max_tokens: int, keep_first: bool = True,
    ) -> List[tuple]:
        if not pairs:
            return []
        pair_tokens = [
            self._estimate_text_tokens(self._pairs_to_text([p])) for p in pairs
        ]
        sep = self._estimate_text_tokens("\n\n")
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



    def _trim_actions_to_budget(
        self, actions: List[ActionStep], task_text: str, max_tokens: int,
    ) -> List[ActionStep]:
        if not actions:
            return []

        def _total_tokens(acts):
            return self._estimate_text_tokens(task_text + self._actions_to_text(acts))

        if _total_tokens(actions) <= max_tokens:
            return list(actions)
        for drop in range(1, len(actions) + 1):
            remaining = actions[drop:]
            if not remaining:
                break
            if remaining and hasattr(remaining[0], 'observations') and remaining[0].observations is not None:
                if drop > 0 and hasattr(actions[drop-1], 'tool_calls') and actions[drop-1].tool_calls is not None:    
                    continue
            if _total_tokens(remaining) <= max_tokens:
                return list(remaining)
            
        last_action = actions[-1]
        
        if len(actions) >= 2 and hasattr(last_action, 'observations') and last_action.observations is not None:
            prev_action = actions[-2]
            if hasattr(prev_action, 'tool_calls') and prev_action.tool_calls is not None:
                logger.warning(
                    "Fallback limit triggered: Retaining the last complete ToolCall + Observation pair intact. "
                    "This may exceed the token budget, and downstream truncation will be relied upon."
                )
                return [prev_action, last_action]
        return [last_action]
    
    # ============================================================
    #  Mainly Entry Point
    # ============================================================

    def compress_if_needed(
        self, model, memory, original_messages: List[ChatMessage], current_run_start_idx,
    ) -> List[ChatMessage]:
        # G1
        if not self.config.enabled:
            return original_messages
        
        if self._estimate_tokens(memory) <= self.config.token_threshold:
            return original_messages 

        with self._lock:
            # Run detection
            if (self._last_run_start_idx is not None
                    and current_run_start_idx != self._last_run_start_idx):
                self._current_summary_cache = None
            self._last_run_start_idx = current_run_start_idx

            # Note: The memory here always consists of the unmodified, summary-task-step-free
            # original previous_run + current_run.
            # - previous_run: [(TaskStep, ActionStep), ...]
            # - current_run:  [TaskStep, ActionStep, ActionStep, ...]
            if self._effective_tokens(memory, current_run_start_idx) <= self.config.token_threshold:
                # Stable-phase bypass: No LLM call; construct compressed messages directly from existing cache.
                self._step_local_log.clear()

                prev_steps = memory.steps[:current_run_start_idx]
                curr_steps = memory.steps[current_run_start_idx:]

                prev_summary_step = None
                prev_tail_steps = list(prev_steps)
                prev_pairs = self._extract_pairs(prev_steps)
                if prev_pairs:
                    is_valid, covered_idx = self._is_prev_cache_valid(prev_pairs)
                    if is_valid:
                        prev_summary_step = SummaryTaskStep(
                            task=self._previous_summary_cache.summary_text
                        )
                        uncovered = prev_pairs[covered_idx:]
                        prev_tail_steps = self._pairs_to_steps(uncovered)

                curr_kept_steps = list(curr_steps)
                if curr_steps:
                    curr_task = curr_steps[0] if isinstance(curr_steps[0], TaskStep) else None
                    curr_action_steps = [s for s in curr_steps if isinstance(s, ActionStep)]
                    if curr_action_steps:
                        is_valid, covered_idx = self._is_curr_cache_valid(curr_action_steps)
                        if is_valid:
                            uncovered = curr_action_steps[covered_idx:]
                            curr_kept_steps = (
                                ([curr_task] if curr_task else [])
                                + [SummaryTaskStep(task=self._current_summary_cache.summary_text)]
                                + list(uncovered)
                            )

                record = CompressionCallRecord(
                    call_type="no_op", cache_hit=True,
                    details={"reason": "stable_period_effective_under_threshold"},
                )
                self.compression_calls_log.append(record)
                self._step_local_log.append(record)

                return self._build_messages(
                    memory, prev_summary_step, prev_tail_steps, curr_kept_steps
                ) 

            self._step_local_log.clear()

            prev_steps = memory.steps[:current_run_start_idx]
            curr_steps = memory.steps[current_run_start_idx:]

            prev_tokens = self._effective_prev_tokens(prev_steps)
            curr_tokens = self._effective_curr_tokens(curr_steps)

            compress_prev = prev_tokens > self.config.token_threshold * 0.6
            compress_curr = curr_tokens > self.config.token_threshold * 0.4

            # --------------- Previous phase ---------------
            prev_summary_step: Optional[SummaryTaskStep] = None
            prev_tail_steps: List[MemoryStep] = list(prev_steps)
            prev_pairs = self._extract_pairs(prev_steps)

            if compress_prev and prev_pairs:
                keep_n = min(self.config.keep_recent_pairs, len(prev_pairs))
                pairs_to_compress = prev_pairs[:-keep_n] if keep_n > 0 else prev_pairs
                pairs_to_keep = prev_pairs[-keep_n:] if keep_n > 0 else []
                if pairs_to_compress:
                    summary_text = self._compress_previous_with_cache(
                        pairs_to_compress, model
                    )
                    if summary_text:
                        if "Truncated" in summary_text:
                            prev_summary_step = SummaryTaskStep(task=summary_text, prefix="Context fallback, Truncated raw history:")
                        else:
                            prev_summary_step = SummaryTaskStep(task=summary_text)
                        prev_tail_steps = self._pairs_to_steps(pairs_to_keep)
            elif prev_pairs:
                # if cache is valid, use cache + uncovered display
                is_valid, covered_idx = self._is_prev_cache_valid(prev_pairs)
                if is_valid:
                    prev_summary_step = SummaryTaskStep(
                        task=self._previous_summary_cache.summary_text
                    )
                    uncovered = prev_pairs[covered_idx:]
                    prev_tail_steps = self._pairs_to_steps(uncovered)

            # --------------- Current phase ---------------
            curr_kept_steps: List[MemoryStep] = list(curr_steps)

            if curr_steps:
                curr_task = curr_steps[0] if isinstance(curr_steps[0], TaskStep) else None
                curr_action_steps = [s for s in curr_steps if isinstance(s, ActionStep)]

                if compress_curr and curr_action_steps:
                    keep_n = min(self.config.keep_recent_steps, len(curr_action_steps))
                    if keep_n > 0 and keep_n < len(curr_action_steps):
                        boundary = curr_action_steps[-keep_n]
                        prev_a = curr_action_steps[-keep_n - 1]
                        if (getattr(boundary, "observations", None) is not None
                                and getattr(prev_a, "tool_calls", None) is not None):
                            keep_n += 1

                    actions_to_compress = (
                        curr_action_steps[:-keep_n] if keep_n > 0 else list(curr_action_steps)
                    )
                    actions_to_keep = (
                        curr_action_steps[-keep_n:] if keep_n > 0 else []
                    )
                    if actions_to_compress:
                        curr_summary_text = self._compress_current_with_cache(
                            curr_task, actions_to_compress, model
                        )
                        if curr_summary_text:
                            if "Truncated" in curr_summary_text:
                                curr_summary_step = SummaryTaskStep(task=curr_summary_text, prefix="Truncated recent action steps:")
                            else:
                                curr_summary_step = SummaryTaskStep(task=curr_summary_text)
                            curr_kept_steps = (
                                ([curr_task] if curr_task else [])
                                + [curr_summary_step]
                                + list(actions_to_keep)
                            )
                elif curr_action_steps:
                    is_valid, covered_idx = self._is_curr_cache_valid(curr_action_steps)
                    if is_valid:
                        uncovered = curr_action_steps[covered_idx:]
                        curr_kept_steps = (
                            ([curr_task] if curr_task else [])
                            + [SummaryTaskStep(task=self._current_summary_cache.summary_text)]
                            + list(uncovered)
                        )

            final_messages = self._build_messages(
                memory, prev_summary_step, prev_tail_steps, curr_kept_steps
            )
            final_tokens = self._msg_token_count(final_messages)
            # This situation is unlikely to occur unless the threshold itself is set unreasonably small
            if final_tokens > int(self.config.token_threshold * 1.1):
                logger.warning(
                    f"Still exceeds threshold after compression: {final_tokens} > {self.config.token_threshold}. "
                    f"Consider reducing keep_recent_pairs ({self.config.keep_recent_pairs}) "
                    f"or keep_recent_steps({self.config.keep_recent_steps})"
                )
            return final_messages

    # ============================================================
    #  Previous Compression
    # ============================================================

    def _extract_pairs(self, steps):
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

    def _compress_previous_with_cache(
        self, pairs_to_compress: List[tuple], model,
    ) -> Optional[str]:
        if not pairs_to_compress:
            return None

        # cache hit
        cache = self._previous_summary_cache
        if cache is not None and cache.covered_pairs == len(pairs_to_compress):
            anchor_t, anchor_a = pairs_to_compress[-1]
            fp = self._pair_fingerprint(
                anchor_t.task or "", self._action_content(anchor_a)
            )
            if fp == cache.anchor_fingerprint:
                return cache.summary_text

        # ===== Incremental Compression Path =====
        if (cache is not None
                and 0 < cache.covered_pairs < len(pairs_to_compress)):
            anchor_t, anchor_a = pairs_to_compress[cache.covered_pairs - 1]
            fp = self._pair_fingerprint(
                anchor_t.task or "", self._action_content(anchor_a)
            )
            if fp == cache.anchor_fingerprint:
                old_summary = cache.summary_text
                new_pairs = pairs_to_compress[cache.covered_pairs:]
                incremental_input = (
                    f"## 此前对话摘要\n{old_summary}\n\n"
                    f"## 新增对话\n{self._pairs_to_text(new_pairs)}"
                )
                input_tokens = self._estimate_text_tokens(incremental_input)
                if input_tokens <= self.config.max_summary_input_tokens:
                    summary_text = self._generate_summary(
                        incremental_input, model,
                        call_type="previous_incremental"
                    )
                    if summary_text:
                        last_t, last_a = pairs_to_compress[-1]
                        self._previous_summary_cache = PreviousSummaryCache(
                            summary_text=summary_text,
                            covered_pairs=len(pairs_to_compress),
                            anchor_fingerprint=self._pair_fingerprint(
                                last_t.task or "", self._action_content(last_a)
                            ),
                        )
                        return summary_text
                logger.info(
                    f"Incremental input {input_tokens} tokens exceeds budget "
                    f"({self.config.max_summary_input_tokens}), "
                    f"Falling back to full compression."
                )

        # Fresh compression
        summary_text, is_cacheable = self._summarize_pairs(pairs_to_compress, model)
        # summary_text is valid, not None
        if summary_text and is_cacheable:
            last_t, last_a = pairs_to_compress[-1]
            self._previous_summary_cache = PreviousSummaryCache(
                summary_text=summary_text,
                covered_pairs=len(pairs_to_compress),
                anchor_fingerprint=self._pair_fingerprint(
                    last_t.task or "", self._action_content(last_a)
                ),
            )
        # is_cacheable is False, PreviousSummaryCache keep as is
        return summary_text

    def _action_content(self, action: ActionStep) -> str:
        return action.action_output or getattr(action, "output", "") or ""

    def _pair_fingerprint(self, task_content: str, action_content: str) -> str:
        raw = (task_content[-200:] + action_content[-200:])
        return hashlib.md5(raw.encode()).hexdigest()

    def _summarize_pairs(
        self, pairs: List[tuple], model,
    ) -> Tuple[Optional[str], bool]:
        """Fresh compression entry point, returns (summary, is_cacheable)。
          L1 full summary -> (text, True)
          L2 trim summary -> (text, True)    # discard long-lived pairs, and then summarize
          L3 trim origin  -> (text, False)   # LLM call Failed, hard truncated, no summary returned
        """
        if not pairs:
            return None, False

        full_text = self._pairs_to_text(pairs)
        if self._estimate_text_tokens(full_text) <= self.config.max_summary_input_tokens:
            # L1
            target_text = full_text 
        else:
            # L2 
            trimmed_pairs = self._trim_pairs_to_budget(
                pairs, self.config.max_summary_input_tokens, keep_first=False
            )
            target_text = self._pairs_to_text(trimmed_pairs)
        
        summary_text = self._generate_summary(target_text, model, call_type="previous_summary")
        if summary_text:
            return summary_text, True 
        logger.warning("previous full/truncated history summary generation failed, triggering L3 fallback truncation")
        
        # L3
        reduced_pairs = self._trim_pairs_to_budget(pairs, self.config.max_summary_reduce_tokens, False)
        reduced_text = "Truncated: " + self._pairs_to_text(reduced_pairs)
        return reduced_text, False


    # ============================================================
    #  Current compression
    # ============================================================

    def _compress_current_with_cache(
        self, curr_task: Optional[TaskStep], actions_to_compress: List[ActionStep], model,
    ) -> Optional[str]:
        if not actions_to_compress:
            return None

        current_last_fp = self._action_fingerprint(actions_to_compress[-1])
        task_text = f"当前任务: {curr_task.task}\n\n" if curr_task else ""
        cache = self._current_summary_cache
        # 1) 完整 cache 命中
        if cache is not None and cache.end_steps == len(actions_to_compress):
            if cache.anchor_fingerprint == current_last_fp:
                return cache.summary_text
            
        # 2) 增量压缩
        if cache is not None and 0 < cache.end_steps < len(actions_to_compress):
            anchor_action = actions_to_compress[cache.end_steps - 1]
            if self._action_fingerprint(anchor_action) == cache.anchor_fingerprint:
                old_summary = cache.summary_text
                new_actions = actions_to_compress[cache.end_steps:]
                incremental_input = (
                    f"## 此前步骤摘要\n{old_summary}\n\n"
                    f"## 新增步骤\n{task_text}{self._actions_to_text(new_actions)}"
                )
                input_tokens = self._estimate_text_tokens(incremental_input)
                if input_tokens <= self.config.max_summary_input_tokens:
                    summary_text = self._generate_summary(
                        incremental_input, model, call_type="current_incremental"
                    )
                    if summary_text:
                        self._current_summary_cache = CurrentSummaryCache(
                            summary_text=summary_text,
                            end_steps=len(actions_to_compress),
                            anchor_fingerprint=current_last_fp,
                        )
                        return summary_text
                logger.info(
                    f"current incremental input {input_tokens} tokens exceeds budget "
                    f"({self.config.max_summary_input_tokens}), fallback to full compression or trimmed actions"
                )


        # 3) Fresh  compression: no cache or no valid cache or incremental input exceeds max_summary_input_tokens
        safe_actions = self._trim_actions_to_budget(
            actions_to_compress, task_text, self.config.max_summary_input_tokens,
        )
        is_full_coverage = (len(safe_actions) == len(actions_to_compress))
        if not is_full_coverage:
            logger.info(
                f"current full summary trimmed {len(actions_to_compress) - len(safe_actions)} "
                f"oldest action, still using cache"
            )

        # In current phase, there may be oversized monolithic payload
        full_text = task_text + self._actions_to_text_with_limit(safe_actions,prefill_tokens=self._estimate_text_tokens(task_text))
        full_text = task_text + self._actions_to_text(safe_actions)
        summary_text = self._generate_summary(full_text, model, call_type="current_summary")
        if summary_text:
            self._current_summary_cache = CurrentSummaryCache(
                summary_text=summary_text,
                end_steps=len(actions_to_compress),
                anchor_fingerprint=current_last_fp,
            )
            return summary_text
        else:
            reduced_actions = self._trim_actions_to_budget(actions_to_compress, task_text, self.config.max_summary_reduce_tokens)
            reduced_text = "Truncated action steps: " + self._actions_to_text(reduced_actions)[self.config.max_summary_reduce_tokens:]
            return reduced_text

    def _actions_to_text(self, actions: List[ActionStep]) -> str:
        parts = []
        for i, step in enumerate(actions):
            text = self._render_action_step(step)
            parts.append(f"[步骤 {step.step_number or i+1}]\n{text}")
        return "\n\n".join(parts)

    def _actions_to_text_with_limit(self, actions: List[ActionStep], prefill_tokens: int = 0) -> str:
        rendered_steps = []
        for i, step in enumerate(actions):
            prefix = f"[步骤 {step.step_number or i+1}]\n"
            content = self._render_action_step(step)
            rendered_steps.append((prefix, content))
        budget_per_action = self.config.max_memory_step_length

        while True:
            parts = [] 
            
            for prefix, content in rendered_steps:
                if len(content) > budget_per_action:
                    text = f"{prefix}{content[:budget_per_action]}\n\n[System Note: 该步骤内容过长，已被部分截断]"
                else:
                    text = f"{prefix}{content}"
                parts.append(text)
                
            all_text = "\n\n".join(parts)

            if self._estimate_text_tokens(all_text) + prefill_tokens <= self.config.max_summary_input_tokens:
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

    @staticmethod
    def _action_fingerprint(action: ActionStep) -> str:
        raw = (
            str(action.step_number or "")
            + (action.model_output or "")[-200:]
            + (
                action.action_output if isinstance(action.action_output, str)
                else str(action.action_output) if action.action_output else ""
            )[-200:]
        )
        return hashlib.md5(raw.encode()).hexdigest()

    # ============================================================
    #  LLM call
    # ============================================================

    def _is_context_length_error(self, err: Exception) -> bool:
        msg = str(err).lower()
        return any(k in msg for k in (
            "context_length", "context length", "maximum context", "maximum context length",
            "prompt is too long", "reduce the length", "too many tokens",
            "token limit", "exceeds the maximum", "input is too long",
            "input length", "exceeds context", "context window",
        ))

    def _generate_summary(self, text: str, model, call_type: str = "summary") -> Optional[str]:
        try:
            return self._do_generate_summary(text, model, call_type)
        except Exception as e:
            if self._is_context_length_error(e):
                logger.warning(f"{call_type} exceeds context limit; retrying with 2/3 budget truncation")
                shrunk = self._truncate_text_to_tokens(
                    text, int(self.config.max_summary_input_tokens * 0.66)
                )
                try:
                    return self._do_generate_summary(shrunk, model, call_type + "_retry")
                except Exception as e2:
                    logger.error(f"Retry still failed: {e2}")
                    return None
            logger.error(f"Summary generation exception: {e}")
            return None

    def _do_generate_summary(self, text: str, model, call_type: str = "summary") -> Optional[str]:
        schema_desc = json.dumps(
            self.config.summary_json_schema, ensure_ascii=False, indent=2
        )
        user_prompt = (
            f"请按以下 JSON 结构输出摘要：\n{schema_desc}\n\n"
            f"需要摘要的对话内容：\n{text}"
        )
        messages = [
            ChatMessage(role=MessageRole.SYSTEM,
                        content=[{"type": "text", "text": self.config.summary_system_prompt}]),
            ChatMessage(role=MessageRole.USER,
                        content=[{"type": "text", "text": user_prompt}]),
        ]
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

        summary = self._format_summary(raw_output)
        self._record_llm_call_token(
            input_len=self._msg_char_count(messages),
            output_len=len(raw_output),
            response=response, call_type=call_type,
        )
        return summary


    def _record_llm_call_token(self, input_len, output_len, response, call_type):
        record = CompressionCallRecord(
            call_type=call_type,
            input_tokens=getattr(getattr(response, "token_usage", None), "input_tokens", 0) or 0,
            output_tokens=getattr(getattr(response, "token_usage", None), "output_tokens", 0) or 0,
            input_chars=input_len, output_chars=output_len,
        )
        self.compression_calls_log.append(record)
        self._step_local_log.append(record)

    def _format_summary(self, raw_output: str) -> Optional[str]:
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

    def _render_action_step(self, action: ActionStep) -> str:
        msgs = action.to_messages(summary_mode=False)
        return _extract_text_from_messages(msgs) or ""

    def _truncate_text_to_tokens(self, text: str, max_tokens: int) -> str:
        if max_tokens <= 0:
            return ""
        if self._estimate_text_tokens(text) <= max_tokens:
            return text
        units = text.split("\n\n")
        kept, total = [], 0
        for u in reversed(units):
            u_tokens = self._estimate_text_tokens(u)
            if total + u_tokens > max_tokens and kept:
                break
            kept.append(u)
            total += u_tokens
        result = "...[前段已截断]...\n\n" + "\n\n".join(reversed(kept))
        if self._estimate_text_tokens(result) > max_tokens:
            approx_chars = int(max_tokens * self.config.chars_per_token * 0.9)
            result = "...[前段已截断]...\n" + result[:approx_chars]
        return result

    def _pairs_to_text(self, pairs: List[tuple]) -> str:
        parts = []
        for i, (task_step, action_step) in enumerate(pairs):
            task_text = task_step.task or ""
            action_text = self._render_action_step(action_step)
            parts.append(f"user: {task_text}\nassistant: {action_text}")
        return "\n\n".join(parts)

    def _pairs_to_steps(self, pairs: List[tuple]) -> List[MemoryStep]:
        steps = []
        for task_step, action_step in pairs:
            steps.append(task_step)
            steps.append(action_step)
        return steps

    def _build_messages(
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

    # ============================================================
    #  Token Estimation
    # ============================================================

    def _estimate_tokens_for_steps(self, steps):
        return estimate_tokens_for_steps(steps, self.config.chars_per_token)

    def _estimate_tokens(self, memory: AgentMemory) -> int:
        return estimate_tokens(memory, self.config.chars_per_token)

    def _msg_char_count(self, msg: Union[ChatMessage, List[ChatMessage]]) -> int:
        return msg_char_count(msg)

    def _msg_token_count(self, msg):
        return msg_token_count(msg, self.config.chars_per_token)

    def get_step_compression_stats(self) -> dict:
        with self._lock:
            if not self._step_local_log:
                return {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cache_hits": 0}
            return {
                "calls": len([r for r in self._step_local_log if not r.cache_hit]),
                "input_tokens": sum(r.input_tokens for r in self._step_local_log),
                "output_tokens": sum(r.output_tokens for r in self._step_local_log),
                "input_chars": sum(r.input_chars for r in self._step_local_log),
                "output_chars": sum(r.output_chars for r in self._step_local_log),
                "cache_hits": sum(1 for r in self._step_local_log if r.cache_hit),
            }

    def get_all_compression_stats(self) -> dict:
        with self._lock:
            real_calls = [r for r in self.compression_calls_log if not r.cache_hit]
            return {
                "total_calls": len(real_calls),
                "total_input_tokens": sum(r.input_tokens for r in real_calls),
                "total_output_tokens": sum(r.output_tokens for r in real_calls),
                "total_cache_hits": sum(1 for r in self.compression_calls_log if r.cache_hit),
            }