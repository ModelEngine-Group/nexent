"""
factories.py
────────────
Centralised factory functions for test objects.

All make_* functions are pure (no pytest dependency) so they can be called
directly in tests or wrapped in fixtures inside conftest.py.

Imports
-------
- loader  : for the classes exported from agent_context
- stubs   : for _SystemPromptStep (not re-exported by loader)
"""

from typing import Optional
from unittest.mock import MagicMock
import sys 
import os 
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from loader import (
    AgentMemory,
    ActionStep,
    ContextManager,
    ContextManagerConfig,
    TaskStep,
)
from stubs import _SystemPromptStep


# ──────────────────────────────────────────────────────────────
# Primitive builders
# ──────────────────────────────────────────────────────────────

def make_pair(
    task_text: str = "task",
    action_output: str = "result",
    step_num: int = 1,
):
    """Return a (TaskStep, ActionStep) tuple — the smallest logical unit."""
    t = TaskStep(task=task_text)
    a = ActionStep(
        step_number=step_num,
        model_output=action_output,
        action_output=action_output,
    )
    return t, a


def make_model(summary_output: str = '{"task_overview": "test summary"}') -> MagicMock:
    """
    Return a callable mock that behaves like a smolagents model.
    Calling it returns a response whose .content is summary_output and
    whose .token_usage reports 50 input / 20 output tokens.
    """
    model    = MagicMock()
    response = MagicMock()
    response.content     = summary_output
    response.token_usage = MagicMock(input_tokens=50, output_tokens=20)
    model.return_value   = response
    return model


def make_cm(
    enabled: bool = True,
    threshold: int = 10_000,
    keep_recent_steps: int = 2,
    keep_recent_pairs: int = 1,
) -> ContextManager:
    """Return a ContextManager configured with the given parameters."""
    cfg = ContextManagerConfig(
        enabled=enabled,
        token_threshold=threshold,
        keep_recent_steps=keep_recent_steps,
        keep_recent_pairs=keep_recent_pairs,
    )
    return ContextManager(config=cfg)


# ──────────────────────────────────────────────────────────────
# Composite memory builders
# ──────────────────────────────────────────────────────────────

def make_memory_with_steps(n_pairs: int = 3) -> AgentMemory:
    """
    Build an AgentMemory whose steps are n_pairs of (TaskStep, ActionStep).
    All steps are treated as belonging to a single previous run.
    Includes a system_prompt.
    """
    steps = []
    for i in range(n_pairs):
        t, a = make_pair(
            task_text=f"task{i} " + "X" * 50,
            action_output=f"action{i} " + "Y" * 50,
            step_num=i,
        )
        steps.extend([t, a])
    return AgentMemory(
        steps=steps,
        system_prompt=_SystemPromptStep(system_prompt="system prompt"),
    )


def make_memory_mixed(
    n_prev_pairs: int = 2,
    n_curr_actions: int = 2,
) -> AgentMemory:
    """
    Build an AgentMemory that contains both a previous run and a current run.

    Layout:
        steps[0 : 2*n_prev_pairs]     — previous run: alternating TaskStep/ActionStep pairs
        steps[2*n_prev_pairs]          — current run:  TaskStep
        steps[2*n_prev_pairs+1 : ...]  — current run:  n_curr_actions ActionSteps

    Includes a system_prompt.
    """
    steps = []

    # previous run
    for i in range(n_prev_pairs):
        t, a = make_pair(
            task_text=f"prev_task{i} " + "X" * 50,
            action_output=f"prev_action{i}" + "Y" * 50,
            step_num=i,
        )
        steps.extend([t, a])

    # current run
    curr_t = TaskStep(task="current_task" + "X" * 50)
    steps.append(curr_t)
    for i in range(n_curr_actions):
        a = ActionStep(
            step_number=n_prev_pairs + i,
            model_output=f"curr_output{i}" + "Y" * 50,
            action_output=f"curr_result{i}" + "Y" * 50,
        )
        steps.append(a)

    return AgentMemory(
        steps=steps,
        system_prompt=_SystemPromptStep(system_prompt="system prompt"),
    )


# ──────────────────────────────────────────────────────────────
# Convenience: reconstruct original_messages list
# ──────────────────────────────────────────────────────────────

def make_original_messages(memory: AgentMemory) -> list:
    """
    Replicate the write_memory_to_messages logic:
        original = system_prompt.messages + Σ step.to_messages()

    Used wherever a test needs the flat message list that compress_if_needed
    would normally receive.
    """
    original = []
    if memory.system_prompt:
        original.extend(memory.system_prompt.to_messages())
    for step in memory.steps:
        original.extend(step.to_messages())
    return original