# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Post-response context maintenance over the real HTTP/SSE model pipeline."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace

import pytest
from shared.model_service_profiles import resolved_profile_for_test
from smolagents.memory import ActionStep, TaskStep
from smolagents.monitoring import Timing

from nexent.core.agents.context import ContextItemInput, ContextManager, ContextManagerConfig
from nexent.core.agents.cores.smolagents.context import ManagedContextRuntime
from nexent.core.model_service.compatibility.legacy_chat_model import LegacyChatModel
from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile
from nexent.core.models.capacity_budget import CapacityReservePolicy, ContextBudgetCalculator
from nexent.core.models.capacity_resolver import resolve_capacity


pytestmark = [pytest.mark.case_id("CONTEXT-POST-RESPONSE-D3-001"), pytest.mark.stage("D3")]


@pytest.mark.parametrize("old_input,old_reserve", [(2000, 1024), (9000, 512)])
@pytest.mark.parametrize("entrypoint", ["runtime", "agent", "agent_tools"])
def test_usage_calibrates_post_response_maintenance(old_input, old_reserve, entrypoint):
    requests, main_requests, summaries = [], [], []
    window = 100000 if entrypoint.startswith("agent") else 10000
    actual_input = window - 1000

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            is_summary = "Conversation content to summarize:" in json.dumps(requests[-1])
            (summaries if is_summary else main_requests).append(requests[-1])
            returned_text = "<final_answer>HELLO</final_answer>" if entrypoint.startswith("agent") else "HELLO"
            if entrypoint == "agent_tools" and len(main_requests) == 1 and not is_summary:
                returned_text = '<code>print("</code>")\nprint("TOOL_OK")</code>'
            if is_summary:
                returned_text = "COMPACT_VIEW"
            request_input = 20000 if entrypoint == "agent_tools" and len(main_requests) > 1 else actual_input
            chunk = {"id": "context-controlled", "model": "qwen3.5-plus", "choices": [
                {"index": 0, "delta": {"role": "assistant", "content": returned_text}, "finish_reason": "stop"}]}
            usage = {"id": "context-controlled", "choices": [], "usage": {
                "prompt_tokens": request_input, "completion_tokens": 5, "total_tokens": request_input + 5,
                "prompt_tokens_details": {"cached_tokens": 8000}}}
            body = ("data: " + json.dumps(chunk) + "\n\ndata: " + json.dumps(usage)
                    + "\n\ndata: [DONE]\n\n").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        data = resolved_profile_for_test(f"http://127.0.0.1:{server.server_port}/v1").model_dump(mode="json")
        data["capabilities"]["context"] = {"combined_window": window, "input_limit": old_input, "output_limit": 2048}
        data["context_configuration"]["output_reserve_tokens"] = old_reserve
        data["parameter_values"]["max_output_tokens"] = 4096
        model = LegacyChatModel.from_profile(ResolvedModelProfile.model_validate(data), "controlled-key")
        capacity = resolve_capacity(model_id="qwen3.5-plus", provider="alibaba", capability_profiles={},
            operator_overrides={"context_window_tokens": window, "max_output_tokens": 2048,
                                "max_input_tokens": old_input, "default_output_reserve_tokens": old_reserve})
        budget = ContextBudgetCalculator().calculate_context_budget(
            capacity_snapshot=capacity, reserve_policy=CapacityReservePolicy())
        assert budget.compaction_trigger_threshold_tokens == window - min(window // 5, 20000)
        assert budget.compaction_target_tokens == window - 2 * min(window // 5, 20000)
        model.context_budget_snapshot = budget
        runtime = ManagedContextRuntime(ContextManager(ContextManagerConfig(
            context_window_tokens=window, effective_input_limit_tokens=window,
            compaction_trigger_threshold_tokens=budget.compaction_trigger_threshold_tokens,
            compaction_target_tokens=budget.compaction_target_tokens,
            policy_layers={"platform": {"processing_mode": "adaptive_compact"}})), items=[
                ContextItemInput(id="old-turn", type="conversation_turn", content={
                    "user_message": "evidence " * (10000 if entrypoint.startswith("agent") else 1000),
                    "assistant_final_answer": "OLD_ANSWER", "user_message_id": 1, "assistant_message_id": 2})])
        if entrypoint.startswith("agent"):
            from nexent.core.agents.cores.smolagents.core_agent import CoreAgent
            agent = CoreAgent(observer=model.observer, model=model, tools=[], name="context_policy",
                enable_protocol_repair_retry=True, max_steps=2, context_runtime=runtime)
            assert str(agent.run("Respond briefly")) == "HELLO"
            memory = agent.memory
            first_size = len(str(requests[0]["messages"]))
            after = runtime.context_manager.assemble_final_context(model=model, memory=memory,
                current_run_start_idx=0, run_context=runtime._run_context)
        else:
            memory = SimpleNamespace(steps=[TaskStep(task="Respond briefly")])
            first = runtime.prepare_step(model=model, memory=memory, current_run_start_idx=0)
            assert not runtime.context_manager._agent_history and not summaries
            first_size = len(str(first.messages))
            response = model.generate(first.messages)
            assert response.content == "HELLO" and response.token_usage.input_tokens == actual_input
            memory.steps.append(ActionStep(step_number=1, model_output="HELLO", model_output_message=response,
                timing=Timing(start_time=0)))
            response.nexent_context_accepted = True
            runtime.complete_step(model=model, memory=memory, current_run_start_idx=0, response=response)
            after = runtime.prepare_step(model=model, memory=memory, current_run_start_idx=0)
        assert runtime.context_manager._agent_triggered
        assert runtime.context_manager._agent_history.content["summary"]["markdown"] == "COMPACT_VIEW"
        assert len(summaries) == (2 if entrypoint.startswith("agent") else 1)
        assert runtime.usage_baseline.actual_input_tokens == (20000 if entrypoint == "agent_tools" else None)
        assert len(str(after.messages)) < first_size
        model.generate(after.messages)
        if entrypoint == "runtime":
            checkpoint = runtime.finish_run(model=model, memory=memory, current_run_start_idx=0, final_output="HELLO")
        else:
            events = [json.loads(value) for value in model.observer.message_query]
            checkpoint = next(json.loads(value["content"]) for value in events
                              if value.get("type") == "history_summary"
                              and "current_completed_turn" in value.get("content", ""))
        assert checkpoint["coverage_scope"] == "current_completed_turn"
        assert checkpoint["history_tail_message_id"] == 2
        assert "covered_through_message_id" not in checkpoint
        assert len(requests) == (5 if entrypoint == "agent_tools" else 4)
        assert len(summaries) == 2
        completion_material = str(summaries[-1]["messages"])
        assert "completed_turn_tail" in completion_material and "HELLO" in completion_material
        if entrypoint == "agent_tools":
            assert [request["stop"] for request in main_requests[:2]] == [["<RESULT>"]] * 2
            results = [message for message in main_requests[1]["messages"]
                       if message["role"] == "user" and "<RESULT>" in str(message["content"])]
            assert results and "&lt;/code&gt;\nTOOL_OK" in str(results[-1]["content"]).replace("\\n", "\n")
            assert "TOOL_OK" in completion_material
            assert len(str(main_requests[1]["messages"])) < len(str(main_requests[0]["messages"]))
        for body in requests:
            assert not {"max_tokens", "max_completion_tokens", "max_output_tokens"}.intersection(body)
        wire_text = "\n".join(
            message["content"] if isinstance(message.get("content"), str)
            else "".join(part.get("text", "") for part in message.get("content", []) if isinstance(part, dict))
            for message in requests[0]["messages"])
        assert memory.steps[0].task.startswith("Respond briefly")
        assert memory.steps[0].task in wire_text
        assert "HELLO" in memory.steps[-1].model_output
        assert runtime.finalize_evidence(status="success").model_call_count == (2 if entrypoint == "agent_tools" else 1 if entrypoint == "agent" else 2)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()
