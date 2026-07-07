"""
Comprehensive verification test for PR-0/1/2 context module features.

Tests:
- PR-0: All 10 handler to_messages() implementations
- PR-0: ContextProjector with all 7 component types
- PR-1: Semantic equivalence between use_context_items=True/False
- PR-2: HistoryProjector with all 3 projection purposes
- Integration: Full agent run with all components + history projector
"""
import os
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional
from threading import Event

_project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(_project_root / "sdk"))
sys.path.insert(0, str(_project_root / "backend"))

from utils.monitoring import monitoring_manager

from nexent.core.agents.context.handlers import register_all
from nexent.core.agents.context.item_handler_registry import ItemHandlerRegistry
from nexent.core.agents.context.context_item import (
    ContextItem,
    ContextItemType,
    AuthorityTier,
    RepresentationTier,
)
from nexent.core.agents.context.projector import ContextProjector
from nexent.core.agents.context.history_projector import HistoryProjector
from nexent.core.agents.agent_model import (
    SystemPromptComponent,
    ToolsComponent,
    SkillsComponent,
    MemoryComponent,
    KnowledgeBaseComponent,
    ManagedAgentsComponent,
    ExternalAgentsComponent,
)
from nexent.core.agents.summary_config import ContextManagerConfig
from nexent.core.agents.agent_context import ContextManager


def test_pr0_handlers():
    """PR-0: Test all 10 handler to_messages() implementations."""
    print("\n" + "=" * 70)
    print("PR-0: Testing all 10 handler to_messages() implementations")
    print("=" * 70)
    
    register_all()
    
    test_cases = [
        # (item_type, content, expected_message_count, expected_roles)
        (
            "SystemPromptHandler",
            ContextItemType.SYSTEM_PROMPT,
            "You are a helpful assistant",
            1,
            ["user"],
        ),
        (
            "ToolHandler",
            ContextItemType.TOOL,
            {"name": "search", "description": "Search the web"},
            1,
            ["user"],
        ),
        (
            "SkillHandler",
            ContextItemType.SKILL,
            {"name": "coding", "description": "Write code"},
            1,
            ["user"],
        ),
        (
            "MemoryHandler",
            ContextItemType.MEMORY,
            {"content": "User prefers Python", "memory_type": "user"},
            1,
            ["user"],
        ),
        (
            "KnowledgeBaseHandler",
            ContextItemType.KNOWLEDGE_BASE,
            "Retrieved knowledge about AI",
            1,
            ["user"],
        ),
        (
            "ManagedAgentHandler",
            ContextItemType.MANAGED_AGENT,
            {"name": "researcher", "description": "Research agent"},
            1,
            ["user"],
        ),
        (
            "ExternalAgentHandler",
            ContextItemType.EXTERNAL_AGENT,
            {"name": "external_api", "description": "External API agent"},
            1,
            ["user"],
        ),
        (
            "HistoryTurnHandler (both)",
            ContextItemType.HISTORY_TURN,
            {"user_query": "What is AI?", "assistant_response": "AI is artificial intelligence"},
            2,
            ["user", "assistant"],
        ),
        (
            "HistoryTurnHandler (user only)",
            ContextItemType.HISTORY_TURN,
            {"user_query": "What is AI?"},
            1,
            ["user"],
        ),
        (
            "HistoryTurnHandler (empty)",
            ContextItemType.HISTORY_TURN,
            {},
            0,
            [],
        ),
        (
            "ToolCallResultHandler",
            ContextItemType.TOOL_CALL_RESULT,
            {"tool_call": "search('AI')", "execution_result": "Found 10 results"},
            1,
            ["user"],
        ),
        (
            "WorkingMemoryHandler (active_goal)",
            ContextItemType.WORKING_MEMORY,
            {"type": "active_goal", "text": "Complete the task"},
            1,
            ["user"],
        ),
        (
            "WorkingMemoryHandler (pending_tool_call)",
            ContextItemType.WORKING_MEMORY,
            {"type": "pending_tool_call", "tool_call_id": "tc_123", "tool_content": "Searching..."},
            1,
            ["user"],
        ),
        (
            "WorkingMemoryHandler (default)",
            ContextItemType.WORKING_MEMORY,
            {"type": "other", "data": "some data"},
            1,
            ["user"],
        ),
    ]
    
    passed = 0
    failed = 0
    
    for name, item_type, content, expected_count, expected_roles in test_cases:
        item = ContextItem(
            item_id=f"test:{name}",
            item_type=item_type,
            content=content,
        )
        
        handler = ItemHandlerRegistry.get(item_type)
        messages = handler.to_messages(item)
        
        if len(messages) != expected_count:
            print(f"  ❌ {name}: expected {expected_count} messages, got {len(messages)}")
            failed += 1
            continue
        
        actual_roles = [msg["role"] for msg in messages]
        if actual_roles != expected_roles:
            print(f"  ❌ {name}: expected roles {expected_roles}, got {actual_roles}")
            failed += 1
            continue
        
        print(f"  ✅ {name}: {len(messages)} message(s), roles={actual_roles}")
        passed += 1
    
    print(f"\nPR-0 Handlers: {passed} passed, {failed} failed")
    return failed == 0


def test_pr0_projector():
    """PR-0: Test ContextProjector with all 7 component types."""
    print("\n" + "=" * 70)
    print("PR-0: Testing ContextProjector with all 7 component types")
    print("=" * 70)
    
    register_all()
    projector = ContextProjector()
    
    components = [
        SystemPromptComponent(content="You are helpful"),
        ToolsComponent(
            tools=[
                {"name": "search", "description": "Search"},
                {"name": "calculate", "description": "Calculate"},
            ],
            formatted_description="Available tools: search, calculate",
        ),
        SkillsComponent(
            skills=[{"name": "coding", "description": "Write code"}],
            formatted_description="Skills: coding",
        ),
        MemoryComponent(
            memories=[
                {"content": "User likes Python", "memory_type": "user"},
                {"content": "User is a developer", "memory_type": "user"},
            ],
            formatted_content="User preferences: Python, developer",
        ),
        KnowledgeBaseComponent(
            summary="AI knowledge base summary",
            kb_ids=["kb_1", "kb_2"],
        ),
        ManagedAgentsComponent(
            agents=[{"name": "researcher", "description": "Research agent"}],
            formatted_description="Managed agents: researcher",
        ),
        ExternalAgentsComponent(
            agents=[{"name": "external_api", "description": "External API"}],
            formatted_description="External agents: external_api",
        ),
    ]
    
    items = projector.project(components)
    
    expected_types = {
        ContextItemType.SYSTEM_PROMPT: 1,
        ContextItemType.TOOL: 2,
        ContextItemType.SKILL: 1,
        ContextItemType.MEMORY: 2,
        ContextItemType.KNOWLEDGE_BASE: 1,
        ContextItemType.MANAGED_AGENT: 1,
        ContextItemType.EXTERNAL_AGENT: 1,
    }
    
    actual_counts = {}
    for item in items:
        actual_counts[item.item_type] = actual_counts.get(item.item_type, 0) + 1
    
    print(f"  Total items projected: {len(items)}")
    
    passed = 0
    failed = 0
    
    for item_type, expected_count in expected_types.items():
        actual_count = actual_counts.get(item_type, 0)
        if actual_count == expected_count:
            print(f"  ✅ {item_type.value}: {actual_count} item(s)")
            passed += 1
        else:
            print(f"  ❌ {item_type.value}: expected {expected_count}, got {actual_count}")
            failed += 1
    
    has_source_ref = all("_source_component" in item.metadata for item in items)
    if has_source_ref:
        print(f"  ✅ All items have _source_component back-reference")
        passed += 1
    else:
        print(f"  ❌ Some items missing _source_component back-reference")
        failed += 1
    
    print(f"\nPR-0 Projector: {passed} passed, {failed} failed")
    return failed == 0


def test_pr1_semantic_equivalence():
    """PR-1: Test semantic equivalence between use_context_items=True/False."""
    print("\n" + "=" * 70)
    print("PR-1: Testing semantic equivalence (use_context_items=True vs False)")
    print("=" * 70)
    
    register_all()
    
    from smolagents.memory import AgentMemory
    
    components = [
        SystemPromptComponent(content="You are a helpful assistant"),
        ToolsComponent(
            tools=[{"name": "search", "description": "Search"}],
            formatted_description="Tools: search",
        ),
        MemoryComponent(
            memories=[{"content": "User fact", "memory_type": "user"}],
            formatted_content="Memory: User fact",
        ),
    ]
    
    config_false = ContextManagerConfig(
        enabled=True,
        use_context_items=False,
        token_threshold=100000,
        strategy="full",
    )
    
    config_true = ContextManagerConfig(
        enabled=True,
        use_context_items=True,
        token_threshold=100000,
        strategy="full",
    )
    
    cm_false = ContextManager(config=config_false)
    cm_true = ContextManager(config=config_true)
    
    from smolagents.memory import SystemPromptStep
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
    
    print(f"  OLD path (use_context_items=False): {len(msgs_false)} messages")
    print(f"  NEW path (use_context_items=True): {len(msgs_true)} messages")
    
    if len(msgs_false) != len(msgs_true):
        print(f"  ❌ Message count mismatch")
        return False
    
    for i, (msg_f, msg_t) in enumerate(zip(msgs_false, msgs_true)):
        if msg_f["role"] != msg_t["role"]:
            print(f"  ❌ Message {i} role mismatch: {msg_f['role']} vs {msg_t['role']}")
            return False
        
        content_f = msg_f["content"][0]["text"] if msg_f["content"] else ""
        content_t = msg_t["content"][0]["text"] if msg_t["content"] else ""
        
        if content_f != content_t:
            print(f"  ❌ Message {i} content mismatch")
            print(f"     OLD: {content_f[:100]}...")
            print(f"     NEW: {content_t[:100]}...")
            return False
    
    print(f"  ✅ All {len(msgs_false)} messages are semantically equivalent")
    print(f"\nPR-1 Semantic Equivalence: PASSED")
    return True


def test_pr2_history_projector():
    """PR-2: Test HistoryProjector with all 3 projection purposes."""
    print("\n" + "=" * 70)
    print("PR-2: Testing HistoryProjector with all 3 projection purposes")
    print("=" * 70)
    
    register_all()
    
    def mock_query_units(conversation_id: int, run_id: Optional[int] = None) -> List[Dict[str, Any]]:
        units = [
            {"unit_id": 1, "unit_type": "user_input", "unit_content": "What is AI?", "run_id": 1, "step_id": 1, "tool_call_id": None},
            {"unit_id": 2, "unit_type": "final_answer", "unit_content": "AI is artificial intelligence", "run_id": 1, "step_id": 1, "tool_call_id": None},
            {"unit_id": 3, "unit_type": "tool", "unit_content": "search('machine learning')", "run_id": 1, "step_id": 2, "tool_call_id": "tc_001"},
            {"unit_id": 4, "unit_type": "execution_logs", "unit_content": "Found 5 results", "run_id": 1, "step_id": 2, "tool_call_id": "tc_001"},
            {"unit_id": 5, "unit_type": "model_output_thinking", "unit_content": "Let me think about this...", "run_id": 1, "step_id": 2, "tool_call_id": None},
            {"unit_id": 6, "unit_type": "user_input", "unit_content": "Tell me more", "run_id": 2, "step_id": 1, "tool_call_id": None},
        ]
        if run_id is not None:
            return [u for u in units if u.get("run_id") == run_id]
        return units
    
    projector = HistoryProjector(query_units_fn=mock_query_units)
    
    passed = 0
    failed = 0
    
    print("\n  Testing purpose='model_context':")
    items_mc = projector.project(conversation_id=123, purpose="model_context")
    
    mc_types = {}
    for item in items_mc:
        mc_types[item.item_type] = mc_types.get(item.item_type, 0) + 1
    
    if ContextItemType.HISTORY_TURN in mc_types:
        print(f"    ✅ HISTORY_TURN: {mc_types[ContextItemType.HISTORY_TURN]} item(s)")
        passed += 1
    else:
        print(f"    ❌ Missing HISTORY_TURN items")
        failed += 1
    
    if ContextItemType.TOOL_CALL_RESULT in mc_types:
        print(f"    ✅ TOOL_CALL_RESULT: {mc_types[ContextItemType.TOOL_CALL_RESULT]} item(s)")
        passed += 1
    else:
        print(f"    ❌ Missing TOOL_CALL_RESULT items")
        failed += 1
    
    if ContextItemType.WORKING_MEMORY not in mc_types:
        print(f"    ✅ WORKING_MEMORY correctly excluded")
        passed += 1
    else:
        print(f"    ❌ WORKING_MEMORY should not be in model_context")
        failed += 1
    
    print("\n  Testing purpose='resume':")
    items_resume = projector.project(conversation_id=123, purpose="resume")
    
    resume_types = {}
    for item in items_resume:
        resume_types[item.item_type] = resume_types.get(item.item_type, 0) + 1
    
    if ContextItemType.WORKING_MEMORY in resume_types:
        print(f"    ✅ WORKING_MEMORY: {resume_types[ContextItemType.WORKING_MEMORY]} item(s)")
        passed += 1
    else:
        print(f"    ❌ Missing WORKING_MEMORY items")
        failed += 1
    
    print("\n  Testing purpose='chat':")
    items_chat = projector.project(conversation_id=123, purpose="chat")
    
    chat_types = {}
    for item in items_chat:
        chat_types[item.item_type] = chat_types.get(item.item_type, 0) + 1
    
    if ContextItemType.HISTORY_TURN in chat_types:
        print(f"    ✅ HISTORY_TURN: {chat_types[ContextItemType.HISTORY_TURN]} item(s)")
        passed += 1
    else:
        print(f"    ❌ Missing HISTORY_TURN items")
        failed += 1
    
    has_thinking = any(
        "thinking" in str(item.content).lower()
        for item in items_chat
        if item.item_type == ContextItemType.HISTORY_TURN
    )
    if has_thinking:
        print(f"    ✅ Chat includes thinking content")
        passed += 1
    else:
        print(f"    ⚠️  Chat may not include thinking (check implementation)")
    
    print(f"\nPR-2 HistoryProjector: {passed} passed, {failed} failed")
    return failed == 0


def test_integration_full_agent():
    """Integration: Full agent run with all components + history projector."""
    print("\n" + "=" * 70)
    print("Integration: Full agent run with all components + history projector")
    print("=" * 70)
    
    try:
        import asyncio
        from dotenv import load_dotenv
        load_dotenv(override=True)
        
        from nexent.core.utils.observer import MessageObserver
        from nexent.core.agents.agent_model import ModelConfig, AgentConfig, AgentRunInfo
        from nexent.core.agents.run_agent import agent_run
        from nexent.monitor import agent_monitoring_context, AgentRunMetadata
        
        def mock_query_units(conversation_id: int, run_id: Optional[int] = None) -> List[Dict[str, Any]]:
            return [
                {"unit_id": 1, "unit_type": "user_input", "unit_content": "Previous question", "run_id": 1, "step_id": 1, "tool_call_id": None},
                {"unit_id": 2, "unit_type": "final_answer", "unit_content": "Previous answer", "run_id": 1, "step_id": 1, "tool_call_id": None},
            ]
        
        history_projector = HistoryProjector(query_units_fn=mock_query_units)
        
        cm_config = ContextManagerConfig(
            enabled=True,
            use_context_items=True,
            token_threshold=100000,
            strategy="full",
            history_projector=history_projector,
        )
        
        components = [
            SystemPromptComponent(content="You are a helpful assistant. Answer concisely."),
            ToolsComponent(
                tools=[{"name": "search", "description": "Search the web"}],
                formatted_description="Available tools: search",
            ),
            MemoryComponent(
                memories=[{"content": "User prefers English", "memory_type": "user"}],
                formatted_content="User preferences: English",
            ),
        ]
        
        model_cfg = ModelConfig(
            cite_name="main_model",
            api_key=os.environ.get("DEFAULT_MODEL_API_KEY", ""),
            model_name=os.environ.get("DEFAULT_MODEL", "qwen3.6-plus"),
            url=os.environ.get("DEFAULT_MODEL_ENDPOINT", ""),
            temperature=0.1,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        
        agent_cfg = AgentConfig(
            name="integration_test_agent",
            description="Full integration test",
            model_name="main_model",
            tools=[],
            max_steps=3,
            context_manager_config=cm_config,
            context_components=components,
            conversation_id=12345,
        )
        
        observer = MessageObserver(lang="en")
        stop_event = Event()
        
        run_info = AgentRunInfo(
            query="What is 2+2?",
            model_config_list=[model_cfg],
            observer=observer,
            agent_config=agent_cfg,
            stop_event=stop_event,
        )
        
        metadata = AgentRunMetadata(
            agent_name="integration_test_agent",
            query="What is 2+2?",
            tenant_id="test",
            user_id="integration_test",
            conversation_id=12345,
            model_name=model_cfg.model_name,
        )
        
        async def run():
            final_answer = ""
            with agent_monitoring_context(metadata):
                async for message in agent_run(run_info):
                    msg = message if isinstance(message, dict) else eval(message)
                    if msg.get("type") == "final_answer":
                        final_answer = msg.get("content", "")
            return final_answer
        
        answer = asyncio.run(run())
        
        if answer:
            print(f"  ✅ Agent completed with answer: {answer[:100]}")
            print(f"\nIntegration Test: PASSED")
            return True
        else:
            print(f"  ❌ Agent did not produce final answer")
            print(f"\nIntegration Test: FAILED")
            return False
            
    except Exception as e:
        print(f"  ❌ Integration test failed with error: {e}")
        import traceback
        traceback.print_exc()
        print(f"\nIntegration Test: FAILED")
        return False


def main():
    print("=" * 70)
    print("Comprehensive PR-0/1/2 Context Module Verification")
    print("=" * 70)
    
    results = {}
    
    results["PR-0 Handlers"] = test_pr0_handlers()
    results["PR-0 Projector"] = test_pr0_projector()
    results["PR-1 Equivalence"] = test_pr1_semantic_equivalence()
    results["PR-2 HistoryProjector"] = test_pr2_history_projector()
    results["Integration"] = test_integration_full_agent()
    
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    for test_name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"  {status}: {test_name}")
    
    all_passed = all(results.values())
    print("\n" + "=" * 70)
    if all_passed:
        print("ALL TESTS PASSED ✅")
    else:
        print("SOME TESTS FAILED ❌")
    print("=" * 70)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
