# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Post-response context maintenance over the real HTTP/SSE model pipeline."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace

import pytest
from smolagents.memory import TaskStep, ActionStep
from smolagents.monitoring import Timing
from nexent.core.agents.context import ContextItemInput, ContextManager, ContextManagerConfig, ManagedContextRuntime
from nexent.core.models.capacity_budget import CapacityReservePolicy, ContextBudgetCalculator
from nexent.core.models.capacity_resolver import resolve_capacity
from nexent.core.model_service.compatibility.legacy_chat_model import LegacyChatModel
from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile
from shared.model_service_profiles import resolved_profile_for_test

pytestmark = [pytest.mark.case_id("CONTEXT-POST-RESPONSE-D3-001"), pytest.mark.stage("D3")]


@pytest.mark.parametrize("old_input,old_reserve", [(2000, 1024), (9000, 512)])
@pytest.mark.parametrize("entrypoint", ["runtime", "agent", "agent_tools"])
def test_usage_calibrates_post_response_maintenance(old_input, old_reserve, entrypoint):
    requests = []
    window = 100000 if entrypoint.startswith("agent") else 10000
    actual_input = window - 1000

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            returned_text = "<final_answer>HELLO</final_answer>" if entrypoint.startswith("agent") else "HELLO"
            if entrypoint == "agent_tools" and len(requests) == 1:
                returned_text = '<code>print("TOOL_OK")</code>'
            request_input = 20000 if entrypoint == "agent_tools" and len(requests) > 1 else actual_input
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
                ContextItemInput(id="kb:large", type="knowledge_base", content={"text": "evidence " * (10000 if entrypoint.startswith("agent") else 1000)})])
        if entrypoint.startswith("agent"):
            from nexent.core.agents.core_agent import CoreAgent
            agent = CoreAgent(observer=model.observer, model=model, tools=[], name="context_policy",
                enable_protocol_repair_retry=True, max_steps=2, context_runtime=runtime)
            assert str(agent.run("Respond briefly")) == "HELLO"
            memory = agent.memory
            evidence = runtime.last_maintenance_evidence
            first_size = len(str(requests[0]["messages"]))
            after = runtime.context_manager.assemble_final_context(model=model, memory=memory,
                current_run_start_idx=0, run_context=runtime._run_context)
        else:
            memory = SimpleNamespace(steps=[TaskStep(task="Respond briefly")])
            first = runtime.prepare_step(model=model, memory=memory, current_run_start_idx=0)
            assert not runtime.context_manager._representation_overrides
            first_size = len(str(first.messages))
            response = model.generate(first.messages)
            assert response.content == "HELLO" and response.token_usage.input_tokens == actual_input
            memory.steps.append(ActionStep(step_number=1, model_output="HELLO", model_output_message=response,
                timing=Timing(start_time=0)))
            evidence = runtime.complete_step(model=model, memory=memory, current_run_start_idx=0, response=response)
            after = runtime.prepare_step(model=model, memory=memory, current_run_start_idx=0)
        assert evidence.maintenance_phase == "post_response"
        assert evidence.usage_source == "provider_calibrated" and evidence.provider_input_tokens == actual_input
        assert runtime.context_manager._representation_overrides
        assert runtime.usage_baseline.actual_input_tokens == (20000 if entrypoint == "agent_tools" else None)
        assert len(str(after.messages)) < first_size
        model.generate(after.messages)
        assert len(requests) == (3 if entrypoint == "agent_tools" else 2)
        if entrypoint == "agent_tools":
            assert "TOOL_OK" in str(requests[1]["messages"])
            assert len(str(requests[1]["messages"])) < len(str(requests[0]["messages"]))
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
