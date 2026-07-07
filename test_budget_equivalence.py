"""Test semantic equivalence under token budget pressure."""
import sys
from pathlib import Path

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

# Create components that EXCEED a small budget
components = [
    SystemPromptComponent(content="You are a helpful assistant. " * 100),  # ~500 tokens
    ToolsComponent(
        tools=[{"name": f"tool_{i}", "description": f"Tool {i} description " * 20} for i in range(10)],
        formatted_description="Available tools: " + ", ".join([f"tool_{i}" for i in range(10)]) + " " * 500,
    ),
    MemoryComponent(
        memories=[{"content": f"Memory fact {i} " * 30, "memory_type": "user"} for i in range(5)],
        formatted_content="User memories: " + " ".join([f"fact_{i}" for i in range(5)]) + " " * 300,
    ),
    KnowledgeBaseComponent(
        summary="Knowledge base summary " * 50,
        kb_ids=["kb_1"],
    ),
]

# Small budget to force strategy filtering
small_budget = 500  # tokens

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

memory_false = AgentMemory(system_prompt=SystemPromptStep(system_prompt=""))
memory_true = AgentMemory(system_prompt=SystemPromptStep(system_prompt=""))

run_ctx_false = cm_false.prepare_run_context(
    memory=memory_false,
    fallback_system_prompt="",
    components=components,
)

run_ctx_true = cm_true.prepare_run_context(
    memory=memory_true,
    fallback_system_prompt="",
    components=components,
)

msgs_false = list(run_ctx_false.component_messages)
msgs_true = list(run_ctx_true.component_messages)

print("=" * 70)
print("Semantic Equivalence Test UNDER BUDGET PRESSURE")
print("=" * 70)
print(f"\nToken budget: {small_budget}")
print(f"Components: {len(components)} (SystemPrompt + Tools + Memory + KB)")
print(f"\nOLD path (use_context_items=False): {len(msgs_false)} messages")
print(f"NEW path (use_context_items=True):  {len(msgs_true)} messages")

if len(msgs_false) != len(msgs_true):
    print(f"\n❌ MESSAGE COUNT MISMATCH!")
    print(f"   Difference: {abs(len(msgs_false) - len(msgs_true))} messages")
    print(f"\n   This means the NEW path bypasses strategy selection!")
    print(f"   Under budget pressure, it includes ALL components instead of")
    print(f"   strategy-selected components.")
    sys.exit(1)
else:
    print(f"\n✅ Message count matches")
    
    # Check content
    for i, (msg_f, msg_t) in enumerate(zip(msgs_false, msgs_true)):
        if msg_f["role"] != msg_t["role"]:
            print(f"\n❌ Message {i} role mismatch")
            sys.exit(1)
        
        content_f = msg_f["content"][0]["text"] if msg_f["content"] else ""
        content_t = msg_t["content"][0]["text"] if msg_t["content"] else ""
        
        if content_f != content_t:
            print(f"\n❌ Message {i} content mismatch")
            print(f"   OLD: {content_f[:100]}...")
            print(f"   NEW: {content_t[:100]}...")
            sys.exit(1)
    
    print(f"✅ All {len(msgs_false)} messages are semantically equivalent")
    print(f"\n{'=' * 70}")
    print("PASSED")
    print("=" * 70)
    sys.exit(0)
