"""Test assemble_final_context equivalence under budget pressure."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent / "sdk"))
sys.path.insert(0, str(Path(__file__).parent / "backend"))

from smolagents.memory import AgentMemory, SystemPromptStep
from nexent.core.agents.context.handlers import register_all
from nexent.core.agents.summary_config import ContextManagerConfig
from nexent.core.agents.agent_context import ContextManager
from nexent.core.agents.agent_model import (
    SystemPromptComponent,
    ToolsComponent,
    MemoryComponent,
    KnowledgeBaseComponent,
)

register_all()

components = [
    SystemPromptComponent(content="You are a helpful assistant. " * 100),
    ToolsComponent(
        tools=[{"name": f"tool_{i}", "description": f"Tool {i} " * 20} for i in range(10)],
        formatted_description="Tools: " + " ".join([f"tool_{i}" for i in range(10)]) + " " * 500,
    ),
    MemoryComponent(
        memories=[{"content": f"Memory {i} " * 30, "memory_type": "user"} for i in range(5)],
        formatted_content="Memories: " + " ".join([f"fact_{i}" for i in range(5)]) + " " * 300,
    ),
    KnowledgeBaseComponent(
        summary="KB summary " * 50,
        kb_ids=["kb_1"],
    ),
]

small_budget = 500

config_false = ContextManagerConfig(
    enabled=True,
    use_context_items=False,
    token_threshold=small_budget,
    strategy="token_budget",
)

config_true = ContextManagerConfig(
    enabled=True,
    use_context_items=True,
    token_threshold=small_budget,
    strategy="token_budget",
)

cm_false = ContextManager(config=config_false)
cm_true = ContextManager(config=config_true)

memory = AgentMemory(system_prompt=SystemPromptStep(system_prompt=""))
mock_model = MagicMock()

final_ctx_false = cm_false.assemble_final_context(
    model=mock_model,
    memory=memory,
    current_run_start_idx=0,
    tools=[],
    purpose="step",
)

final_ctx_true = cm_true.assemble_final_context(
    model=mock_model,
    memory=memory,
    current_run_start_idx=0,
    tools=[],
    purpose="step",
)

msgs_false = final_ctx_false.messages
msgs_true = final_ctx_true.messages

print("=" * 70)
print("assemble_final_context Equivalence UNDER BUDGET PRESSURE")
print("=" * 70)
print(f"\nToken budget: {small_budget}")
print(f"Components: {len(components)}")
print(f"\nOLD path (use_context_items=False): {len(msgs_false)} messages")
print(f"NEW path (use_context_items=True):  {len(msgs_true)} messages")

if len(msgs_false) != len(msgs_true):
    print(f"\n❌ MESSAGE COUNT MISMATCH!")
    print(f"   Difference: {abs(len(msgs_false) - len(msgs_true))} messages")
    print(f"\n   Root cause: NEW path bypasses strategy selection in")
    print(f"   assemble_final_context(). It projects ALL components via")
    print(f"   project_context_items() instead of using strategy-selected")
    print(f"   components from build_context_messages().")
    print(f"\n   Production risk: Under budget pressure, NEW path includes")
    print(f"   more component messages, leaving less room for conversation")
    print(f"   history before compression kicks in.")
    sys.exit(1)
else:
    print(f"\n✅ Message count matches")
    
    for i, (msg_f, msg_t) in enumerate(zip(msgs_false, msgs_true)):
        if msg_f["role"] != msg_t["role"]:
            print(f"\n❌ Message {i} role mismatch")
            sys.exit(1)
        
        content_f = msg_f["content"][0]["text"] if msg_f["content"] else ""
        content_t = msg_t["content"][0]["text"] if msg_t["content"] else ""
        
        if content_f != content_t:
            print(f"\n❌ Message {i} content mismatch")
            sys.exit(1)
    
    print(f"✅ All messages semantically equivalent")
    print(f"\n{'=' * 70}")
    print("PASSED - Safe to merge")
    print("=" * 70)
    sys.exit(0)
