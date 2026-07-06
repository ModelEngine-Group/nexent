"""Deterministic check: does the system prompt survive managed-path assembly?

Runs prepare_run -> prepare_step (the exact path CoreAgent uses) with and
without a SystemPromptComponent, and prints whether a system-role message
is present in the final model input. No LLM call (memory kept under
threshold so compress_if_needed returns early without touching the model).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from smolagents.memory import AgentMemory, TaskStep, SystemPromptStep
from nexent.core.agents.agent_context import ContextManager
from nexent.core.agents.agent_model import SystemPromptComponent
from nexent.core.agents.summary_config import ContextManagerConfig
from nexent.core.context_runtime.managed.runtime import ManagedContextRuntime


def role_of(m):
    r = m.get("role") if isinstance(m, dict) else getattr(m, "role", None)
    return getattr(r, "value", r)


def assemble(with_component: bool):
    # High threshold -> compression never triggers -> model unused.
    cfg = ContextManagerConfig(enabled=True, token_threshold=1_000_000)
    cm = ContextManager(config=cfg, max_steps=5)
    comps = ([SystemPromptComponent(content="YOU ARE A TEST AGENT. Do the duty.")]
             if with_component else [])
    runtime = ManagedContextRuntime(cm, components=comps)

    mem = AgentMemory(system_prompt=SystemPromptStep(system_prompt="seed"))
    runtime.prepare_run(memory=mem, fallback_system_prompt="FALLBACK SYSTEM PROMPT")
    mem.steps.append(TaskStep(task="hello user"))
    fc = runtime.prepare_step(model=None, memory=mem, current_run_start_idx=0, tools=[])
    return fc.messages


def report(label, with_component):
    msgs = assemble(with_component)
    first = role_of(msgs[0]) if msgs else None
    has_sys = any(role_of(m) == "system" for m in msgs)
    print(f"[{label}] first_role={first!r}  has_system_msg={has_sys}  msg_count={len(msgs)}")
    return has_sys


if __name__ == "__main__":
    print("managed-path assembly: system-prompt survival check")
    with_sys = report("WITH SystemPromptComponent (post-fix) ", True)
    without_sys = report("WITHOUT component          (bug repro)", False)
    print()
    print("RESULT:",
          "PASS" if (with_sys and not without_sys)
          else ("UNEXPECTED" if with_sys == without_sys else "FAIL"),
          f"(with={with_sys}, without={without_sys})")
